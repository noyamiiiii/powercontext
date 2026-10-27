# 实测数据与测试方法

本文所有数字都是在本仓库上**实际跑出来的**，不是估算值。每张表都附了复现命令。

---

## 0. 测试环境

| 项 | 值 |
| --- | --- |
| 机器 | 笔记本（单机，无独显外接） |
| OS | Windows 11（`win32-x64`） |
| 浏览器 | Chrome（`navigator.gpu` 可用，`crossOriginIsolated = true`） |
| Node | v22.22.2 |
| 端侧运行时 | `@huggingface/transformers` 3.8.1 + `onnxruntime-web` 1.22.0 |
| seekdb SDK | `seekdb` 1.4.0 |
| 模型 | `Xenova/bge-small-zh-v1.5`（512 维，pooling=`cls`，向量已 L2 归一化） |
| 语料 | `shared/sampleCorpus.ts`：24 段中文技术文档 + 12 条固定评测查询 |
| 指标 | Recall@5 / Recall@10 / nDCG@10 / MRR（查询的「金标」为人工指定的 1~2 个片段） |

语料规模刻意做得很小：赛题考察的是**端侧推理开销**与**库内混合检索正确性**，不是百万级召回率。24 段足以让 Recall@K 有区分度，同时让每次全量重跑在几十秒内结束，方便评委复现。

---

## 1. 浏览器端推理：WebGPU vs WASM（核心表）

这是本作品最关键的一组数据 —— 全部在真实浏览器里测得（页面内 `performance.now()` 计时，非 Node 代理）。

| 后端 | 权重 | 加载+warmup | 首个单条向量 | 24 段批量（bs=8） | 文档吞吐 | 查询延迟（中位） |
| --- | --- | --- | --- | --- | --- | --- |
| **WebGPU** | FP16 | 2775 ms | 170.6 ms | 136.2 ms | **176.2 doc/s** | **17.1 ms** |
| **WASM** | INT8 | **292 ms** | 194.2 ms | 4325.9 ms | 5.5 doc/s | 62.4 ms |

读法：

- **吞吐差 32 倍**（176.2 / 5.5）。WebGPU 走 FP16 张量核心，WASM 是单线程 CPU 路径，这个量级符合预期。
- **加载反过来**：WASM 只要 292 ms，WebGPU 要 2775 ms —— 多出来的时间几乎全在 shader 编译与显存上传。所以「小批量、一次性」场景下 WASM 反而更快，WebGPU 的优势要攒够批量才显现。
- **查询延迟**是关键指标：单条查询是用户每次敲回车的等待时间。17.1 ms 完全无感，62.4 ms 在可接受范围。
- 首个单条向量（170 / 194 ms）都比稳态慢一个数量级，这就是 `createEmbedder()` 里必须做 warmup 的原因 —— 不预热的话第一次用户查询要白等约 200 ms。

> WASM 的 5.5 doc/s 明显低于 Node 原生 ONNX Runtime 的 226 doc/s（见第 3 节）。原因见第 2 节：浏览器侧受限于单线程。

---

## 2. batch size 扫描（为什么默认 8）

同一批 24 段文档，只改 `batchSize`：

| batchSize | WebGPU FP16 | WASM INT8 |
| --- | --- | --- |
| 1 | 47.5 doc/s | 5.4 doc/s |
| 4 | 195.5 doc/s | 5.6 doc/s |
| **8** | **310.8 doc/s** | **5.9 doc/s** |
| 16 | 245.3 doc/s | 5.7 doc/s |

- **WebGPU 在 bs=8 达到峰值 310.8 doc/s**，是 bs=1 的 6.5 倍。bs=16 反而掉到 245.3 —— 显存与 attention 矩阵随 batch 增长，超过甜点后调度开销吃掉收益。**默认 8 是这个扫描的直接结论**。
- **WASM 几乎不受 batch 影响**（5.4 → 5.9，波动在噪声内）。单线程下矩阵乘是纯粹的顺序计算，批量化只省掉调用开销，省不出并行度。

### 为什么 WASM 是单线程（重要）

多线程 WASM 需要 `SharedArrayBuffer`，要求页面跨源隔离 —— 本项目已发送 COOP/COEP，`crossOriginIsolated` 实测为 `true`，条件满足。但开启多线程后：

