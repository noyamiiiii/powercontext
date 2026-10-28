import type {
  KnowledgeBase,
  KnowledgeDocument,
  SearchResponse,
} from "../types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { error?: string }
      | null;
    throw new Error(payload?.error ?? `请求失败：${response.status}`);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function listCollections(): Promise<KnowledgeBase[]> {
  return request("/api/collections");
}

export function createCollection(name: string): Promise<KnowledgeBase> {
  return request("/api/collections", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function deleteCollection(id: string): Promise<void> {
  return request(`/api/collections/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function upsertDocuments(
  id: string,
  documents: KnowledgeDocument[],
): Promise<{ count: number; databaseMs: number }> {
  return request(`/api/collections/${encodeURIComponent(id)}/documents`, {
    method: "POST",
    body: JSON.stringify({ documents }),
  });
}

export function searchDocuments(
  id: string,
  query: string,
  embedding: number[],
  limit: number,
): Promise<SearchResponse> {
  return request(`/api/collections/${encodeURIComponent(id)}/search`, {
    method: "POST",
    body: JSON.stringify({ query, queryEmbedding: embedding, limit }),
  });
}
