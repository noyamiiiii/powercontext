# 一页技术说明

**作品**：端侧向量化 × seekdb 混合检索 · 迷你知识库
**赛题**：2026 OceanBase 数据库大赛 · seekdb × 阶跃星辰 —— 端侧 AI 推理性能优化与 seekdb 混合检索

---

## 一句话

浏览器用 Transformers.js 把文本变成 512 维向量（WebGPU FP16，失败自动降级 WASM INT8），向量经 HTTP 交给嵌入式 seekdb；检索时由 seekdb 在**库内**用 `hybridSearch` 同时跑 HNSW 向量召回与 ngram 全文召回，再用 RRF 融合成一张排名表 —— 全程没有一行云端推理调用。

---

## 为什么这样切分

赛题的两条硬约束把架构逼成了唯一解：

1. **推理必须在用户设备** → embedding 只能在浏览器里算。
2. **必须用 seekdb 做混合检索** → 融合必须发生在数据库内部，不能在应用层拼两个列表。

于是分成两段：**前端负责「算」，后端负责「存与融合」**。前端只发向量和原文，后端不碰任何模型（集合的 `embeddingFunction: null` 从 schema 层面堵死服务端重算向量的可能）。

```
浏览器                                    Node 服务（同机）
─────────                                ─────────────────
文本 → 切片 → pipeline(WebGPU/WASM) ─┐
                                    ├─► POST /documents ─► collection.add()
512 维归一化向量（不出设备）         │                      + refresh_index()
                                    │
查询 → 指令前缀 → 同一 pipeline ─────┴─► POST /search ────► collection.hybridSearch()
                                                             ├ 全文召回（ngram）
                                                             ├ 向量召回（HNSW cosine）
                                                             └ RRF 融合 ← 在库内
```

---

## 三个关键决策

### 1. 后端选型：WebGPU 优先，但默认值是「会失败」

候选链写成 `webgpu/fp16 → wasm/int8 → wasm/q8 → wasm/fp32`，每一环都有 60 s 超时兜底。这不是防御性编程，是实测结论：GPU 驱动会在没有任何错误、没有任何进度的情况下卡死会话创建，没有超时的话 UI 就永久白屏。每次降级都把原因写进 `backend.reason`，状态栏原样展示给用户 —— 用户永远知道自己此刻在什么后端上跑。

实测差距很大（详见 `BENCHMARK.md`）：

| | 加载 | 文档吞吐 | 查询延迟 |
| --- | --- | --- | --- |
| WebGPU FP16 | 2775 ms | 176.2 doc/s | 17.1 ms |
| WASM INT8 | 292 ms | 5.5 doc/s | 62.4 ms |

但加载时间是反的。所以降级不是「变慢」，是「换了一组权衡」——这个事实比「WebGPU 更好」更有信息量，也解释了为什么不能只留一条路。

### 2. batch size = 8，不是拍脑袋

对同一批 24 段文档扫 `1 / 4 / 8 / 16`：WebGPU 得到 47.5 / 195.5 / **310.8** / 245.3 doc/s，bs=16 反而回落。默认值 8 就是这条曲线的峰值。WASM 侧则几乎不动（5.4→5.9），因为单线程下批量化只省调用开销，省不出并行度。

### 3. WASM 默认单线程 —— 一个如实记录的妥协

页面已满足跨源隔离（`crossOriginIsolated = true`），`SharedArrayBuffer` 可用，多线程 WASM 的前置条件都齐了。但一旦开 `threads=4`，会话创建就永久挂起：拿不到错误、等不到完成，还会把渲染线程一起楔住（连截图都取不到）。这是上游 `onnxruntime-web` 在 Chrome/Windows 上的 worker pool 缺陷。

所以默认固定 1 线程，并留了 `window.__MINIKB_WASM_THREADS__` 显式开关。这是环境限制，不是设计选择，写在文档里而不是藏起来。

---

## 数据库侧

**Schema**（每个知识库一个集合 `kb_<slug>`，双索引建在同一集合上）：

