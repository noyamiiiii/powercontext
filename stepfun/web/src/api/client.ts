/**
 * Typed API client.
 *
 * Rules baked in here (so no component has to think about them):
 *  - 4xx  -> thrown immediately, message already human readable
 *  - 5xx / network -> retried up to 3 times with backoff, then a friendly error
 *  - the backend's canonical error envelope is unwrapped into `ApiError`
 */

export interface ApiConfig {
  embeddingModel: string;
  embeddingDim: number;
  queryInstruction: string;
  defaultKb: string;
  collectionPrefix: string;
  database: string;
  fulltextAnalyzer: string;
  fulltextTokenSize: number;
  refreshMode: "always" | "deferred" | "manual";
  maxDocumentsPerRequest: number;
  maxDocumentChars: number;
  mode: "embedded";
}

export interface KbStats {
  kb: string;
  collection: string;
  dimension: number;
  distance: string;
  count: number;
  pendingRefresh: boolean;
}

export interface KbListEntry {
  name: string;
  kb: string;
  count: number;
}

export interface SearchHitDto {
  id: string;
  text: string | null;
  metadata: Record<string, unknown> | null;
  score: number | null;
  rawScore: number | null;
}

export interface SearchResponse {
  kb: string;
  mode: "hybrid" | "vector" | "fulltext";
  took: number;
  dbMs: number;
  refreshMs: number;
  total: number;
  scoreKind: "rrf" | "cosine-similarity" | "keyword";
  results: SearchHitDto[];
}

export interface IngestResponse {
  kb: string;
  inserted: number;
  skipped: number;
  total: number;
  refreshed: boolean;
  timings: { writeMs: number; refreshMs: number };
}

export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
    readonly requestId?: string,
    readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const BASE = "/api";

const FRIENDLY: Record<string, string> = {
  VALIDATION_ERROR: "请求参数不合法",
  DATABASE_ERROR: "seekdb 操作失败，请查看服务端日志",
  NOT_FOUND: "资源不存在",
  PAYLOAD_TOO_LARGE: "单次提交的数据量过大",
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function request<T>(path: string, init?: RequestInit, retries = 3): Promise<T> {
  let lastError: unknown;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const res = await fetch(`${BASE}${path}`, {
        ...init,
        headers: {
          ...(init?.body ? { "content-type": "application/json" } : {}),
          ...init?.headers,
        },
      });

      if (!res.ok) {
        let payload: { error?: { code?: string; message?: string; requestId?: string; details?: unknown } } = {};
        try {
          payload = await res.json();
        } catch {
          /* non-JSON error body */
        }
        const code = payload.error?.code ?? `HTTP_${res.status}`;
        const message = payload.error?.message ?? FRIENDLY[code] ?? `请求失败 (HTTP ${res.status})`;
        // 4xx is the caller's fault: retrying will not help.
        if (res.status < 500) {
          throw new ApiError(code, message, res.status, payload.error?.requestId, payload.error?.details);
        }
        lastError = new ApiError(code, message, res.status, payload.error?.requestId, payload.error?.details);
      } else {
        return (await res.json()) as T;
      }
    } catch (err) {
      if (err instanceof ApiError && err.status < 500) throw err;
      lastError = err;
    }
    if (attempt < retries) await sleep(300 * 2 ** attempt);
  }

  if (!navigator.onLine) {
    throw new ApiError("OFFLINE", "当前离线，无法连接本地 seekdb 服务", 0);
  }
  throw lastError instanceof ApiError
    ? lastError
    : new ApiError("NETWORK_ERROR", "无法连接后端服务，请确认 npm run dev 已启动", 0);
}

export const api = {
  meta: () => request<{ config: ApiConfig; defaultKbStats: KbStats }>("/meta"),

  listKbs: () =>
    request<{ connection: Record<string, unknown>; collections: KbListEntry[] }>("/kbs"),

  createKb: (name: string) =>
    request<KbStats>("/kbs", { method: "POST", body: JSON.stringify({ name }) }),

  stats: (kb: string) => request<KbStats>(`/kbs/${kb}/stats`),

  resetKb: (kb: string) => request<{ kb: string; total: number }>(`/kbs/${kb}/reset`, { method: "POST" }),

  refresh: (kb: string) =>
    request<{ kb: string; refreshMs: number; total: number }>(`/kbs/${kb}/refresh`, { method: "POST" }),

  preview: (kb: string, limit = 20) =>
    request<{ kb: string; documents: { id: string; text: string | null; metadata: Record<string, unknown> | null }[] }>(
      `/kbs/${kb}/documents?limit=${limit}`,
    ),

  ingest: (
    kb: string,
    documents: { id: string; text: string; embedding: number[]; metadata?: Record<string, string | number | boolean | null> }[],
    mode: "add" | "upsert" = "add",
  ) =>
    request<IngestResponse>(`/kbs/${kb}/documents`, {
      method: "POST",
      body: JSON.stringify({ documents, mode }),
    }),

  search: (
    kb: string,
    body: { queryEmbedding: number[]; queryText?: string; topK: number; mode: "hybrid" | "vector" | "fulltext" },
  ) => request<SearchResponse>(`/kbs/${kb}/search`, { method: "POST", body: JSON.stringify(body) }),
};
