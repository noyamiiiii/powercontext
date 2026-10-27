/**
 * Reproducible benchmark harness (CLI).
 *
 * Two stages, independently runnable:
 *
 *   --stage embed   model load / document embedding throughput / query latency,
 *                   plus Recall@K / nDCG@10 / MRR computed by brute-force cosine
 *                   over the same vectors. No database involved, so it always
 *                   runs. (This is a measurement tool, not the app runtime.)
 *
 *   --stage db      the production path through the service layer:
 *                   ingest -> seekdb write -> refresh_index -> hybridSearch.
 *
 *   --stage all     both (default).
 *
 * Usage:
 *   npm run bench                          # embed + db, int8 then fp32
 *   npm run bench -- --stage embed
 *   npm run bench -- --dtype fp32 --dtype int8
 *
 * NOTE: these are CPU/Node numbers. Browser numbers (WebGPU FP16) come from the
 * in-app 评测面板, which runs on the device the user actually uses.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { env, pipeline, type FeatureExtractionPipeline } from "@huggingface/transformers";
import { EVAL_CASES, SAMPLE_DOCS } from "../shared/sampleCorpus";
import { config } from "../server/config";
import { logger } from "../server/logger";
import type { knowledgeService as KnowledgeServiceType } from "../server/services/knowledgeService";

type Service = typeof KnowledgeServiceType;

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");

env.allowLocalModels = true;
env.allowRemoteModels = false;
env.localModelPath = join(root, "public", "models");

const args = process.argv.slice(2);
const dtypesRequested: string[] = [];
let stage: "embed" | "db" | "all" = "all";
for (let i = 0; i < args.length; i += 1) {
  if (args[i] === "--dtype" && args[i + 1]) dtypesRequested.push(args[i + 1]);
  if (args[i] === "--stage" && args[i + 1]) stage = args[i + 1] as typeof stage;
}
const DTYPES = dtypesRequested.length ? dtypesRequested : ["int8", "fp32"];
const BATCH_SIZE = 8;
const TOP_K = 10;

const median = (values: number[]): number => {
  if (values.length === 0) return 0;
  const s = [...values].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 === 0 ? (s[mid - 1] + s[mid]) / 2 : s[mid];
};
const mean = (values: number[]): number => values.reduce((a, b) => a + b, 0) / Math.max(1, values.length);
/** Vectors are L2-normalised (normalize: true), so the dot product is the cosine. */
const dot = (a: number[], b: number[]): number => {
  let sum = 0;
  for (let i = 0; i < a.length; i += 1) sum += a[i] * b[i];
  return sum;
};

function ndcg(ranked: string[], relevant: string[], k: number): number {
  const rel = new Set(relevant);
  let dcg = 0;
  for (let i = 0; i < Math.min(k, ranked.length); i += 1) if (rel.has(ranked[i])) dcg += 1 / Math.log2(i + 2);
  let idcg = 0;
  for (let i = 0; i < Math.min(k, relevant.length); i += 1) idcg += 1 / Math.log2(i + 2);
  return idcg === 0 ? 0 : dcg / idcg;
}

function recall(ranked: string[], relevant: string[], k: number): number {
  const top = new Set(ranked.slice(0, k));
  return relevant.filter((id) => top.has(id)).length / Math.max(1, relevant.length);
}

interface Row {
  dtype: string;
  loadMs: number;
  docEmbedMs: number;
  docThroughput: number;
  writeMs: number | null;
  refreshMs: number | null;
  queryEmbedMedianMs: number;
  dbMedianMs: number | null;
  e2eMedianMs: number;
  recall5: number;
  recall10: number;
  ndcg10: number;
  mrr: number;
}

async function benchDtype(dtype: string, service: Service | null): Promise<Row> {
  const modelId = config.EMBEDDING_MODEL;
  const loadStart = performance.now();
  const extractor: FeatureExtractionPipeline = await (
    pipeline as unknown as (
      task: "feature-extraction",
      model: string,
      options: Record<string, unknown>,
    ) => Promise<FeatureExtractionPipeline>
  )("feature-extraction", modelId, { device: "cpu", dtype });
  // Warmup keeps graph optimisation / shader compilation out of the measurements.
  await extractor(["warmup"], { pooling: "cls", normalize: true });
  const loadMs = performance.now() - loadStart;

  // ---- document embedding (batched) ----
  const texts = SAMPLE_DOCS.map((doc) => doc.text);
  const embedStart = performance.now();
  const vectors: number[][] = [];
  for (let i = 0; i < texts.length; i += BATCH_SIZE) {
    const out = await extractor(texts.slice(i, i + BATCH_SIZE), { pooling: "cls", normalize: true });
    vectors.push(...(out.tolist() as number[][]));
  }
  const docEmbedMs = performance.now() - embedStart;

  // ---- write + index refresh through seekdb ----
  const kb = `bench-${dtype}`;
  let writeMs: number | null = null;
  let refreshMs: number | null = null;
  if (service) {
    const ingestResult = await service.ingest(
      kb,
      SAMPLE_DOCS.map((doc, i) => ({
        id: doc.id,
        text: doc.text,
        embedding: vectors[i],
        metadata: { title: doc.title, source: "sample" },
      })),
    );
    writeMs = ingestResult.timings.writeMs;
    refreshMs = ingestResult.timings.refreshMs;
  }

  // ---- query embedding + retrieval ----
  const queryEmbedTimes: number[] = [];
  const dbTimes: number[] = [];
  const e2eTimes: number[] = [];
  const r5: number[] = [];
  const r10: number[] = [];
  const ndcgs: number[] = [];
  const rrs: number[] = [];

  for (const testCase of EVAL_CASES) {
    const start = performance.now();
    const qOut = await extractor([config.QUERY_INSTRUCTION + testCase.query], { pooling: "cls", normalize: true });
    const queryVector = (qOut.tolist() as number[][])[0];
    const queryEmbedMs = performance.now() - start;

    let ids: string[];
    let dbMs: number | null = null;

    if (service) {
      const res = await service.search(kb, {
        queryEmbedding: queryVector,
        queryText: testCase.query,
        topK: TOP_K,
        mode: "hybrid",
      });
      ids = res.results.map((hit) => hit.id);
      dbMs = res.dbMs;
    } else {
      // Offline scoring only: rank the corpus by cosine to evaluate the model.
      ids = SAMPLE_DOCS.map((doc, i) => ({ id: doc.id, score: dot(queryVector, vectors[i]) }))
        .sort((a, b) => b.score - a.score)
        .slice(0, TOP_K)
        .map((entry) => entry.id);
    }

    const total = performance.now() - start;
    const rankIndex = ids.findIndex((id) => testCase.relevant.includes(id));

    queryEmbedTimes.push(queryEmbedMs);
    if (dbMs !== null) dbTimes.push(dbMs);
    e2eTimes.push(total);
    r5.push(recall(ids, testCase.relevant, 5));
    r10.push(recall(ids, testCase.relevant, 10));
    ndcgs.push(ndcg(ids, testCase.relevant, 10));
    rrs.push(rankIndex >= 0 ? 1 / (rankIndex + 1) : 0);
  }

  await extractor.dispose?.();

  return {
    dtype,
    loadMs,
    docEmbedMs,
    docThroughput: (SAMPLE_DOCS.length / docEmbedMs) * 1000,
    writeMs,
    refreshMs,
    queryEmbedMedianMs: median(queryEmbedTimes),
    dbMedianMs: dbTimes.length ? median(dbTimes) : null,
    e2eMedianMs: median(e2eTimes),
    recall5: mean(r5),
    recall10: mean(r10),
    ndcg10: mean(ndcgs),
    mrr: mean(rrs),
  };
}

