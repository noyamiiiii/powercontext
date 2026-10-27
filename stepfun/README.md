# 端侧向量化 × seekdb 混合检索 · 迷你知识库

> 2026 OceanBase 数据库大赛 · **seekdb × 阶跃星辰** 赛题参赛作品
>
> 题目：端侧 AI 推理性能优化与 seekdb 混合检索

一个在浏览器里完成全部 embedding 推理、把向量与原文写入 seekdb、由 seekdb 内部完成「向量 + 全文」混合检索（RRF 融合）的迷你知识库 Web 应用。

**没有任何云端推理调用**：模型权重由本地静态目录提供，向量化跑在用户设备的 GPU（WebGPU）或 CPU（WASM）上，原文不出设备。

---

## 快速开始

环境要求：Node.js >= 20.11（推荐 22），Chrome / Edge 最新版。

```bash
cd stepfun

# 1) 安装依赖
#    .npmrc 已设置 legacy-peer-deps=true：seekdb 的 peerDependencies 里带有
#    `workspace:*`（上游发布包缺陷），不关掉 peer 自动安装会直接 EUNSUPPORTEDPROTOCOL。
npm install

# 2) 准备运行时资源（一次性，约 190MB）
#    - 下载 ONNX 模型权重（fp32 / fp16 / int8）到 public/models/
#    - 复制 ONNX Runtime Web 的 wasm 到 public/ort/
npm run setup

# 3) 启动（后端 :8787 + 前端 :5173 一起起）
npm run dev
```

打开 http://localhost:5173 ，页面会自动加载模型并在右上角显示当前推理后端。

> 如果在内网/代理环境，且 `npm run setup` 之外的 seekdb 原生库下载失败，
> 先执行 `npm run fetch:bindings`（用 curl 下载，支持代理与断点续传）。

### 生产模式（单进程、同源、无 CORS）

```bash
npm run build     # 类型检查 + 打包前端到 dist/web
npm start         # Express 同时提供 API 与静态前端，访问 http://127.0.0.1:8787
```

### 一键跑基准（CLI，可复现）

```bash
npm run bench -- --dtype int8 --dtype fp32
```

输出各阶段耗时与 Recall@K / nDCG@10 / MRR 对照表，并把原始数据写到 `benchmark/*.json`。

### 浏览器端推理基准（WebGPU vs WASM）

```bash
npm run dev
# 打开 http://localhost:5173/bench.html?autorun=1
```

这个页面**不连数据库**，只测推理本身：加载开销、首个向量、24 段批量吞吐、12 条查询延迟中位数，
以及 batch size 1/4/8/16 的扫描。跑完可以「复制 JSON」或「下载 JSON」（带上你的 UA 与核数，便于比对）。
`BENCHMARK.md` 的表 1 / 表 2 就是从这个页面出来的。

> 页面上的「检索质量与性能评测」面板测的是**完整链路**（查询向量化 → seekdb 混合检索），
> 需要数据库可用；`bench.html` 只测推理，因此在任何平台上都能跑。

---

## 赛题要求 → 实现对照

| 赛题要求 | 实现位置 |
| --- | --- |
| 2.1 导入文本 → 本地向量化 → 写入 seekdb → 检索排序展示 | `web/src/components/ImportPanel.tsx`、`web/src/components/SearchPanel.tsx` |
| 2.2.1 端侧运行时（Transformers.js / ONNX Runtime Web） | `web/src/lib/embedder.ts`（`@huggingface/transformers` + `onnxruntime-web`） |
| 2.2.2 开源模型，注明来源与版本 | `Xenova/bge-small-zh-v1.5`（24M 参数，512 维，MIT），权重落在 `public/models/`，版本清单见 `model-manifest.json` |
| 2.2.3 INT8 / FP16 量化 | WASM 用 `int8` 权重，WebGPU 用 `fp16` 权重；体积与压缩比见 `TECHNICAL.md`，质量变化用 Recall@K 实测 |
| 2.2.4 WebGPU 优先 + 自动降级 WASM + 界面提示 | `createEmbedder()` 的候选链 `webgpu/fp16 → wasm/int8 → wasm/q8 → wasm/fp32`；`StatusBar` 显示后端与降级原因 |
| 2.3.1 seekdb-js 接入，存向量/原文/元数据 | `server/db/seekdb.ts`、`server/repositories/knowledgeRepo.ts` |
| 2.3.2 向量 + 全文混合检索，由 seekdb 完成 | `collection.hybridSearch({ query.whereDocument, knn, rank.rrf })`，RRF 在库内融合 |
| 2.3.3 写入与索引刷新 | `refresh_index()`；三种刷新策略 `always / deferred / manual` |
| 2.3.4 增量写入 / 集合与会话状态 | 每个知识库一个集合（`kb_<slug>`），集合缓存 + 待刷新标记，切换知识库即切换集合 |
| 2.4 基础性能优化 + 实测 | batch 可调（默认 8）、模型预热、索引刷新策略、HNSW 参数；分阶段计时见页面指标卡与 `BENCHMARK.md` |
| 2.5 禁止云端推理 / 禁止预计算回放 | `env.allowRemoteModels = false`，向量只由浏览器产生，服务端集合 `embeddingFunction: null` |
| 4.1 可运行应用 + 启动说明 | 本文件 |
| 4.2 源码 + 模型获取与量化步骤 + 表结构与索引配置 | 本文件 + `TECHNICAL.md` |
| 4.3 一页技术说明 | `TECHNICAL.md` |

