import { config } from "../config";
import { getCollection, listCollections, dropCollection, connectionInfo } from "../db/seekdb";
import { PayloadTooLargeError, ValidationError } from "../errors";
import * as repo from "../repositories/knowledgeRepo";
import type { CollectionLike, DocumentInput } from "../repositories/knowledgeRepo";

/**
 * Business rules for the mini knowledge base.
 *
 * Responsibilities kept here (and out of controllers):
 *  - validating that every vector really comes from the client's embedder
 *  - deciding when the vector index must be refreshed so freshly written
 *    documents are immediately searchable
 *  - timing each database stage for the benchmark table in the UI / docs
 *
 * Note there is no HTTP type in this file: the transport can change freely.
 */

/**
 * Storage dependencies injected at construction time.
 * Production wires the real seekdb functions; the contract tests wire an
 * in-memory double so the business rules can be verified without a database.
 */
export interface KnowledgeServiceDeps {
  resolveCollection: (kb: string) => Promise<CollectionLike>;
  dropCollection: (kb: string) => Promise<void>;
  listCollections: () => Promise<{ name: string; kb: string; count: number }[]>;
  connectionInfo: () => Record<string, unknown>;
}

export type SearchMode = "hybrid" | "vector" | "fulltext";

export interface IngestResult {
  kb: string;
  inserted: number;
  skipped: number;
  total: number;
  refreshed: boolean;
  timings: { writeMs: number; refreshMs: number };
}

export interface SearchResultItem {
  id: string;
  text: string | null;
  metadata: Record<string, unknown> | null;
  score: number | null;
  rawScore: number | null;
}

export interface SearchResult {
  kb: string;
  mode: SearchMode;
  took: number;
  dbMs: number;
  refreshMs: number;
  total: number;
  scoreKind: "rrf" | "cosine-similarity" | "keyword";
  results: SearchResultItem[];
}

