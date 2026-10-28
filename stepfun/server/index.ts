import path from "node:path";
import { fileURLToPath } from "node:url";

import express from "express";
import { z } from "zod";

import {
  EMBEDDING_DIMENSION,
  KnowledgeStore,
  type KnowledgeStoreConfig,
} from "./store.js";

const currentDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(currentDirectory, "..");
const dataDirectory = path.resolve(
  process.env.SEEKDB_DATA_DIR ?? path.join(projectRoot, ".seekdb"),
);
const port = Number(process.env.PORT ?? "8787");

const databaseMode = process.env.SEEKDB_MODE ?? "server";
const seekdbConfig: KnowledgeStoreConfig =
  databaseMode === "embedded"
    ? {
        path: dataDirectory,
        database: process.env.SEEKDB_DATABASE ?? "test",
      }
    : {
        host: process.env.SEEKDB_HOST ?? "127.0.0.1",
        port: Number(process.env.SEEKDB_PORT ?? "2881"),
        user: process.env.SEEKDB_USER ?? "root",
        password: process.env.SEEKDB_PASSWORD ?? "",
        database: process.env.SEEKDB_DATABASE ?? "test",
      };
const store = new KnowledgeStore(seekdbConfig, dataDirectory);
const app = express();
app.use(express.json({ limit: "64mb" }));

const embeddingSchema = z
  .array(z.number().finite())
  .length(EMBEDDING_DIMENSION);
const createCollectionSchema = z.object({
  name: z.string().trim().min(1).max(80),
});
const documentsSchema = z.object({
  documents: z
    .array(
      z.object({
        id: z.string().min(1).max(256),
        text: z.string().min(1).max(20_000),
        embedding: embeddingSchema,
        metadata: z
          .record(z.string(), z.union([z.string(), z.number(), z.boolean()]))
          .optional(),
      }),
    )
    .min(1)
    .max(128),
});
const searchSchema = z.object({
  query: z.string().trim().min(1).max(2_000),
  queryEmbedding: embeddingSchema,
  limit: z.number().int().min(1).max(20).default(5),
});

app.get("/api/health", async (_request, response, next) => {
  try {
    await store.ping();
    response.json({
      status: "ok",
      storage:
        databaseMode === "embedded" ? "seekdb-js embedded" : "seekdb-js server",
    });
  } catch (error) {
    next(error);
  }
});

app.get("/api/collections", async (_request, response, next) => {
  try {
    response.json(await store.listKnowledgeBases());
  } catch (error) {
    next(error);
  }
});

app.post("/api/collections", async (request, response, next) => {
  try {
    const body = createCollectionSchema.parse(request.body);
    response.status(201).json(await store.createKnowledgeBase(body.name));
  } catch (error) {
    next(error);
  }
});

app.delete("/api/collections/:id", async (request, response, next) => {
  try {
    await store.deleteKnowledgeBase(request.params.id);
    response.status(204).end();
  } catch (error) {
    next(error);
  }
});

app.post("/api/collections/:id/documents", async (request, response, next) => {
  try {
    const body = documentsSchema.parse(request.body);
    const startedAt = performance.now();
    const result = await store.upsertDocuments(request.params.id, body.documents);
    response.json({
      ...result,
      databaseMs: performance.now() - startedAt,
    });
  } catch (error) {
    next(error);
  }
});

app.post("/api/collections/:id/search", async (request, response, next) => {
  try {
    const body = searchSchema.parse(request.body);
    const startedAt = performance.now();
    const results = await store.search(
      request.params.id,
      body.query,
      body.queryEmbedding,
      body.limit,
    );
    response.json({
      results,
      databaseMs: performance.now() - startedAt,
      fusion: "seekdb DBMS_HYBRID_SEARCH + RRF",
    });
  } catch (error) {
    next(error);
  }
});

const distDirectory = path.join(projectRoot, "dist");
app.use(express.static(distDirectory));
app.get(/.*/, (_request, response) => {
  response.sendFile(path.join(distDirectory, "index.html"));
});

app.use(
  (
    error: unknown,
    _request: express.Request,
    response: express.Response,
    _next: express.NextFunction,
  ) => {
    if (error instanceof z.ZodError) {
      response.status(422).json({
        error: "请求参数无效",
        issues: error.issues,
      });
      return;
    }
    const message = error instanceof Error ? error.message : "服务器内部错误";
    response.status(500).json({ error: message });
  },
);

const server = app.listen(port, "0.0.0.0", () => {
  console.log(`Edge Course Lens running at http://127.0.0.1:${port}`);
  console.log(
    "host" in seekdbConfig
      ? `seekdb server: ${seekdbConfig.host}:${seekdbConfig.port}`
      : `seekdb embedded data: ${dataDirectory}`,
  );
});

async function shutdown(): Promise<void> {
  server.close();
  await store.close();
}

process.on("SIGINT", () => {
  void shutdown().then(() => process.exit(0));
});
process.on("SIGTERM", () => {
  void shutdown().then(() => process.exit(0));
});
