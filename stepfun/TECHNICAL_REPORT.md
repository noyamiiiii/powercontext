# Edge Course Lens 技术说明

## 作品

Edge Course Lens 是一个浏览器端课程知识库。用户导入文本后，浏览器 Worker 使用开源 embedding 模型生成本地向量，Node 服务只把向量、原文和元数据写入 seekdb。查询时同样在浏览器生成向量，再由 seekdb 一次完成全文、向量与 RRF 融合。

## 模型与量化

- 模型：`onnx-community/bge-small-zh-v1.5-ONNX`
- 上游模型：`BAAI/bge-small-zh-v1.5`
- 修订：`9507db33464b5da99a532ac26b2a251767cbc62b`
- 语言：中文
- 向量维度：512
- 最大序列长度：512
- 池化：CLS
- 归一化：L2
- 查询指令：`为这个句子生成表示以用于检索相关文章：`

来源：

- https://huggingface.co/BAAI/bge-small-zh-v1.5
- https://huggingface.co/onnx-community/bge-small-zh-v1.5-ONNX

| 精度 | 模型权重体积 | 相对 FP32 压缩比 |
| --- | ---: | ---: |
| FP32 | 94,806,745 B | 1.00× |
| FP16 | 47,424,911 B | 2.00× |
| INT8/q8 | 23,942,210 B | 3.96× |

固定评测集包含 12 个课程段落和 6 个中文查询。FP32 与 INT8 的 Recall@3 均为 `1.00`，MRR 均为 `1.00`；INT8 没有在这个小型测试集上造成可观察的排序损失。完整原始结果见 `benchmarks/model-quality.json`，可用 `npm run benchmark:models` 复现。

## 端侧运行

Transformers.js 4.3.2 在独立 Web Worker 中加载模型：

1. 使用 `navigator.gpu.requestAdapter()` 检测 WebGPU。
2. WebGPU 可用时加载 `dtype: "fp16"`。
3. WebGPU 不可用或初始化失败时，自动加载 `dtype: "q8"` 并通过 WASM 推理。
4. 页面持续显示当前 `device`、精度、模型权重体积和加载进度。

官方依据：

- https://huggingface.co/docs/transformers.js/en/guides/webgpu
- https://huggingface.co/docs/transformers.js/en/guides/dtypes

当前 Windows 无头 Chrome 不支持 WebGPU，实测自动进入 WASM/INT8：

| 阶段 | 实测 |
| --- | ---: |
| 首次模型加载（2 次中位数） | 8.93 s |
| 缓存后模型加载（2 次中位数） | 188 ms |
| 3 个文本块向量化 | 32.7 ms |
| 1 个查询向量化 | 23 ms |

两次原始加载值和样本见 `benchmarks/runtime-browser.json`。应用会把实际 WebGPU 或 WASM 后端、首次/后续请求耗时、批大小和 seekdb 延迟显示在右侧“运行指标”中，并可导出 JSON。

本次 WASM 自动降级和运行时指标截图见 `screenshots/app-wasm-runtime.png`，390px 手机视口见 `screenshots/app-wasm-mobile.png`。

## seekdb

seekdb-js 1.4.0 使用官方 Docker server 模式。每个知识库对应一个独立 collection：

- 全文索引：`FulltextIndexConfig("ik", { ik_mode: "smart" })`
- 向量索引：HNSW，512 维，余弦距离
- 向量生成：`embeddingFunction: null`，只接收浏览器已经生成的向量
- 写入方式：`upsert`
- 刷新方式：`collection.refresh_index()`
- 混合检索：`collection.hybridSearch({ query, knn, rank: { rrf: {} } })`

向量与全文排名在 seekdb 内部通过 `DBMS_HYBRID_SEARCH` 和 RRF 融合，前端不会分别请求两路结果再自行拼接。新导入的内容只有在 `refresh_index()` 完成后才展示为可检索。

官方依据：

- https://github.com/oceanbase/seekdb-js
- https://www.oceanbase.ai/docs/deploy-by-docker
- https://www.oceanbase.ai/docs/seekdb-js-get-started

## 状态与优化

- 知识库目录保存在应用数据目录，collection 与文本块数量由 seekdb 提供。
- 重复导入使用稳定文档 ID 的 upsert，实现增量更新。
- 长文本按 1,200 字符上限切块，保存来源、块编号和导入时间。
- 批大小可选 1、4、8、16，界面显示逐批进度。
- embedding 在 Worker 内执行，避免阻塞主线程。
- 模型使用浏览器缓存；缓存后加载明显快于首次加载。
- 混合检索先取候选集，再由 seekdb RRF 返回最终 Top K，减少传输和展示规模。
- 页面自动记录模型加载、文档向量化、索引刷新、查询向量化、数据库检索和端到端查询耗时。

## 限制

- 当前部署环境没有运行 Docker engine，因此本次自动记录只包含浏览器端实测；seekdb 延迟需要在执行 `npm run db:start` 后由界面记录。
- WebGPU 性能依赖显卡、驱动和浏览器；不同设备需要分别测试，不能把当前 WASM 数据当作 WebGPU 性能。
- 小型质量集用于回归排序变化，不等同于完整 C-MTEB 或业务评测。
