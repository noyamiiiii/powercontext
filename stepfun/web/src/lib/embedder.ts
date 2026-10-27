/**
 * Browser-side embedding.
 *
 * Everything in this file runs in the user's browser: the ONNX weights are
 * served from `/models/...` (downloaded once by `npm run setup`), and inference
 * happens on the local GPU or CPU. No text ever leaves the device.
 *
 * Backend policy (requirement 2.2.4):
 *   1. WebGPU available  -> fp16 weights on `device: "webgpu"`
 *   2. otherwise         -> int8 weights on `device: "wasm"` (auto-degrades to
 *                           q8 / fp32 if the 8-bit graph fails to load)
 * The chosen backend is reported to the UI, which shows it explicitly.
 */
import { env, pipeline, type FeatureExtractionPipeline } from "@huggingface/transformers";

export type Device = "webgpu" | "wasm";
export type Dtype = "fp16" | "int8" | "q8" | "fp32";

export interface BackendInfo {
  device: Device;
  dtype: Dtype;
  label: string;
  /** True when the user (or a failed WebGPU init) forced the CPU path. */
  degraded: boolean;
  reason?: string;
  /** Pipeline construction time (weight load + session init + warmup). */
  loadMs?: number;
}

export interface EmbedProgress {
  stage: "loading" | "embedding" | "warmup";
  file?: string;
  progress?: number;
  message?: string;
}

export interface Embedder {
  readonly backend: BackendInfo;
  readonly modelId: string;
  readonly dim: number;
  readonly loadMs: number;
  readonly wasmThreads: number;
  embedDocuments(
    texts: string[],
    batchSize: number,
    onProgress?: (done: number, total: number) => void,
  ): Promise<{ vectors: number[][]; ms: number }>;
  embedQuery(text: string): Promise<{ vector: number[]; ms: number }>;
  dispose(): Promise<void>;
}

const MODEL_ROOT = "/models/";
const ORT_ROOT = "/ort/";

env.allowLocalModels = true;
// No remote fallback: a judging run must work with the network unplugged.
env.allowRemoteModels = false;
env.localModelPath = MODEL_ROOT;
env.useBrowserCache = true;

/** `env.backends.onnx.wasm` is typed as optional; it always exists in the browser build. */
const ortWasm = env.backends.onnx?.wasm;
if (ortWasm) ortWasm.wasmPaths = ORT_ROOT;

/**
 * WASM thread count.
 *
 * Multi-threaded WASM needs SharedArrayBuffer (cross-origin isolated page) *and*
 * a worker pool that onnxruntime-web can spawn. In practice that pool fails to
 * come up on some Chrome/Windows combinations and the session then hangs forever
 * with no error -- so the safe default is a single thread, which always works.
 *
 * Opt in when you have verified it works on your machine:
 *   window.__MINIKB_WASM_THREADS__ = 4   // before the app loads, or via devtools
 */
const requestedThreads = (globalThis as { __MINIKB_WASM_THREADS__?: number }).__MINIKB_WASM_THREADS__;
const WASM_THREADS = Math.max(
  1,
  Math.min(8, Math.floor(requestedThreads ?? 1) || 1),
);
// SharedArrayBuffer is only available on a cross-origin isolated page; ORT
// silently falls back to 1 thread otherwise, so this is a hint, not a hard bet.
if (ortWasm) ortWasm.numThreads = WASM_THREADS;

const LABELS: Record<string, string> = {
  "webgpu/fp16": "WebGPU · FP16",
  "wasm/int8": "WASM · INT8",
  "wasm/q8": "WASM · 8-bit",
  "wasm/fp32": "WASM · FP32",
};

export async function detectWebGpu(): Promise<{ available: boolean; reason?: string }> {
  const gpu = (navigator as Navigator & { gpu?: { requestAdapter(): Promise<unknown> } }).gpu;
  if (!gpu) return { available: false, reason: "navigator.gpu 不可用" };
  try {
    const adapter = await gpu.requestAdapter();
    if (!adapter) return { available: false, reason: "未获取到 GPU adapter" };
    return { available: true };
  } catch (err) {
    return { available: false, reason: err instanceof Error ? err.message : "GPU 初始化失败" };
  }
}

interface Candidate {
  device: Device;
  dtype: Dtype;
}

function candidateChain(webgpuOk: boolean, force?: Device): Candidate[] {
  const wasm: Candidate[] = [
    { device: "wasm", dtype: "int8" },
    { device: "wasm", dtype: "q8" },
    { device: "wasm", dtype: "fp32" },
  ];
  if (force === "wasm") return wasm;
  if (force === "webgpu") return [{ device: "webgpu", dtype: "fp16" }, ...wasm];
  return webgpuOk ? [{ device: "webgpu", dtype: "fp16" }, ...wasm] : wasm;
}

function toVectors(output: { tolist(): unknown; dims?: number[] }): number[][] {
  const list = output.tolist() as number[] | number[][];
  if (!Array.isArray(list) || list.length === 0) return [];
  // Single-input calls can come back as [dim] instead of [[dim]].
  if (typeof list[0] === "number") return [list as number[]];
  return list as number[][];
}

