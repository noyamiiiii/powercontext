/**
 * Contract tests for the repository + service layers.
 *
 * These use an in-memory double of `Collection` so the business rules
 * (validation, dedupe, refresh policy, result normalisation, error wrapping)
 * can be verified on a machine where the seekdb native binding is unavailable.
 *
 * IMPORTANT: the double exists only here, in tests. The application runtime has
 * exactly one storage implementation -- seekdb -- wired in
 * `createKnowledgeService({ resolveCollection: getCollection, ... })`.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { config } from "../server/config";
import { DatabaseError, ValidationError } from "../server/errors";
import { chunkText } from "../web/src/lib/chunk";
import * as repo from "../server/repositories/knowledgeRepo";
import { createKnowledgeService } from "../server/services/knowledgeService";

interface Row {
  text: string;
  metadata: Record<string, unknown>;
  embedding: number[];
}

function cosine(a: number[], b: number[]): number {
  let dot = 0;
  let na = 0;
  let nb = 0;
  for (let i = 0; i < a.length; i += 1) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  return dot / (Math.sqrt(na) * Math.sqrt(nb) || 1);
}

class FakeCollection {
  readonly name = "kb_test";
  readonly dimension = config.EMBEDDING_DIM;
  readonly distance = "cosine";

  rows = new Map<string, Row>();
  refreshCalls = 0;
  failNextAdd = false;
  lastHybridOptions: Record<string, unknown> | null = null;

  async add(options: {
    ids: string[];
    documents: string[];
    embeddings: number[][];
    metadatas: Record<string, unknown>[];
  }): Promise<void> {
    if (this.failNextAdd) {
      this.failNextAdd = false;
      throw new Error("driver exploded: secret internal detail");
    }
    options.ids.forEach((id, i) => {
      if (this.rows.has(id)) throw new Error(`duplicate id ${id}`);
      this.rows.set(id, {
        text: options.documents[i],
        metadata: options.metadatas?.[i] ?? {},
        embedding: options.embeddings[i],
      });
    });
  }

  async upsert(options: {
    ids: string[];
    documents: string[];
    embeddings: number[][];
    metadatas: Record<string, unknown>[];
  }): Promise<void> {
    options.ids.forEach((id, i) => {
      this.rows.set(id, {
        text: options.documents[i],
        metadata: options.metadatas?.[i] ?? {},
        embedding: options.embeddings[i],
      });
    });
  }

  async delete(options: { ids?: string[] }): Promise<void> {
    for (const id of options.ids ?? []) this.rows.delete(id);
  }

  async count(): Promise<number> {
    return this.rows.size;
  }

  async refresh_index(): Promise<void> {
    this.refreshCalls += 1;
  }

  private ranked(embedding: number[], limit: number): { id: string; distance: number }[] {
    return [...this.rows.entries()]
      .map(([id, row]) => ({ id, distance: 1 - cosine(embedding, row.embedding) }))
      .sort((a, b) => a.distance - b.distance)
      .slice(0, limit);
  }

  async query(options: { queryEmbeddings: number[][]; nResults: number }) {
    const hits = this.ranked(options.queryEmbeddings[0], options.nResults);
    return {
      ids: [hits.map((h) => h.id)],
      documents: [hits.map((h) => this.rows.get(h.id)!.text)],
      metadatas: [hits.map((h) => this.rows.get(h.id)!.metadata)],
      distances: [hits.map((h) => h.distance)],
    };
  }

  async hybridSearch(options: {
    query: { whereDocument?: { $contains?: string } };
    knn: { queryEmbeddings: number[][] };
    rank?: { rrf?: { rankConstant?: number } };
    nResults: number;
  }) {
    this.lastHybridOptions = options as unknown as Record<string, unknown>;
    const keyword = (options.query.whereDocument?.$contains ?? "").toLowerCase();
    const fulltext = [...this.rows.entries()]
      .filter(([, row]) => keyword.length > 0 && row.text.toLowerCase().includes(keyword))
      .map(([id]) => id);
    const vector = this.ranked(options.knn.queryEmbeddings[0], options.nResults).map((h) => h.id);

    const k = options.rank?.rrf?.rankConstant ?? 60;
    const fused = new Map<string, number>();
    for (const [listIndex, list] of [fulltext, vector].entries()) {
      void listIndex;
      list.forEach((id, rank) => {
        fused.set(id, (fused.get(id) ?? 0) + 1 / (k + rank + 1));
      });
    }
    const ordered = [...fused.entries()].sort((a, b) => b[1] - a[1]).slice(0, options.nResults);

    return {
      ids: [ordered.map(([id]) => id)],
      documents: [ordered.map(([id]) => this.rows.get(id)!.text)],
      metadatas: [ordered.map(([id]) => this.rows.get(id)!.metadata)],
      distances: [ordered.map(([, score]) => score)],
    };
  }

  async get(options: { whereDocument?: { $contains?: string }; limit?: number }) {
    const keyword = (options.whereDocument?.$contains ?? "").toLowerCase();
    const matched = [...this.rows.entries()]
      .filter(([, row]) => row.text.toLowerCase().includes(keyword))
      .slice(0, options.limit ?? 10);
    return {
      ids: matched.map(([id]) => id),
      documents: matched.map(([, row]) => row.text),
      metadatas: matched.map(([, row]) => row.metadata),
    };
  }

  async peek(limit: number) {
    const entries = [...this.rows.entries()].slice(0, limit);
    return {
      ids: entries.map(([id]) => id),
      documents: entries.map(([, row]) => row.text),
      metadatas: entries.map(([, row]) => row.metadata),
    };
  }
}

function makeService(collection: FakeCollection) {
  return createKnowledgeService({
    resolveCollection: async () => collection as unknown as repo.CollectionLike,
    dropCollection: async () => {
      collection.rows.clear();
    },
    listCollections: async () => [{ name: collection.name, kb: "test", count: collection.rows.size }],
    connectionInfo: () => ({ mode: "test" }),
  });
}

const dim = config.EMBEDDING_DIM;
const vec = (seed: number): number[] => Array.from({ length: dim }, (_, i) => ((i * seed) % 7) - 3);

const DOCS = [
  { id: "a", text: "向量索引是异步可见的，写入后必须 refresh_index 才能检索到", embedding: vec(1) },
  { id: "b", text: "WebGPU 不可用时会自动降级到 WASM 后端", embedding: vec(2) },
  { id: "c", text: "RRF 把全文与向量的排名融合成一个列表", embedding: vec(3) },
];

test("ingest 写入后立即刷新索引并返回统计", async () => {
  const collection = new FakeCollection();
  const service = makeService(collection);
  const result = await service.ingest("test", DOCS, { mode: "add" });
  assert.equal(result.inserted, 3);
  assert.equal(result.total, 3);
  assert.equal(result.refreshed, config.REFRESH_MODE === "always");
  assert.ok(collection.refreshCalls >= 1 || config.REFRESH_MODE !== "always");
});

test("ingest 去重重复 id 并统计 skipped", async () => {
  const collection = new FakeCollection();
  const service = makeService(collection);
  const result = await service.ingest("test", [...DOCS, DOCS[0]], { mode: "add" });
  assert.equal(result.inserted, 3);
  assert.equal(result.skipped, 1);
});

test("ingest 拒绝维度不匹配的向量", async () => {
  const collection = new FakeCollection();
  const service = makeService(collection);
  await assert.rejects(
    () => service.ingest("test", [{ id: "x", text: "bad", embedding: [0.1, 0.2] }]),
    (err: unknown) => err instanceof ValidationError && /expected 512/.test((err as Error).message),
  );
});

test("ingest 把驱动异常转换为 DatabaseError 且不泄露内部信息", async () => {
  const collection = new FakeCollection();
  collection.failNextAdd = true;
  const service = makeService(collection);
  await assert.rejects(
    () => service.ingest("test", DOCS),
    (err: unknown) =>
      err instanceof DatabaseError &&
      !/secret internal detail/.test((err as Error).message) &&
      err.status === 503,
  );
});

test("hybrid 检索走 seekdb 的 RRF 参数并返回融合分数", async () => {
  const collection = new FakeCollection();
  const service = makeService(collection);
  await service.ingest("test", DOCS);
  const result = await service.search("test", {
    queryEmbedding: vec(1),
    queryText: "refresh_index",
    topK: 3,
    mode: "hybrid",
  });
  assert.equal(result.mode, "hybrid");
  assert.equal(result.scoreKind, "rrf");
  assert.ok(result.results.length >= 1);
  assert.equal(result.results[0].id, "a", "关键词与向量都指向 a，融合后应排第一");
  assert.ok(typeof result.results[0].score === "number");
  const options = collection.lastHybridOptions as {
    rank?: { rrf?: { rankConstant?: number } };
    query?: { whereDocument?: { $contains?: string } };
  };
  assert.equal(options.rank?.rrf?.rankConstant, 60, "RRF 融合必须交给 seekdb，参数需透传");
  assert.equal(options.query?.whereDocument?.$contains, "refresh_index");
});

test("queryText 为空时 hybrid 退化为纯向量检索", async () => {
  const collection = new FakeCollection();
  const service = makeService(collection);
  await service.ingest("test", DOCS);
  const result = await service.search("test", { queryEmbedding: vec(2), queryText: "   ", topK: 3, mode: "hybrid" });
  assert.equal(result.mode, "vector");
  assert.equal(result.scoreKind, "cosine-similarity");
  assert.equal(result.results[0].id, "b");
});

test("纯向量检索把余弦距离转换为相似度", async () => {
  const collection = new FakeCollection();
  const service = makeService(collection);
  await service.ingest("test", DOCS);
  const result = await service.search("test", { queryEmbedding: vec(2), topK: 1, mode: "vector" });
  const [top] = result.results;
  assert.equal(top.id, "b");
  assert.ok(top.score !== null && top.score > 0.99, "自身向量的相似度应接近 1");
});

test("纯全文检索使用 get() 的扁平结果结构", async () => {
  const collection = new FakeCollection();
  const service = makeService(collection);
  await service.ingest("test", DOCS);
  const result = await service.search("test", { queryEmbedding: vec(1), queryText: "WASM", topK: 5, mode: "fulltext" });
  assert.equal(result.mode, "fulltext");
  assert.equal(result.scoreKind, "keyword");
  assert.deepEqual(result.results.map((r) => r.id), ["b"]);
});

test("topK 越界被拒绝", async () => {
  const collection = new FakeCollection();
  const service = makeService(collection);
  await assert.rejects(
    () => service.search("test", { queryEmbedding: vec(1), topK: 0, mode: "vector" }),
    (err: unknown) => err instanceof ValidationError,
  );
});

test("deferred 模式下新写入在检索前自动刷新（增量导入后立即可搜）", async () => {
  const collection = new FakeCollection();
  const service = makeService(collection);
  const original = config.REFRESH_MODE;
  (config as { REFRESH_MODE: string }).REFRESH_MODE = "deferred";
  try {
    await service.ingest("test", DOCS);
    const before = collection.refreshCalls;
    assert.equal(before, 0, "deferred 模式写入时不应刷新");

    const first = await service.search("test", { queryEmbedding: vec(1), queryText: "RRF", topK: 3, mode: "hybrid" });
    assert.equal(collection.refreshCalls, 1, "检索前应刷新一次");
    assert.ok(first.refreshMs >= 0);
    assert.equal(first.results[0].id, "c");

    // 已刷新过，第二次检索不应重复刷新
    await service.search("test", { queryEmbedding: vec(1), queryText: "RRF", topK: 3, mode: "hybrid" });
    assert.equal(collection.refreshCalls, 1);
  } finally {
    (config as { REFRESH_MODE: string }).REFRESH_MODE = original;
  }
});

test("stats 反映集合维度与片段数", async () => {
  const collection = new FakeCollection();
  const service = makeService(collection);
  await service.ingest("test", DOCS);
  const stats = await service.stats("test");
  assert.equal(stats.count, 3);
  assert.equal(stats.dimension, dim);
  assert.equal(stats.distance, "cosine");
});

test("切片保留段落并在超长时按句子切分", () => {
  const short = chunkText("第一段内容。\n\n第二段内容。");
  assert.equal(short.length, 2);

  const long = `${"这是一句用于测试切分逻辑的中文句子。".repeat(30)}`;
  const chunks = chunkText(long, { maxChars: 200 });
  assert.ok(chunks.length > 1);
  for (const chunk of chunks) assert.ok(chunk.length <= 220, `chunk too long: ${chunk.length}`);
});