---

## 架构

```
┌──────────────────────────── 浏览器（用户设备） ────────────────────────────┐
│                                                                            │
│  文本 / 文件 ──切片──► Transformers.js ──► ONNX Runtime Web                │
│                        (WebGPU FP16)  │  (WASM INT8，自动降级)             │
│                                      ▼                                     │
│                              512 维归一化向量（本地产生，不离开设备）        │
│                                      │                                     │
│  查询词 ──加指令前缀──► 同一 pipeline ──► 查询向量                          │
│                                      │                                     │
└──────────────────────────────────────┼─────────────────────────────────────┘
                                       │ HTTP (JSON)
┌──────────────────────────────────────▼─────────────────────────────────────┐
│                        Node 服务（分层：控制器 → 服务 → 仓储）              │
│                                                                            │
│   POST /api/kbs/:kb/documents   ──►  ingest()  ──► seekdb collection.add()  │
│   POST /api/kbs/:kb/search      ──►  search()  ──► collection.hybridSearch()│
│   POST /api/kbs/:kb/refresh     ──►  refresh() ──► collection.refresh_index()│
│                                                                            │
│   seekdb（嵌入式，进程内）                                                  │
│     ├── HNSW 稠密向量索引（cosine, dim=512, m=16, ef_construction=200）     │
│     └── 全文索引（ngram, token_size=2，中英文混排可用）                     │
│     hybridSearch = 全文召回 ⊕ 向量召回 → RRF 融合（在库内完成）             │
└────────────────────────────────────────────────────────────────────────────┘
```

**为什么向量化放在浏览器、数据库放在本地进程？**
赛题要求推理必须发生在用户设备。数据库则允许「嵌入式或本地 server」。这里选择嵌入式 seekdb，是因为它能把数据库本身也留在同一台机器上，形成完整的本地方案：原文与向量都不出设备，同时仍然可以演示完整的数据库混合检索能力。

---

## 目录结构

```
stepfun/
├── server/                     # 后端（Express + seekdb 嵌入式）
│   ├── config.ts               # 环境变量集中校验，启动即失败
│   ├── logger.ts               # 结构化 JSON 日志，带 requestId
│   ├── errors.ts               # 类型化错误 + 全局错误处理
│   ├── db/seekdb.ts            # 连接、集合 Schema（向量 + 全文索引）
│   ├── repositories/           # 唯一接触 seekdb SDK 的层
│   ├── services/               # 业务规则、刷新策略、分阶段计时
│   ├── controllers/            # HTTP 解析与校验（zod）
│   └── index.ts                # 启动、CORS、健康检查、优雅停机
├── web/                        # 前端（Vite + React + TS）
│   ├── index.html              # 应用入口
│   ├── bench.html              # 推理基准页（不依赖数据库，产出 BENCHMARK.md 的表 1/2）
│   └── src/
│       ├── lib/embedder.ts     # 端侧推理：后端探测、降级链、批量向量化
│       ├── lib/chunk.ts        # 文本切片
│       ├── api/client.ts       # 类型化 API 客户端（4xx 不重试 / 5xx 重试 3 次）
│       └── components/         # 状态栏、导入、检索、评测面板
├── shared/sampleCorpus.ts      # 示例语料 + 固定评测集（前后端与 bench 共用）
├── scripts/
│   ├── fetch-model.mjs         # 下载 ONNX 权重（可指定 dtype / 镜像源）
│   ├── fetch-bindings.mjs      # 预取 seekdb 原生库（代理友好、断点续传）
│   ├── prepare-runtime.mjs     # 复制 ORT wasm 到 public/ort
│   └── bench-hybrid.ts         # 可复现基准（质量 + 分阶段延迟）
├── TECHNICAL.md                # 一页技术说明
├── BENCHMARK.md                # 实测数据与测试方法
└── README.md
```