async function main(): Promise<void> {
  console.log(`[bench] stage=${stage} model=${config.EMBEDDING_MODEL} dim=${config.EMBEDDING_DIM}`);
  console.log(`[bench] docs=${SAMPLE_DOCS.length} queries=${EVAL_CASES.length} batch=${BATCH_SIZE} topK=${TOP_K}`);
  console.log(`[bench] node=${process.version} platform=${process.platform}-${process.arch} dtype=${DTYPES.join(",")}`);

  let service: Service | null = null;
  let db: { dropCollection: (kb: string) => Promise<void>; close: () => Promise<void> } | null = null;

  if (stage !== "embed") {
    const svcModule = await import("../server/services/knowledgeService");
    const dbModule = await import("../server/db/seekdb");
    service = svcModule.knowledgeService;
    db = { dropCollection: dbModule.dropCollection, close: dbModule.close };
    await Promise.all(DTYPES.map((dtype) => dbModule.dropCollection(`bench-${dtype}`)));
    console.log(`[bench] seekdb mode=${config.SEEKDB_MODE}`);
  }

  const rows: Row[] = [];
  for (const dtype of DTYPES) {
    console.log(`\n[bench] running dtype=${dtype} …`);
    rows.push(await benchDtype(dtype, service));
  }

  const header = [
    "dtype",
    "load(ms)",
    "docEmb(ms)",
    "doc/s",
    "write(ms)",
    "refresh(ms)",
    "qEmb(ms)",
    "db(ms)",
    "e2e(ms)",
    "R@5",
    "R@10",
    "nDCG@10",
    "MRR",
  ];
  const num = (v: number | null, digits = 0) => (v === null ? "-" : v.toFixed(digits));
  const fmt = (row: Row) => [
    row.dtype,
    row.loadMs.toFixed(0),
    row.docEmbedMs.toFixed(0),
    row.docThroughput.toFixed(1),
    num(row.writeMs),
    num(row.refreshMs),
    row.queryEmbedMedianMs.toFixed(1),
    num(row.dbMedianMs, 2),
    row.e2eMedianMs.toFixed(0),
    `${(row.recall5 * 100).toFixed(1)}%`,
    `${(row.recall10 * 100).toFixed(1)}%`,
    row.ndcg10.toFixed(3),
    row.mrr.toFixed(3),
  ];

  const table = [header, ...rows.map(fmt)];
  const widths = header.map((_, i) => Math.max(...table.map((r) => r[i].length)));
  console.log(`\n${table.map((r) => r.map((c, i) => c.padEnd(widths[i])).join("  ")).join("\n")}`);

  const outDir = join(root, "benchmark");
  mkdirSync(outDir, { recursive: true });
  const file = join(outDir, `bench-${stage}-${new Date().toISOString().replace(/[:.]/g, "-")}.json`);
  writeFileSync(
    file,
    `${JSON.stringify(
      {
        stage,
        model: config.EMBEDDING_MODEL,
        dim: config.EMBEDDING_DIM,
        node: process.version,
        platform: `${process.platform}-${process.arch}`,
        batchSize: BATCH_SIZE,
        topK: TOP_K,
        refreshMode: config.REFRESH_MODE,
        docs: SAMPLE_DOCS.length,
        queries: EVAL_CASES.length,
        rows,
      },
      null,
      2,
    )}\n`,
  );
  console.log(`\n[bench] wrote ${file}`);

  if (db) {
    await Promise.all(DTYPES.map((dtype) => db!.dropCollection(`bench-${dtype}`)));
    await db.close();
  }
}

main().catch((err) => {
  logger.error("bench failed", { err: err instanceof Error ? err.message : String(err) });
  process.exit(1);
});
