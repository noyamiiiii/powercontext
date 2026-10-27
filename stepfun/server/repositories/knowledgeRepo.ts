import type { Collection, Metadata, QueryResult } from "seekdb";
import { wrapDbError } from "../errors";

/**
 * The subset of seekdb's `Collection` this app relies on.
 * Narrowing it keeps the repository honest about what it uses and lets the
 * contract tests substitute an in-memory double without faking the whole SDK.
 */
export type CollectionLike = Pick<
  Collection,
  | "name"
  | "dimension"
  | "distance"
  | "add"
  | "upsert"
  | "delete"
  | "get"
  | "query"
  | "hybridSearch"
  | "count"
  | "refresh_index"
  | "peek"
>;

/**
 * Repository layer: the only place that knows about seekdb's SDK shapes.
 * Services deal in plain domain objects, so swapping the storage engine or
 * unit-testing the service layer never touches the driver.
 */

export interface DocumentInput {
  id: string;
  text: string;
  embedding: number[];
  metadata?: Record<string, string | number | boolean | null>;
}

export interface SearchHit {
  id: string;
  text: string | null;
  metadata: Record<string, unknown> | null;
  /** Raw value returned by seekdb (HNSW distance, or RRF fused score). */
  rawScore: number | null;
  /** 1 - distance for cosine vector search; equal to rawScore for hybrid RRF. */
  score: number | null;
}

export interface SearchOptions {
  queryEmbedding: number[];
  queryText?: string;
  topK: number;
  rankWindowSize?: number;
  rankConstant?: number;
}

function toMetadata(metadata: DocumentInput["metadata"]): Metadata | undefined {
  if (!metadata) return undefined;
  const out: Metadata = {};
  for (const [key, value] of Object.entries(metadata)) {
    if (value === null || value === undefined) continue;
    out[key] = value;
  }
  return Object.keys(out).length ? out : undefined;
}

function flatten(result: QueryResult): SearchHit[] {
  const ids = result.ids?.[0] ?? [];
  const documents = result.documents?.[0] ?? [];
  const metadatas = result.metadatas?.[0] ?? [];
  const distances = result.distances?.[0] ?? [];

  return ids.map((id, i) => {
    const raw = typeof distances[i] === "number" ? (distances[i] as number) : null;
    return {
      id,
      text: (documents[i] as string | null) ?? null,
      metadata: (metadatas[i] as Record<string, unknown> | null) ?? null,
      rawScore: raw,
      score: raw,
    };
  });
}

export async function insertDocuments(collection: CollectionLike, docs: DocumentInput[]): Promise<void> {
  if (docs.length === 0) return;
  try {
    await collection.add({
      ids: docs.map((d) => d.id),
      documents: docs.map((d) => d.text),
      embeddings: docs.map((d) => d.embedding),
      metadatas: docs.map((d) => (toMetadata(d.metadata) ?? {}) as Metadata),
    });
  } catch (err) {
    throw wrapDbError(err, "insertDocuments");
  }
}

export async function upsertDocuments(collection: CollectionLike, docs: DocumentInput[]): Promise<void> {
  if (docs.length === 0) return;
  try {
    await collection.upsert({
      ids: docs.map((d) => d.id),
      documents: docs.map((d) => d.text),
      embeddings: docs.map((d) => d.embedding),
      metadatas: docs.map((d) => (toMetadata(d.metadata) ?? {}) as Metadata),
    });
  } catch (err) {
    throw wrapDbError(err, "upsertDocuments");
  }
}

export async function deleteByIds(collection: CollectionLike, ids: string[]): Promise<void> {
  if (ids.length === 0) return;
  try {
    await collection.delete({ ids });
  } catch (err) {
    throw wrapDbError(err, "deleteByIds");
  }
}

/**
 * Hybrid retrieval executed **inside seekdb**.
 *
 * `query.whereDocument` drives the fulltext index, `knn` drives the HNSW index,
 * and `rank.rrf` fuses the two ranked lists in the database via RRF. We never
 * merge keyword and vector hits in application code.
 */
export async function hybridSearch(collection: CollectionLike, options: SearchOptions): Promise<SearchHit[]> {
  try {
    const result = await collection.hybridSearch({
      query: {
        whereDocument: { $contains: options.queryText ?? "" },
        nResults: options.topK,
      },
      knn: {
        queryEmbeddings: [options.queryEmbedding],
        nResults: options.topK,
      },
      rank: {
        rrf: {
          rankWindowSize: options.rankWindowSize ?? 60,
          rankConstant: options.rankConstant ?? 60,
        },
      },
      nResults: options.topK,
      include: ["documents", "metadatas", "distances"],
    });
    const hits = flatten(result);
    // For RRF the raw value is a fused score (higher is better), not a distance.
    return hits.map((hit) => ({ ...hit, score: hit.rawScore }));
  } catch (err) {
    throw wrapDbError(err, "hybridSearch");
  }
}

export async function vectorSearch(collection: CollectionLike, options: SearchOptions): Promise<SearchHit[]> {
  try {
    const result = await collection.query({
      queryEmbeddings: [options.queryEmbedding],
      nResults: options.topK,
      include: ["documents", "metadatas", "distances"],
    });
    return flatten(result).map((hit) => ({
      ...hit,
      score: hit.rawScore === null ? null : 1 - hit.rawScore,
    }));
  } catch (err) {
    throw wrapDbError(err, "vectorSearch");
  }
}

/** Keyword-only retrieval through the fulltext index, used by the UI comparison view. */
export async function fulltextSearch(collection: CollectionLike, queryText: string, topK: number): Promise<SearchHit[]> {
  try {
    const result = await collection.get({
      whereDocument: { $contains: queryText },
      limit: topK,
      include: ["documents", "metadatas"],
    });
    // `get()` returns flat arrays, unlike `query()` which is nested per query.
    const ids = result.ids ?? [];
    const documents = result.documents ?? [];
    const metadatas = result.metadatas ?? [];
    return ids.map((id, i) => ({
      id,
      text: (documents[i] as string | null) ?? null,
      metadata: (metadatas[i] as Record<string, unknown> | null) ?? null,
      rawScore: null,
      score: null,
    }));
  } catch (err) {
    throw wrapDbError(err, "fulltextSearch");
  }
}

export async function countDocuments(collection: CollectionLike): Promise<number> {
  try {
    return await collection.count();
  } catch (err) {
    throw wrapDbError(err, "count");
  }
}

export async function refreshIndex(collection: CollectionLike): Promise<void> {
  try {
    await collection.refresh_index();
  } catch (err) {
    throw wrapDbError(err, "refresh_index");
  }
}

export async function peekDocuments(collection: CollectionLike, limit: number) {
  try {
    const result = await collection.peek(limit);
    const ids = result.ids ?? [];
    const documents = result.documents ?? [];
    const metadatas = result.metadatas ?? [];
    return ids.map((id, i) => ({
      id,
      text: (documents[i] as string | null) ?? null,
      metadata: (metadatas[i] as Record<string, unknown> | null) ?? null,
    }));
  } catch (err) {
    throw wrapDbError(err, "peek");
  }
}
