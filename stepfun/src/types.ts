export type EmbeddingDevice = "webgpu" | "wasm";
export type EmbeddingDtype = "fp16" | "q8";

export interface EmbeddingBackend {
  device: EmbeddingDevice;
  dtype: EmbeddingDtype;
  modelId: string;
  dimension: number;
  fallbackReason?: string;
}

export interface KnowledgeBase {
  id: string;
  name: string;
  count: number;
  createdAt: string;
}

export interface PreparedDocument {
  id: string;
  text: string;
  metadata: {
    source: string;
    chunk: number;
    importedAt: string;
  };
}

export interface KnowledgeDocument extends PreparedDocument {
  embedding: number[];
}

export interface SearchResult {
  id: string;
  text: string;
  metadata: Record<string, unknown> | null;
  score: number | null;
}

export interface SearchResponse {
  results: SearchResult[];
  databaseMs: number;
  fusion: string;
}

export interface MetricEntry {
  id: string;
  label: string;
  durationMs: number;
  detail: string;
  recordedAt: string;
}

export interface EmbeddingLoadResult {
  backend: EmbeddingBackend;
  loadMs: number;
}

export interface EmbeddingBatchResult {
  embeddings: number[][];
  embeddingMs: number;
}

export interface EmbeddingProgress {
  operation: "load" | "documents" | "query";
  progress: number;
  message: string;
}