---

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 进程存活 |
| GET | `/api/ready` | 数据库就绪（含默认集合状态） |
| GET | `/api/meta` | 前端所需配置（模型、维度、指令前缀、刷新策略） |
| GET | `/api/kbs` | 知识库列表与片段数 |
| POST | `/api/kbs` | 新建知识库 → 新集合 |
| GET | `/api/kbs/:kb/stats` | 集合名、维度、距离、片段数 |
| POST | `/api/kbs/:kb/reset` | 清空（删集合重建） |
| GET | `/api/kbs/:kb/documents?limit=` | 预览片段 |
| POST | `/api/kbs/:kb/documents` | 批量写入 `{documents:[{id,text,embedding,metadata}], mode}` |
| POST | `/api/kbs/:kb/search` | `{queryEmbedding, queryText, topK, mode: hybrid\|vector\|fulltext}` |
| POST | `/api/kbs/:kb/refresh` | 手动刷新索引 |

错误统一返回 `{ error: { code, message, requestId, details? } }`，`requestId` 与日志中的字段一致，便于定位。

---

## 关键配置

见 `.env.example`。常用项：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `EMBEDDING_MODEL` | `Xenova/bge-small-zh-v1.5` | 换成 `Xenova/all-MiniLM-L6-v2` 需同时把 `EMBEDDING_DIM` 改 384、池化改 `mean` |
| `EMBEDDING_DIM` | `512` | 必须与模型输出一致，服务端强校验 |
| `QUERY_INSTRUCTION` | `为这个句子生成表示以用于检索相关文章：` | bge 系列非对称检索的查询前缀 |
| `FULLTEXT_ANALYZER` | `ngram` | `ngram` 对中文无需词典；`ik` 需额外词典 |
| `REFRESH_MODE` | `always` | `always` 写入即刷新；`deferred` 检索前刷新；`manual` 只手动刷新 |
| `SEEKDB_PATH` | `./data/seekdb` | 嵌入式数据库目录 |

---

## 常见问题

**1. `npm install` 报 `EUNSUPPORTEDPROTOCOL workspace:*`**
seekdb 1.4.0 的 `@seekdb/default-embed` peer 依赖声明成了 `workspace:*`。仓库自带 `.npmrc`（`legacy-peer-deps=true`）已规避；若要手动安装：`npm install --legacy-peer-deps`。

**2. 首次查询报 `fetch failed`**
嵌入式 seekdb 首次使用会从 S3 下载约 90MB 原生库，而 Node 内置 `fetch` 不读取 `http_proxy`。执行 `npm run fetch:bindings`（走 curl，支持代理与断点续传）即可。

**3. 页面上没有 WebGPU，只有 WASM**
说明 `navigator.gpu.requestAdapter()` 没拿到 adapter（无独显 / 驱动较旧 / 浏览器未启用）。这是设计内的降级路径，界面会显示降级原因，检索流程不受影响。可用状态栏的「试 WebGPU / 强制 WASM」按钮手动验证两条路径。

**4. WASM 后端显示单线程**
这是默认值，也是本机验证过的唯一稳定值。多线程 WASM 需要 `SharedArrayBuffer`，要求页面跨源隔离 —— 开发服务器与生产服务器都已发送 `Cross-Origin-Opener-Policy` / `Cross-Origin-Embedder-Policy`，实测 `crossOriginIsolated === true`，前提是满足的。但把线程数开到 4 之后，`onnxruntime-web` 的 worker pool 在本机 Chrome/Windows 上会永久挂起：拿不到错误、等不到完成，连渲染线程都会被拖住。

所以默认固定 1 线程。如果你的机器验证可行，用 `window.__MINIKB_WASM_THREADS__ = 4` 打开（或在基准页加 `?threads=4`）。详见 `BENCHMARK.md` 第 2 节。

**5. 模型下载慢**
`HF_ENDPOINT=https://hf-mirror.com npm run fetch:model`。

**6. Windows 上启动后进程直接退出（exit 139 / 段错误）**
`seekdb@1.4.0` 依赖的原生库 `@seekdb/js-bindings` 在 **win32-x64** 上初始化 store 时段错误退出。已排查：Node 20 与 22 均复现、全新空目录亦复现、数据目录已正常创建后才崩溃 —— 因此判定为上游原生构建的缺陷，不是本仓库代码问题。

三条应对路径：

1. **换平台**（推荐）：Linux / macOS 上嵌入式模式可直接使用，`npm run bench -- --stage all` 也能补齐数据库阶段耗时。
2. **连 server**：把 `SEEKDB_MODE=server`，指向任意 seekdb / OceanBase 实例（`SEEKDB_HOST` / `SEEKDB_PORT` / `SEEKDB_USER` / `SEEKDB_PASSWORD` / 可选 `SEEKDB_TENANT`）。接口完全一致，只有连接方式不同。
3. **只验业务规则**：`npm test` 的 12 个契约测试用内存替身覆盖了维度校验、去重、三种刷新策略、RRF 参数透传等全部服务层规则，不需要数据库。

`BENCHMARK.md` 第 5 节如实标注了因此缺失的三列耗时，没有估算填充。
