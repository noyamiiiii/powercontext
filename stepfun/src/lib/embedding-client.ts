import type {
  EmbeddingBackend,
  EmbeddingBatchResult,
  EmbeddingLoadResult,
  EmbeddingProgress,
} from "../types";

type WorkerResponse =
  | { id: number; type: "progress"; progress: EmbeddingProgress }
  | { id: number; type: "result"; result: unknown }
  | { id: number; type: "error"; error: string };

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
  onProgress?: (progress: EmbeddingProgress) => void;
}

export class EmbeddingClient {
  private readonly worker: Worker;
  private readonly pending = new Map<number, PendingRequest>();
  private nextId = 1;

  constructor() {
    this.worker = new Worker(
      new URL("../workers/embedding.worker.ts", import.meta.url),
      { type: "module" },
    );
    this.worker.addEventListener("message", (event: MessageEvent<WorkerResponse>) => {
      const message = event.data;
      const request = this.pending.get(message.id);
      if (!request) {
        return;
      }
      if (message.type === "progress") {
        request.onProgress?.(message.progress);
        return;
      }
      this.pending.delete(message.id);
      if (message.type === "error") {
        request.reject(new Error(message.error));
      } else {
        request.resolve(message.result);
      }
    });
    this.worker.addEventListener("error", (event) => {
      for (const request of this.pending.values()) {
        request.reject(new Error(event.message || "Embedding Worker 崩溃"));
      }
      this.pending.clear();
    });
  }

  load(onProgress?: (progress: EmbeddingProgress) => void): Promise<EmbeddingLoadResult> {
    return this.send("load", {}, onProgress);
  }

  embedDocuments(
    texts: string[],
    batchSize: number,
    onProgress?: (progress: EmbeddingProgress) => void,
  ): Promise<EmbeddingBatchResult> {
    return this.send("embed-documents", { texts, batchSize }, onProgress);
  }

  embedQuery(query: string): Promise<EmbeddingBatchResult> {
    return this.send("embed-query", { query });
  }

  backend(): Promise<EmbeddingBackend> {
    return this.send("backend", {});
  }

  terminate(): void {
    this.worker.terminate();
  }

  private send<T>(
    operation: string,
    payload: Record<string, unknown>,
    onProgress?: (progress: EmbeddingProgress) => void,
  ): Promise<T> {
    const id = this.nextId++;
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, {
        resolve: (value) => resolve(value as T),
        reject,
        onProgress,
      });
      this.worker.postMessage({ id, operation, ...payload });
    });
  }
}
