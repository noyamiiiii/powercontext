/**
 * Built-in demo corpus.
 *
 * Purpose: one click gives the app a real corpus so a reviewer can reproduce
 * the pipeline (import -> embed -> seekdb -> hybrid search) without hunting for
 * data. Each entry is one chunk with a stable id, which also makes the
 * Recall@K evaluation in the benchmark deterministic.
 *
 * Content is written from the project's own architecture notes plus the
 * documented seekdb / ONNX Runtime Web behaviour we actually rely on.
 */

export interface SampleDoc {
  id: string;
  title: string;
  text: string;
}

export const SAMPLE_DOCS: SampleDoc[] = [
  {
    id: "sample-seekdb-01",
    title: "seekdb 是什么",
    text: "seekdb 是面向 AI 应用的数据库，兼容 MySQL 协议，同时内置向量、全文与稀疏向量三类索引。它既可以作为独立 server 监听 2881 端口部署，也可以通过原生绑定以嵌入式方式运行在应用进程里。本项目使用嵌入式模式，数据库文件直接落在 data/seekdb 目录下，不需要额外安装任何守护进程。",
  },
  {
    id: "sample-seekdb-02",
    title: "嵌入式模式与原生绑定",
    text: "seekdb-js 的嵌入式模式依赖 @seekdb/js-bindings 预编译原生库，支持 linux-x64、linux-arm64、darwin-arm64 和 win32-x64 四个平台。首次调用时会从官方制品仓库下载约 90MB 的压缩包到 ~/.seekdb/bindings 缓存目录，之后直接加载 seekdb.node。如果处于代理网络环境，需要预先执行 npm run fetch:bindings，因为 Node 内置 fetch 不会读取 http_proxy 环境变量。",
  },
  {
    id: "sample-seekdb-03",
    title: "集合与向量索引",
    text: "在 seekdb-js 中，createCollection 接受一个 Schema，可以在同一个集合上同时声明 vectorIndex 与 fulltextIndex。向量索引使用 HNSW 图结构，需要指定维度与距离度量；本项目采用 cosine 余弦距离与 512 维向量。HNSW 的 m 参数控制每个节点的连边数量，ef_construction 决定建图时的候选队列长度，两者共同影响召回率与构建耗时。",
  },
  {
    id: "sample-seekdb-04",
    title: "全文索引与中文分词",
    text: "全文索引依赖分析器 analyzer。对中文而言，ik 分析器需要额外词典，而 ngram 分析器把文本切成固定长度的连续片段，不需要词典即可工作。本项目使用 ngram 分析器并把 ngram_token_size 设为 2，也就是二元组切分，这样「向量检索」会被切成「向量」「量检」「检索」三个片段，中英文混排的语料也能被关键词命中。",
  },
  {
    id: "sample-seekdb-05",
    title: "混合检索与 RRF 融合",
    text: "hybridSearch 是 seekdb 的核心能力：query.whereDocument 走全文索引，knn 走向量索引，rank.rrf 指定用 Reciprocal Rank Fusion 在数据库内部把两路排名融合成一个结果列表。RRF 的公式是每个文档得分为 1/(k+rank) 之和，k 就是 rankConstant，默认 60。关键点是融合发生在数据库里，应用层不需要分别取两路结果再自行拼装。",
  },
  {
    id: "sample-seekdb-06",
    title: "索引刷新",
    text: "向量索引是异步可见的。写入新文档后，必须调用 collection.refresh_index() 让新增内容对检索立即可见，否则查询可能拿不到刚导入的片段。本项目提供三种策略：always 表示每批写入后立刻刷新，deferred 表示把刷新推迟到下一次检索之前，manual 表示只能手动触发刷新接口。默认使用 always，以保证导入后立刻可搜。",
  },
  {
    id: "sample-embed-01",
    title: "浏览器端向量化",
    text: "端侧向量化指 embedding 推理完全在用户设备的浏览器里完成。模型文件由本地静态目录提供，推理通过 WebAssembly 或 WebGPU 执行，原文与向量都不经过任何远程推理服务。相比调用云端 embedding 接口，端侧方案的隐私性更好，没有按 token 计费的成本，也避免了网络往返带来的首字延迟；代价是需要一次性下载模型权重。",
  },
  {
    id: "sample-embed-02",
    title: "Transformers.js 与 ONNX Runtime Web",
    text: "Transformers.js 把 Hugging Face 的模型加载、分词与推理流程搬到浏览器，底层依赖 ONNX Runtime Web 执行 ONNX 计算图。调用 pipeline 时传入 device 与 dtype 两个参数，device 可选 wasm 或 webgpu，dtype 可选 fp32、fp16、int8、q8 等精度。分词器同样在浏览器中运行，tokenizer.json 由本地目录提供。",
  },
  {
    id: "sample-embed-03",
    title: "INT8 量化",
    text: "INT8 量化把模型权重从 32 位浮点压缩成 8 位整数，模型体积大约缩小到原来的四分之一。对 bge-small-zh-v1.5 来说，FP32 权重约 90.5MB，INT8 权重约 22.8MB，压缩比接近 4 倍。量化会带来轻微的精度损失，通常表现为向量方向的微小偏移，需要用 Recall@K 这类指标在固定评测集上量化，而不能只靠肉眼看结果。",
  },
  {
    id: "sample-embed-04",
    title: "FP16 量化",
    text: "FP16 量化把权重从 32 位浮点压缩成 16 位浮点，体积刚好减半，数值范围仍然保留浮点特性，因此精度损失通常小于 INT8。WebGPU 后端偏好 FP16：大多数消费级 GPU 对半精度有硬件加速，显存占用也更低。bge-small-zh-v1.5 的 FP16 权重约 45.3MB，相对 FP32 压缩 2.0 倍。",
  },
  {
    id: "sample-embed-05",
    title: "WebGPU 与 WASM 降级",
    text: "WebGPU 提供对 GPU 的通用计算访问，适合矩阵乘法密集的 Transformer 推理，但并非所有浏览器和显卡驱动都可用。正确做法是先用 navigator.gpu 请求 adapter，成功则用 webgpu 后端加载 FP16 权重；失败则自动降级到 wasm 后端加载 INT8 权重，并在界面上明确提示当前使用的推理后端与降级原因，而不是静默切换。",
  },
  {
    id: "sample-embed-06",
    title: "WASM 多线程与 SharedArrayBuffer",
    text: "ONNX Runtime Web 的 WASM 后端可以多线程执行，但需要 SharedArrayBuffer。浏览器只在跨源隔离（cross-origin isolated）的页面上开放这个能力，因此服务端必须发送 Cross-Origin-Opener-Policy: same-origin 与 Cross-Origin-Embedder-Policy: require-corp 两个响应头。缺少这两个头时，运行时不会报错，而是退化成单线程，性能明显下降。",
  },
  {
    id: "sample-embed-07",
    title: "批处理与吞吐",
    text: "端侧推理的固定开销有两部分：每次调用 ONNX session 的调度开销，以及 GPU 与 CPU 之间的数据搬运。把多个文本拼成一个 batch 一起前向计算，可以显著摊薄这两部分开销，提高每秒处理文档数。批大小并非越大越好：显存或内存受限时过大的 batch 会导致分配失败，本项目默认批大小为 8 并允许在界面上调节。",
  },
  {
    id: "sample-embed-08",
    title: "首次加载与预热",
    text: "模型加载与首次推理是两个不同的成本。加载包括读取权重、初始化 session，WebGPU 还要编译 shader；首次推理则包含算子图优化。因此性能报告必须区分冷启动与预热后的数字，否则把 shader 编译时间算进查询延迟会严重失真。本项目在加载完成后主动跑一次 warmup 推理，让后续计时只包含稳定状态下的耗时。",
  },
  {
    id: "sample-embed-09",
    title: "向量归一化与余弦相似度",
    text: "bge 系列模型输出的是语义向量，检索前通常做 L2 归一化，这样内积就等于余弦相似度。seekdb 在 cosine 距离模式下返回的是余弦距离，取值越小越相似，转换成相似度用 1 减去距离。如果向量本身已归一化，距离就落在 0 到 2 之间，便于设定阈值。",
  },
  {
    id: "sample-embed-10",
    title: "查询指令前缀",
    text: "bge-small-zh 这类非对称检索模型要求查询侧加指令前缀，例如「为这个句子生成表示以用于检索相关文章：」，而文档侧不加任何前缀。漏掉前缀会让查询向量与文档向量处在不同的分布上，召回率明显下降。是否添加前缀由模型决定，不是所有模型都需要。",
  },
  {
    id: "sample-rag-01",
    title: "端到端检索延迟的构成",
    text: "从用户敲下回车到结果渲染，延迟由几段组成：查询向量化、HTTP 往返、seekdb 混合检索、以及结果渲染。查询向量化通常是最大的一块，因为它是单条推理，无法像文档向量化那样靠批处理摊薄。数据库检索本身在毫秒级，量级远小于推理。做优化时应该先测清楚各段占比，再决定优化对象。",
  },
  {
    id: "sample-rag-02",
    title: "Recall@K 评测",
    text: "Recall@K 衡量的是：在被标注为相关的结果中，有多少出现在前 K 条返回里。评测集由若干条查询与它们对应的目标文档组成，逐条检索后统计命中比例。用 Recall@K 对比量化前后的变化，可以判断量化是否真的损害了检索质量；如果 Recall@10 只下降一两个百分点，通常认为量化是可接受的。",
  },
  {
    id: "sample-rag-03",
    title: "nDCG@K 与排序质量",
    text: "Recall 只关心有没有召回，不关心排序位置。nDCG 在 Recall 的基础上给靠前的命中更高权重，用折损累积收益衡量排序质量。当两套方案的 Recall 相同但用户体感不同时，差异往往体现在 nDCG 上。工程实践中常把 Recall@K 作为召回层的底线指标，把 nDCG 作为排序层指标。",
  },
  {
    id: "sample-rag-04",
    title: "增量导入与状态一致性",
    text: "知识库很少一次导完。增量导入要解决三个问题：新片段的 id 不能与已有片段冲突，写入后索引必须刷新才能被检索到，以及用户切换知识库时检索必须落在当前集合上。把每个知识库映射到一个独立集合，并在服务端维护集合缓存与待刷新标记，可以在连续导入和切换场景下保持结果一致。",
  },
  {
    id: "sample-rag-05",
    title: "数据不离开设备",
    text: "隐私敏感场景下，端侧向量化的价值在于原文不需要上传。用户导入的文档只在本机浏览器里被切成片段并编码成向量，上传到数据库的只有向量、片段文本与少量元数据，而且数据库本身也运行在本机进程内。这种部署形态适合个人知识库、内网文档助手等对数据外流敏感的场景。",
  },
  {
    id: "sample-rag-06",
    title: "为什么混合检索优于纯向量",
    text: "纯向量检索擅长语义泛化，但对精确的型号、错误码、专有名词往往乏力，因为这些词的表征在训练语料里罕见。关键词检索恰好相反：它对字面匹配极其可靠，却理解不了同义改写。混合检索引擎把两路召回融合，既保住语义能力，又补上精确匹配，因此在工程 RAG 系统里通常是默认选择。",
  },
  {
    id: "sample-rag-07",
    title: "浏览器兼容性",
    text: "应用需要在 Chrome 与 Edge 最新版上正常运行。WASM 后端在这些浏览器上都可用，多线程需要跨源隔离头。WebGPU 在较新的 Chrome 与 Edge 上默认开启，旧版本或部分集显驱动可能拿不到 adapter，此时必须能降级到 WASM 并继续完成检索流程，而不是白屏报错。",
  },
  {
    id: "sample-rag-08",
    title: "模型选择",
    text: "端侧场景倾向于参数量小、ONNX 导出成熟、对中文友好的模型。all-MiniLM-L6-v2 只有英文能力，体积约 90MB（FP32），适合英文语料；bge-small-zh-v1.5 是 24M 参数的中文检索模型，输出 512 维向量，在中文语义匹配上明显更强。两者都提供 FP32、FP16、INT8 等多种精度的 ONNX 权重。",
  },
];