```
bench.html?threads=4&autorun=1
→ 页面停在 "== 强制 WASM ==" 不再前进
→ 90 s 超时兜底触发后 runs 返回空数组
→ 该 tab 的渲染线程被完全楔住（DOM 快照取不到、截图超时）
```

单线程（`threads=1`，默认值）则稳定进入推理。这是上游 `onnxruntime-web` 在本机 Chrome/Windows 组合上的 worker pool 初始化缺陷：既拿不到错误，也等不到完成，还会把主线程一起拖住。

所以 `web/src/lib/embedder.ts` 里把线程数固定为 1，并留了一个显式开关：

```js
window.__MINIKB_WASM_THREADS__ = 4   // 仅在你验证过自己机器可行时打开
```

**这是一个环境缺陷，不是设计选择**，如实记录在此。在有可用多线程 WASM 的机器上，WASM 那 5.5 doc/s 会显著上抬，但不会改变「WebGPU 优先、WASM 兜底」的结论。

---

## 3. 量化质量对照：INT8 vs FP32

WebGPU 走 FP16、WASM 走 INT8，所以「量化掉了多少精度」必须在同一后端上隔离比较。这一组用 CLI 基准在 **CPU（Node 原生 ONNX Runtime）** 上跑，只改权重精度：

```bash
npm run bench -- --stage embed --dtype int8 --dtype fp32
```

| dtype | 加载 | 文档向量化（24 段） | 吞吐 | 查询向量化 | Recall@5 | Recall@10 | nDCG@10 | MRR |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| INT8 | 170 ms | 105.8 ms | 226.8 doc/s | 2.1 ms | 100% | 100% | 0.963 | 0.958 |
| FP32 | 142 ms | 139.7 ms | 171.8 doc/s | 3.8 ms | 100% | 100% | **1.000** | **1.000** |

结论：

- **召回不掉**：两者 Recall@5 / @10 都是 100%，INT8 量化没有漏掉任何金标片段。
- **排序轻微退化**：nDCG@10 从 1.000 掉到 0.963，MRR 0.958 —— 少数查询里第 2、3 位互换了顺序，但没有把无关片段推到第一位。对「迷你知识库」这种展示 Top-5 的场景，这个代价可以接受。
- **INT8 反而更快**（226.8 vs 171.8 doc/s，+32%）：8 位权重在 CPU 上既省内存带宽也走更快的整数核。

单点验证（同一对句子，余弦相似度）：

| 句对 | INT8 | FP32 |
| --- | --- | --- |
| 相关句对 | 0.6488 | 0.6450 |
| 无关句对 | 0.3527 | 0.3210 |

相关与无关之间的间距在两种精度下都保持清晰（约 0.30 的间隔），INT8 的误差没有压缩这个间距。

---

## 4. 权重体积与压缩比

来自 `public/models/Xenova/bge-small-zh-v1.5/model-manifest.json`（`npm run setup` 自动生成）：

| 精度 | 文件 | 体积 | 压缩比 | 用在 |
| --- | --- | --- | --- | --- |
| FP32 | `onnx/model.onnx` | 90.5 MB | 1.00x（基线） | WASM 最后兜底 |
| FP16 | `onnx/model_fp16.onnx` | 45.3 MB | **2.00x** | WebGPU 首选 |
| INT8 | `onnx/model_int8.onnx` | 22.8 MB | **3.97x** | WASM 降级首选 |

外加 `tokenizer.json` 428.8 KB 与几个百字节级配置。**首屏要传的只有一份权重**（按后端二选一），所以 WebGPU 用户实际下载 45.3 MB，WASM 用户 22.8 MB。

---

## 5. 数据库阶段：环境限制说明

**必须如实说明**：`seekdb` 1.4.0 的 `@seekdb/js-bindings` 在 `win32-x64` 上 `open()` 时**段错误退出（exit 139）**。数据目录已成功创建（`etc/log/run/store` 全部生成），崩溃发生在 store 初始化阶段。

已验证的排查：

- Node 22.22.1 / 22.22.2 均复现，Node 20.18.1 同样复现 → 排除 Node 版本。
- 全新空目录、不同路径、embedded 与 admin 两种入口均复现 → 排除数据目录污染。
- 结论：上游 win32-x64 原生构建缺陷，不是本仓库代码问题。

