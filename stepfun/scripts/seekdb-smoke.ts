import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { KnowledgeStore } from "../server/store.js";

function embedding(seed: number): number[] {
  const values = Array.from({ length: 512 }, (_, index) =>
    Math.sin((index + 1) * seed),
  );
  const norm = Math.sqrt(values.reduce((sum, value) => sum + value ** 2, 0));
  return values.map((value) => value / norm);
}

const directory = await mkdtemp(path.join(os.tmpdir(), "edge-course-lens-"));
const databaseMode = process.env.SEEKDB_MODE ?? "server";
const store = new KnowledgeStore(
  databaseMode === "embedded"
    ? { path: directory, database: "test" }
    : {
        host: process.env.SEEKDB_HOST ?? "127.0.0.1",
        port: Number(process.env.SEEKDB_PORT ?? "2881"),
        user: process.env.SEEKDB_USER ?? "root",
        password: process.env.SEEKDB_PASSWORD ?? "",
        database: process.env.SEEKDB_DATABASE ?? "test",
      },
  directory,
);

let exitCode = 0;
try {
  console.log("seekdb-smoke: create");
  const collection = await store.createKnowledgeBase("seekdb smoke test");
  console.log("seekdb-smoke: upsert");
  const targetEmbedding = embedding(1);
  await store.upsertDocuments(collection.id, [
    {
      id: "doc-edge",
      text: "浏览器端推理使用 WebGPU，失败时自动降级到 WASM。",
      embedding: targetEmbedding,
      metadata: { source: "fixture.txt" },
    },
    {
      id: "doc-other",
      text: "数据库连接池和事务隔离级别。",
      embedding: embedding(4),
      metadata: { source: "fixture.txt" },
    },
  ]);

  console.log("seekdb-smoke: hybrid-search");
  const results = await store.search(
    collection.id,
    "WebGPU",
    targetEmbedding,
    2,
  );
  assert.ok(results.length > 0, "hybrid search should return results");
  assert.equal(results[0]?.id, "doc-edge");
  assert.match(results[0]?.text ?? "", /WebGPU/);
  assert.equal((await store.listKnowledgeBases())[0]?.count, 2);
  console.log(
    JSON.stringify({
      status: "ok",
      count: results.length,
      top: results[0]?.id,
    }),
  );
} catch (error) {
  console.error(error);
  exitCode = 1;
} finally {
  await store.close();
}

console.log("seekdb-smoke: close");
process.exit(exitCode);
