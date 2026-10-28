import { pipeline, type FeatureExtractionPipeline } from "@huggingface/transformers";

const MODEL_ID = "onnx-community/bge-small-zh-v1.5-ONNX";
const QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章：";

const documents = [
  ["webgpu", "浏览器支持 WebGPU 时优先使用 GPU 执行端侧模型推理。"],
  ["wasm", "WebGPU 不可用或初始化失败时，启用 ONNX Runtime Web 的 WASM 后端。"],
  ["int8", "INT8 量化把模型权重压缩到八位，降低下载体积但可能轻微改变排序。"],
  ["refresh", "写入新文档后调用 refresh_index，让异步向量索引完成刷新。"],
  ["rrf", "RRF 把全文检索排名和向量检索排名融合成一个最终结果列表。"],
  ["hnsw", "HNSW 是用于高效近似最近邻搜索的向量索引。"],
  ["cosine", "余弦距离适合比较经过 L2 归一化的文本向量。"],
  ["bge", "BGE 中文模型使用 CLS token 作为句子表示，并对向量做归一化。"],
  ["chunk", "长文档应切分为有界文本块，并保存来源和块编号元数据。"],
  ["incremental", "增量导入使用 upsert，避免每次删除并重建整个知识库。"],
  ["privacy", "端侧 embedding 让原始文本和查询向量不必发送到远程推理 API。"],
  ["fulltext", "全文检索擅长精确关键词，向量检索擅长语义相近但措辞不同的内容。"],
] as const;

const queries = [
  ["浏览器没有 GPU 支持时使用什么后端", "wasm"],
  ["怎样让刚写入的文档马上可搜索", "refresh"],
  ["如何把关键词排名和语义排名合并", "rrf"],
  ["模型体积怎样从 FP32 降低", "int8"],
  ["句子向量怎样做池化和归一化", "bge"],
  ["如何提高近似向量搜索速度", "hnsw"],
] as const;

interface BenchmarkResult {
  dtype: "fp32" | "q8";
  loadMs: number;
  embeddingMs: number;
  recallAt3: number;
  mrr: number;
  rankings: Record<string, string[]>;
}

function cosine(left: number[], right: number[]): number {
  return left.reduce((sum, value, index) => sum + value * right[index], 0);
}

async function run(dtype: "fp32" | "q8"): Promise<BenchmarkResult> {
  const loadStarted = performance.now();
  const extractor: FeatureExtractionPipeline = await pipeline(
    "feature-extraction",
    MODEL_ID,
    { dtype, device: "cpu" },
  );
  const loadMs = performance.now() - loadStarted;
  const embedStarted = performance.now();
  const documentOutput = await extractor(
    documents.map(([, text]) => text),
    { pooling: "cls", normalize: true },
  );
  const documentVectors = documentOutput.tolist() as number[][];
  let hitsAt3 = 0;
  let reciprocalRankSum = 0;
  const rankings: Record<string, string[]> = {};

  for (const [query, expectedId] of queries) {
    const queryOutput = await extractor([`${QUERY_INSTRUCTION}${query}`], {
      pooling: "cls",
      normalize: true,
    });
    const queryVector = (queryOutput.tolist() as number[][])[0];
    const ranked = documents
      .map(([id], index) => ({
        id,
        score: cosine(queryVector, documentVectors[index]),
      }))
      .sort((left, right) => right.score - left.score)
      .map((item) => item.id);
    rankings[query] = ranked.slice(0, 3);
    const rank = ranked.indexOf(expectedId);
    if (rank >= 0 && rank < 3) {
      hitsAt3 += 1;
    }
    reciprocalRankSum += rank >= 0 ? 1 / (rank + 1) : 0;
  }

  return {
    dtype,
    loadMs,
    embeddingMs: performance.now() - embedStarted,
    recallAt3: hitsAt3 / queries.length,
    mrr: reciprocalRankSum / queries.length,
    rankings,
  };
}

const results = [];
for (const dtype of ["fp32", "q8"] as const) {
  results.push(await run(dtype));
}

console.log(
  JSON.stringify(
    {
      modelId: MODEL_ID,
      language: "zh",
      documentCount: documents.length,
      queryCount: queries.length,
      results,
      weightBytes: {
        fp32: 94_806_745,
        q8: 23_942_210,
        fp16: 47_424_911,
      },
      compressionRatio: {
        fp16: 94_806_745 / 47_424_911,
        q8: 94_806_745 / 23_942_210,
      },
    },
    null,
    2,
  ),
);