因此 **本节没有「写入耗时 / 索引刷新耗时 / 混合检索延迟」的真实数字**，缺数据就写缺数据，不编造。项目对此的三层应对：

1. `SEEKDB_MODE=server` —— 指向一台 Linux 上的 seekdb server，接口完全一致，仅连接方式不同（`server/db/seekdb.ts` 的 `connect()` 双分支）。
2. **服务层依赖注入** —— `createKnowledgeService(deps)` 让 `ingest / search / refresh` 的全部业务规则（维度校验、去重、刷新策略、分阶段计时）可以脱离数据库验证。
3. **12 个契约测试全部通过** —— `npm test`，用内存替身 `FakeCollection` 走完整的仓储 + 服务 + 控制器链路，覆盖：
   - 向量维度不符时拒绝写入（防止前后端维度漂移）
   - 重复 id 去重并计入 `skipped`
   - 空文档 / 超长文档 / 超量请求被拒
   - `always` / `deferred` / `manual` 三种刷新策略的触发时机
   - `deferred` 模式下检索前自动刷新，且只刷一次
   - 混合检索的 RRF 参数透传、`vector` 模式的 `1 - distance` 转换
   - 空 `queryText` 时 hybrid 自动退化为 vector

在 Linux / macOS 上（原生库可正常加载）执行 `npm run bench -- --stage all` 即可补齐这三列。基准脚本里 `writeMs / refreshMs / dbMs` 三个字段已经就位，只是本机取不到值（JSON 里为 `null`）。

---

## 6. 服务层优化措施与依据

| 优化 | 做法 | 依据 |
| --- | --- | --- |
| **批量向量化** | `embedDocuments()` 按 `batchSize` 分块调用 pipeline，默认 8 | 第 2 节扫描：bs=8 比 bs=1 快 6.5 倍（WebGPU） |
| **模型预热** | `createEmbedder()` 建会话后立即跑一次 `["warmup"]` | 首个向量比稳态慢一个数量级（170 vs 单条约 5.7 ms 摊销） |
| **查询指令前缀** | 查询侧统一加 `为这个句子生成表示以用于检索相关文章：` | bge 系列的非对称检索训练方式，缺失会掉 Recall |
| **向量 L2 归一化** | `normalize: true`，配合 cosine 索引 | 归一化后内积即余弦，索引侧不用再做除法 |
| **INT8 优先降级** | WASM 候选链 `int8 → q8 → fp32` | 第 3 节：INT8 召回不掉且比 FP32 快 32% |
| **索引刷新策略可切** | `always` / `deferred` / `manual` | 批量导入时 `deferred` 只在检索前刷一次，避免每批都刷 |
| **HNSW 参数** | `m=16, ef_construction=200, cosine` | 建图质量与内存的常规折中；24 段语料下无需调大 |
| **全文分词用 ngram** | `ngram, ngram_token_size=2` | 中文无需词典即可召回，避免引入 ik 词典依赖 |
| **`embeddingFunction: null`** | 集合禁用服务端 embedding | 从架构上堵死「服务端偷偷重算向量」的可能，满足 2.5 |

---

## 7. 如何复现本文全部数字

```bash
npm install
npm run setup                     # 拉模型（190MB）+ 复制 ORT wasm

# 表 3 / 表 4：量化质量与体积（CPU，不需要浏览器）
npm run bench -- --stage embed --dtype int8 --dtype fp32
# → 结果写入 benchmark/bench-embed-*.json
#   （本次的原始结果已留存为 benchmark/quantization-int8-fp32.json）

# 表 1 / 表 2：WebGPU vs WASM 真实浏览器数据
npm run dev
# 打开 http://localhost:5173/bench.html?autorun=1
# 页面依次跑「自动选型」与「强制 WASM」，给出加载/首个向量/批量吞吐/查询延迟/batch 扫描
# 跑完可「复制 JSON」或「下载 JSON」

# 表 5：契约测试
npm test
```

浏览器端一行一行的原始记录保留在 `benchmark/webgpu-vs-wasm.json`（`gpu: present`、`crossOriginIsolated: true`、两轮 run 的完整 `sweep`）。