/**
 * Fixed evaluation set for the quality benchmark.
 * `relevant` lists the chunk ids that answer the query.
 */
export interface EvalCase {
  query: string;
  relevant: string[];
}

export const EVAL_CASES: EvalCase[] = [
  { query: "seekdb 怎么在应用进程内嵌运行", relevant: ["sample-seekdb-02", "sample-seekdb-01"] },
  { query: "混合检索的 RRF 融合是在哪里完成的", relevant: ["sample-seekdb-05"] },
  { query: "中文全文索引应该选什么分析器", relevant: ["sample-seekdb-04"] },
  { query: "写入后为什么查不到新文档", relevant: ["sample-seekdb-06", "sample-rag-04"] },
  { query: "INT8 量化后模型体积能压缩到多少", relevant: ["sample-embed-03"] },
  { query: "WebGPU 不可用时如何降级", relevant: ["sample-embed-05", "sample-rag-07"] },
  { query: "为什么 WASM 多线程需要 SharedArrayBuffer", relevant: ["sample-embed-06"] },
  { query: "冷启动时间和预热后的延迟为什么要分开算", relevant: ["sample-embed-08"] },
  { query: "如何用 Recall@K 判断量化是否损害质量", relevant: ["sample-rag-02"] },
  { query: "纯向量检索对错误码这类精确匹配效果差", relevant: ["sample-rag-06"] },
  { query: "batch size 对端侧推理吞吐的影响", relevant: ["sample-embed-07"] },
  { query: "bge 模型查询为什么要加指令前缀", relevant: ["sample-embed-10"] },
];
