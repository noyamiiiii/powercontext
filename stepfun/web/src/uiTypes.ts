/** Shared UI-facing view models (kept out of components so props stay typed). */

export interface IngestProgress {
  running: boolean;
  stage: string;
  done: number;
  total: number;
}

export interface IngestSummary {
  chunks: number;
  embedMs: number;
  uploadMs: number;
  writeMs: number;
  refreshMs: number;
  inserted: number;
  skipped: number;
  collectionTotal: number;
  throughput: number;
  backendLabel: string;
  batchSize: number;
}

export interface QueryTimings {
  embedMs: number;
  networkMs: number;
  dbMs: number;
  refreshMs: number;
  totalMs: number;
  backendLabel: string;
}

export interface BenchmarkRow {
  query: string;
  rank: number | null;
  hit: boolean;
  embedMs: number;
  dbMs: number;
  totalMs: number;
  topIds: string[];
}

export interface BenchmarkSummary {
  label: string;
  backendLabel: string;
  dtype: string;
  cases: number;
  recall5: number;
  recall10: number;
  ndcg10: number;
  mrr: number;
  embedMedianMs: number;
  dbMedianMs: number;
  totalMedianMs: number;
  rows: BenchmarkRow[];
}