export interface CreateEmbedderOptions {
  modelId: string;
  /** "cls" for bge-* models, "mean" for MiniLM/E5 style models. */
  pooling?: "cls" | "mean";
  forceDevice?: Device;
  /** Pin the weight precision (used by the FP32 baseline comparison). */
  forceDtype?: Dtype;
  /**
   * Per-backend budget. A GPU driver can stall session creation indefinitely
   * (no error, no progress); without a deadline the UI would wait forever
   * instead of degrading. Defaults to 60s.
   */
  attemptTimeoutMs?: number;
  onProgress?: (p: EmbedProgress) => void;
}

function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`${label} 超时（${Math.round(ms / 1000)}s 未完成）`)), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (err) => {
        clearTimeout(timer);
        reject(err);
      },
    );
  });
}

export async function createEmbedder(options: CreateEmbedderOptions): Promise<Embedder> {
  const { modelId, pooling = "cls", forceDevice, forceDtype, onProgress } = options;
  const attemptTimeoutMs = options.attemptTimeoutMs ?? 60_000;

  const gpu = forceDevice === "wasm" ? { available: false, reason: "已手动切换到 WASM" } : await detectWebGpu();
  const chain: Candidate[] = forceDtype
    ? [{ device: forceDtype === "fp16" && gpu.available ? "webgpu" : "wasm", dtype: forceDtype }]
    : candidateChain(gpu.available, forceDevice);

  const errors: string[] = [];
  for (const [attempt, candidate] of chain.entries()) {
    const started = performance.now();
    try {
      onProgress?.({
        stage: "loading",
        message: `正在加载 ${modelId}（${candidate.device}/${candidate.dtype}，第 ${attempt + 1}/${chain.length} 个候选后端）`,
      });

      // The `pipeline` overload union (4 dtypes x many tasks) is too wide for
      // TypeScript to resolve here, so the call is narrowed manually.
      const buildPipeline = pipeline as unknown as (
        task: "feature-extraction",
        model: string,
        options: Record<string, unknown>,
      ) => Promise<FeatureExtractionPipeline>;

      const extractor: FeatureExtractionPipeline = await withTimeout(
        buildPipeline("feature-extraction", modelId, {
          device: candidate.device,
          dtype: candidate.dtype,
          progress_callback: (p: { status?: string; file?: string; progress?: number }) => {
            if (p?.status === "progress" && typeof p.progress === "number") {
              onProgress?.({
                stage: "loading",
                file: p.file,
                progress: p.progress,
                message: `${candidate.device}/${candidate.dtype} · ${p.file ?? "weights"} ${Math.round(p.progress)}%`,
              });
            }
          },
        }),
        attemptTimeoutMs,
        `${candidate.device}/${candidate.dtype} 初始化`,
      );

      // Warm-up: the first inference pays for graph optimisation / shader
      // compilation. Doing it here keeps that cost out of the first user query
      // and lets us report "cold" vs "warm" numbers honestly.
      const warmStart = performance.now();
      await extractor(["warmup"], { pooling, normalize: true });
      const warmMs = performance.now() - warmStart;

      const probe = await extractor(["dimension probe"], { pooling, normalize: true });
      const dim = toVectors(probe)[0]?.length ?? 0;
      if (!dim) throw new Error("无法确定向量维度");

      const loadMs = performance.now() - started;
      const key = `${candidate.device}/${candidate.dtype}`;

      onProgress?.({
        stage: "warmup",
        message: `${LABELS[key] ?? key} 就绪，warmup ${warmMs.toFixed(0)}ms，dim=${dim}`,
      });

      const embedder: Embedder = {
        modelId,
        dim,
        loadMs,
        wasmThreads: candidate.device === "wasm" ? WASM_THREADS : 0,
        backend: {
          device: candidate.device,
          dtype: candidate.dtype,
          label: LABELS[key] ?? key,
          degraded: candidate.device === "wasm",
          loadMs,
          reason:
            candidate.device === "wasm"
              ? forceDevice === "wasm"
                ? "已手动切换到 WASM"
                : (gpu.reason ?? "WebGPU 不可用")
              : undefined,
        },
        async embedDocuments(texts, batchSize, onBatch) {
          const vectors: number[][] = [];
          const start = performance.now();
          const size = Math.max(1, batchSize);
          for (let i = 0; i < texts.length; i += size) {
            const batch = texts.slice(i, i + size);
            const out = await extractor(batch, { pooling, normalize: true });
            vectors.push(...toVectors(out));
            onBatch?.(Math.min(i + size, texts.length), texts.length);
          }
          return { vectors, ms: performance.now() - start };
        },
        async embedQuery(text) {
          const start = performance.now();
          const out = await extractor([text], { pooling, normalize: true });
          const vector = toVectors(out)[0];
          return { vector, ms: performance.now() - start };
        },
        async dispose() {
          await extractor.dispose?.();
        },
      };
      return embedder;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      errors.push(`${candidate.device}/${candidate.dtype}: ${message}`);
      onProgress?.({
        stage: "loading",
        message: `${candidate.device}/${candidate.dtype} 失败（${message.slice(0, 140)}），尝试下一个后端`,
      });
    }
  }

  throw new Error(
    `所有推理后端均加载失败：\n${errors.join("\n")}\n` +
      "请确认已执行 `npm run setup`（模型与 ONNX Runtime 文件位于 public/）。",
  );
}
