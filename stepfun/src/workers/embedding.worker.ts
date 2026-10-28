import { env, pipeline, type FeatureExtractionPipeline } from "@huggingface/transformers";

import type {
  EmbeddingBackend,
  EmbeddingLoadResult,
  EmbeddingProgress,
} from "../types";

const MODEL_ID = "onnx-community/bge-small-zh-v1.5-ONNX";
const QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章：";

env.allowLocalModels = false;
env.useBrowserCache = true;

let extractor: FeatureExtractionPipeline | null = null;
let backend: EmbeddingBackend | null = null;

interface WorkerRequest {
  id: number;
  operation: "load" | "embed-documents" | "embed-query" | "backend";
  texts?: string[];
  batchSize?: number;
  query?: string;
}

self.addEventListener("message", (event: MessageEvent<WorkerRequest>) => {
  void handleRequest(event.data);
});

async function handleRequest(request: WorkerRequest): Promise<void> {
  try {
    switch (request.operation) {
      case "load":
        postResult(request.id, await loadEmbedding(request.id));
        break;
      case "embed-documents":
        postResult(
          request.id,
          await embedDocuments(request.id, request.texts ?? [], request.batchSize ?? 8),
        );
        break;
      case "embed-query":
        {
          const startedAt = performance.now();
          const embeddings = await embed([
            `${QUERY_INSTRUCTION}${request.query ?? ""}`,
          ]);
          postResult(request.id, {
            embeddings,
            embeddingMs: performance.now() - startedAt,
          });
        }
        break;
      case "backend":
        postResult(request.id, backend);
        break;
    }
  } catch (error) {
    self.postMessage({
      id: request.id,
      type: "error",
      error: error instanceof Error ? error.message : "端侧推理失败",
    });
  }
}

async function loadEmbedding(id: number): Promise<EmbeddingLoadResult> {
  if (extractor && backend) {
    return { backend, loadMs: 0 };
  }
  const startedAt = performance.now();
  const supportsWebGPU =
    "gpu" in navigator &&
    Boolean(await navigator.gpu?.requestAdapter().catch(() => null));

  if (supportsWebGPU) {
    try {
      extractor = await createPipeline(id, "webgpu", "fp16");
      backend = {
        device: "webgpu",
        dtype: "fp16",
        modelId: MODEL_ID,
        dimension: 512,
      };
      return { backend, loadMs: performance.now() - startedAt };
    } catch (error) {
      console.warn("WebGPU/FP16 failed, falling back to WASM/INT8", error);
    }
  }

  extractor = await createPipeline(id, "wasm", "q8");
  backend = {
    device: "wasm",
    dtype: "q8",
    modelId: MODEL_ID,
    dimension: 512,
    fallbackReason: supportsWebGPU
      ? "WebGPU 初始化失败，已回退到 WASM"
      : "浏览器未提供可用的 WebGPU",
  };
  return { backend, loadMs: performance.now() - startedAt };
}

async function createPipeline(
  id: number,
  device: "webgpu" | "wasm",
  dtype: "fp16" | "q8",
): Promise<FeatureExtractionPipeline> {
  return pipeline("feature-extraction", MODEL_ID, {
    device,
    dtype,
    progress_callback: (progress) => {
      if (progress.status === "progress") {
        postProgress(id, {
          operation: "load",
          progress: progress.progress,
          message: `${progress.file ?? "模型"} ${Math.round(progress.progress)}%`,
        });
      } else {
        postProgress(id, {
          operation: "load",
          progress: 0,
          message: progress.status,
        });
      }
    },
  });
}

async function embedDocuments(
  id: number,
  texts: string[],
  batchSize: number,
): Promise<{ embeddings: number[][]; embeddingMs: number }> {
  const startedAt = performance.now();
  const embeddings: number[][] = [];
  const batchCount = Math.ceil(texts.length / batchSize);
  for (let index = 0; index < texts.length; index += batchSize) {
    const batch = texts.slice(index, index + batchSize);
    embeddings.push(...(await embed(batch)));
    self.postMessage({
      id,
      type: "progress",
      progress: {
        operation: "documents",
        progress: Math.round(((index + batch.length) / texts.length) * 100),
        message: `已完成 ${index + batch.length}/${texts.length} 个文本块`,
      } satisfies EmbeddingProgress,
    });
  }
  return {
    embeddings,
    embeddingMs: performance.now() - startedAt,
  };
}

async function embed(texts: string[]): Promise<number[][]> {
  if (!extractor) {
    throw new Error("Embedding 模型尚未加载");
  }
  const output = await extractor(texts, {
    pooling: "cls",
    normalize: true,
  });
  return output.tolist() as number[][];
}

function postResult(id: number, result: unknown): void {
  self.postMessage({ id, type: "result", result });
}

function postProgress(id: number, progress: EmbeddingProgress): void {
  self.postMessage({
    id,
    type: "progress",
    progress,
  });
}