export function createKnowledgeService(deps: KnowledgeServiceDeps) {
  /** Knowledge bases whose index has unrefreshed writes (deferred refresh mode). */
  const dirty = new Set<string>();

function validateEmbedding(embedding: unknown, index: number): number[] {
  if (!Array.isArray(embedding)) {
    throw new ValidationError(`documents[${index}].embedding must be an array of numbers`);
  }
  if (embedding.length !== config.EMBEDDING_DIM) {
    throw new ValidationError(
      `documents[${index}].embedding has ${embedding.length} dims, expected ${config.EMBEDDING_DIM}. ` +
        "The browser embedder and EMBEDDING_DIM must agree.",
    );
  }
  for (let i = 0; i < embedding.length; i += 1) {
    const v = embedding[i];
    if (typeof v !== "number" || !Number.isFinite(v)) {
      throw new ValidationError(`documents[${index}].embedding[${i}] is not a finite number`);
    }
  }
  return embedding as number[];
}

function assertBoundedDocuments(docs: unknown[]): void {
  if (docs.length === 0) throw new ValidationError("documents must not be empty");
  if (docs.length > config.MAX_DOCUMENTS_PER_REQUEST) {
    throw new PayloadTooLargeError(
      `At most ${config.MAX_DOCUMENTS_PER_REQUEST} documents per request (got ${docs.length})`,
    );
  }
}

async function ingest(
  kb: string,
  docs: DocumentInput[],
  options: { mode?: "add" | "upsert" } = {},
): Promise<IngestResult> {
  assertBoundedDocuments(docs);

  const seen = new Set<string>();
  const unique: DocumentInput[] = [];
  let skipped = 0;
  for (let i = 0; i < docs.length; i += 1) {
    const doc = docs[i];
    if (!doc?.id || typeof doc.id !== "string") {
      throw new ValidationError(`documents[${i}].id must be a non-empty string`);
    }
    if (typeof doc.text !== "string" || doc.text.trim().length === 0) {
      throw new ValidationError(`documents[${i}].text must be a non-empty string`);
    }
    if (doc.text.length > config.MAX_DOCUMENT_CHARS) {
      throw new PayloadTooLargeError(
        `documents[${i}].text exceeds ${config.MAX_DOCUMENT_CHARS} chars`,
      );
    }
    if (seen.has(doc.id)) {
      skipped += 1;
      continue;
    }
    seen.add(doc.id);
    unique.push({ ...doc, embedding: validateEmbedding(doc.embedding, i) });
  }

  const collection = await deps.resolveCollection(kb);

  const writeStart = performance.now();
  if (options.mode === "upsert") {
    await repo.upsertDocuments(collection, unique);
  } else {
    await repo.insertDocuments(collection, unique);
  }
  const writeMs = performance.now() - writeStart;

  let refreshMs = 0;
  let refreshed = false;
  if (config.REFRESH_MODE === "always") {
    const start = performance.now();
    await repo.refreshIndex(collection);
    refreshMs = performance.now() - start;
    refreshed = true;
    dirty.delete(kb);
  } else {
    // deferred / manual: mark the base dirty so the next search can flush the index.
    dirty.add(kb);
  }

  const total = await repo.countDocuments(collection);
  return {
    kb,
    inserted: unique.length,
    skipped,
    total,
    refreshed,
    timings: { writeMs: round(writeMs), refreshMs: round(refreshMs) },
  };
}

async function search(
  kb: string,
  input: { queryEmbedding: number[]; queryText?: string; topK: number; mode: SearchMode },
): Promise<SearchResult> {
  const { mode, topK } = input;
  if (!Number.isInteger(topK) || topK < 1 || topK > 100) {
    throw new ValidationError("topK must be an integer between 1 and 100");
  }
  const queryEmbedding = validateEmbedding(input.queryEmbedding, 0);
  const collection = await deps.resolveCollection(kb);

  // Deferred mode: flush pending writes before searching so results always
  // reflect the documents the user just imported.
  let refreshMs = 0;
  if (dirty.has(kb) && config.REFRESH_MODE !== "manual") {
    const start = performance.now();
    await repo.refreshIndex(collection);
    refreshMs = performance.now() - start;
    dirty.delete(kb);
  }

  const start = performance.now();
  let results: repo.SearchHit[];
  let scoreKind: SearchResult["scoreKind"];
  let effectiveMode = mode;

  if (mode === "fulltext") {
    results = await repo.fulltextSearch(collection, input.queryText ?? "", topK);
    scoreKind = "keyword";
  } else if (mode === "vector" || !input.queryText?.trim()) {
    results = await repo.vectorSearch(collection, { queryEmbedding, topK });
    scoreKind = "cosine-similarity";
    if (mode === "hybrid") effectiveMode = "vector";
  } else {
    results = await repo.hybridSearch(collection, {
      queryEmbedding,
      queryText: input.queryText,
      topK,
    });
    scoreKind = "rrf";
  }
  const dbMs = performance.now() - start;

  return {
    kb,
    mode: effectiveMode,
    took: round(dbMs + refreshMs),
    dbMs: round(dbMs),
    refreshMs: round(refreshMs),
    total: results.length,
    scoreKind,
    results: results.map((hit) => ({
      id: hit.id,
      text: hit.text,
      metadata: hit.metadata,
      score: hit.score === null ? null : Number(hit.score.toFixed(6)),
      rawScore: hit.rawScore === null ? null : Number(hit.rawScore.toFixed(6)),
    })),
  };
}

async function refresh(kb: string): Promise<{ kb: string; refreshMs: number; total: number }> {
  const collection = await deps.resolveCollection(kb);
  const start = performance.now();
  await repo.refreshIndex(collection);
  const refreshMs = round(performance.now() - start);
  dirty.delete(kb);
  return { kb, refreshMs, total: await repo.countDocuments(collection) };
}

async function reset(kb: string): Promise<{ kb: string; total: number }> {
  await deps.dropCollection(kb);
  dirty.delete(kb);
  const collection = await deps.resolveCollection(kb);
  return { kb, total: await repo.countDocuments(collection) };
}

async function stats(kb: string) {
  const collection = await deps.resolveCollection(kb);
  return {
    kb,
    collection: collection.name,
    dimension: collection.dimension,
    distance: collection.distance,
    count: await repo.countDocuments(collection),
    pendingRefresh: dirty.has(kb),
  };
}

async function overview() {
  return {
    connection: deps.connectionInfo(),
    collections: await deps.listCollections(),
  };
}

async function preview(kb: string, limit: number) {
  const collection = await deps.resolveCollection(kb);
  return repo.peekDocuments(collection, Math.min(Math.max(limit, 1), 100));
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

  return {
    ingest,
    search,
    refresh,
    reset,
    stats,
    overview,
    preview,
  };
}

/**
 * Production instance: every knowledge-base lookup goes through the real
 * seekdb connection layer. There is no in-memory fallback at runtime.
 */
export const knowledgeService = createKnowledgeService({
  resolveCollection: getCollection,
  dropCollection,
  listCollections,
  connectionInfo,
});