| 索引 | 配置 | 用途 |
| --- | --- | --- |
| 向量 | HNSW，`dim=512`，`cosine`，`m=16`，`ef_construction=200` | 语义召回 |
| 全文 | `ngram`，`ngram_token_size=2` | 关键词召回，中文免词典 |

**混合检索**是单次库内调用，不是应用层拼装：

```ts
collection.hybridSearch({
  query: { whereDocument: { $contains: queryText }, nResults: topK },  // 全文
  knn:   { queryEmbeddings: [queryEmbedding],    nResults: topK },     // 向量
  rank:  { rrf: { rankWindowSize: 60, rankConstant: 60 } },            // 库内融合
  nResults: topK,
})
```

**索引刷新**三档可切：`always`（写完即刷）/ `deferred`（检索前刷，批量导入友好）/ `manual`（只手动刷）。`deferred` 下的脏标记是**幂等**的 —— 连续导入 10 批只会在下一次检索前刷新一次。

**分数语义**在仓储层就统一了：向量检索把余弦距离转成 `1 - distance`（越大越像），混合检索的 RRF 值本身就是「越大越好」的融合分，两者在前端可以直接同向排序。这个转换只发生在一个地方。

---

## 工程质量

| 项 | 状态 |
| --- | --- |
| 分层 | 控制器（zod 校验）→ 服务（业务规则/计时/刷新策略）→ 仓储（唯一接触 SDK 的层） |
| 服务层测试 | `createKnowledgeService(deps)` 依赖注入，**12 个契约测试全绿**（内存替身，不依赖数据库） |
| 配置 | 全部环境变量经 zod 校验，**配错直接启动失败**，不在运行时才炸 |
| 类型 | `tsc --noEmit` 零错误 |
| 可观测 | 结构化 JSON 日志 + `requestId` 贯穿，错误响应里带同一个 `requestId` |
| 离线可跑 | `env.allowRemoteModels = false`，权重从 `public/models/` 加载，断网可用 |

**已知限制（如实说明）**：`seekdb` 1.4.0 的 `@seekdb/js-bindings` 在 `win32-x64` 上 `open()` 时段错误退出（Node 20/22 均复现，全新目录亦复现，数据目录已正常创建）。因此本机的数据库阶段耗时未取到真实数字，`BENCHMARK.md` 第 5 节明确标注为缺失而非估算。应对是三层：`SEEKDB_MODE=server` 指向 Linux 侧 seekdb、服务层依赖注入、契约测试覆盖全部业务规则 —— 换到 Linux 只需执行 `npm run bench -- --stage all` 即可补齐那三列。

---

## 数据一览

| 指标 | 值 |
| --- | --- |
| 模型 | `Xenova/bge-small-zh-v1.5`，24M 参数，512 维，MIT |
| 权重体积 | FP32 90.5 MB / FP16 45.3 MB（2.00x）/ INT8 22.8 MB（**3.97x**） |
| 量化质量（CPU 隔离对比） | INT8 vs FP32：Recall@5 与 @10 均 100%/100%，nDCG@10 0.963 vs 1.000，MRR 0.958 vs 1.000 |
| 量化速度收益 | INT8 比 FP32 快 32%（226.8 vs 171.8 doc/s） |
| 端侧查询延迟 | WebGPU 17.1 ms / WASM 62.4 ms |

INT8 的结论是：**召回一点没掉，只在少数查询里换了第 2、3 位的顺序**。对展示 Top-5 的知识库场景，用 3.97 倍体积压缩换这个代价是划算的 —— 这是「选 INT8 做默认降级档」的直接依据，不是默认值就是好的。

---

## 复现

```bash
npm install && npm run setup && npm run dev   # → http://localhost:5173
npm test                                      # 12 个契约测试
npm run bench -- --stage embed --dtype int8 --dtype fp32
```

详细数据与测试方法见 `BENCHMARK.md`，启动与排查见 `README.md`。
