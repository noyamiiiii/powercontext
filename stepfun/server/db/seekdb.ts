import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import {
  FulltextIndexConfig,
  Schema,
  SeekdbAdminClient,
  SeekdbClient,
  VectorIndexConfig,
  type Collection,
} from "seekdb";
import { config } from "../config";
import { DatabaseError, ValidationError, wrapDbError } from "../errors";
import { logger } from "../logger";

/**
 * seekdb access layer.
 *
 * The app uses seekdb in **embedded** mode: the database runs in-process inside
 * the Node server, no separate daemon to deploy. Vectors arrive already
 * computed by the browser, so every collection is configured with
 * `embeddingFunction: null` -- seekdb must never re-embed anything server side,
 * otherwise the "inference happens on the user device" rule would break.
 *
 * Two indexes are created on the same collection:
 *   - HNSW dense vector index (cosine) for semantic recall
 *   - fulltext index (ngram, CJK friendly) for keyword recall
 * That is what lets a single `hybridSearch()` call do RRF fusion inside the
 * database instead of gluing two result lists together in application code.
 */

let client: SeekdbClient | null = null;
const collections = new Map<string, Collection>();
let dbPath = "";

const KB_SLUG = /^[a-z0-9][a-z0-9-]{0,47}$/;

export function assertKbSlug(kb: string): string {
  if (!KB_SLUG.test(kb)) {
    throw new ValidationError(
      "Knowledge base name must be 1-48 chars of lower-case letters, digits or dashes",
    );
  }
  return kb;
}

export function collectionNameFor(kb: string): string {
  return `${config.COLLECTION_PREFIX}${assertKbSlug(kb).replace(/-/g, "_")}`;
}

function isAlreadyExists(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return /exist/i.test(msg) && !/not exist/i.test(msg);
}

async function ensureDatabase(path: string): Promise<void> {
  const admin = new SeekdbAdminClient({ path });
  try {
    await admin.createDatabase(config.SEEKDB_DATABASE);
    logger.info("seekdb database created", { database: config.SEEKDB_DATABASE });
  } catch (err) {
    if (isAlreadyExists(err)) {
      logger.debug("seekdb database already exists", { database: config.SEEKDB_DATABASE });
    } else {
      throw wrapDbError(err, "createDatabase");
    }
  } finally {
    await admin.close().catch(() => undefined);
  }
}

export function buildSchema(): Schema {
  return new Schema({
    vectorIndex: new VectorIndexConfig({
      hnsw: {
        dimension: config.EMBEDDING_DIM,
        distance: "cosine",
        type: "hnsw",
        m: 16,
        ef_construction: 200,
      },
      // Vectors are produced in the browser; disabling the SDK embedding
      // function makes that guarantee explicit and avoids a server-side model.
      embeddingFunction: null,
    }),
    fulltextIndex: new FulltextIndexConfig(config.FULLTEXT_ANALYZER, {
      ngram_token_size: config.FULLTEXT_TOKEN_SIZE,
    }),
  });
}

export async function connect(): Promise<SeekdbClient> {
  if (client) return client;

  if (config.SEEKDB_MODE === "server") {
    const next = new SeekdbClient({
      host: config.SEEKDB_HOST,
      port: config.SEEKDB_PORT,
      user: config.SEEKDB_USER,
      password: config.SEEKDB_PASSWORD,
      database: config.SEEKDB_DATABASE,
      ...(config.SEEKDB_TENANT ? { tenant: config.SEEKDB_TENANT } : {}),
    });
    client = next;
    logger.info("seekdb connected", {
      mode: "server",
      host: config.SEEKDB_HOST,
      port: config.SEEKDB_PORT,
      database: config.SEEKDB_DATABASE,
      tenant: config.SEEKDB_TENANT,
    });
    return next;
  }

  dbPath = resolve(process.cwd(), config.SEEKDB_PATH);
  mkdirSync(dbPath, { recursive: true });

  await ensureDatabase(dbPath);

  const next = new SeekdbClient({ path: dbPath, database: config.SEEKDB_DATABASE });
  client = next;
  logger.info("seekdb connected", {
    mode: "embedded",
    path: dbPath,
    database: config.SEEKDB_DATABASE,
    isConnected: next.isConnected(),
  });
  return next;
}

export async function getCollection(kb: string): Promise<Collection> {
  const name = collectionNameFor(kb);
  const cached = collections.get(name);
  if (cached) return cached;

  const c = await connect();
  try {
    const created = await c.getOrCreateCollection({
      name,
      schema: buildSchema(),
      embeddingFunction: null,
    });
    collections.set(name, created);
    logger.info("collection ready", {
      collection: created.name,
      dimension: created.dimension,
      distance: created.distance,
      fulltextAnalyzer: config.FULLTEXT_ANALYZER,
    });
    return created;
  } catch (err) {
    throw wrapDbError(err, "getOrCreateCollection");
  }
}

export async function listCollections(): Promise<{ name: string; kb: string; count: number }[]> {
  const c = await connect();
  const names = await c.listCollections().catch((err) => {
    throw wrapDbError(err, "listCollections");
  });
  const prefix = config.COLLECTION_PREFIX;
  const rows: { name: string; kb: string; count: number }[] = [];
  for (const entry of names as unknown[]) {
    const name = typeof entry === "string" ? entry : (entry as { name?: string }).name;
    if (!name || !name.startsWith(prefix)) continue;
    const kb = name.slice(prefix.length).replace(/_/g, "-");
    let count = 0;
    try {
      count = await (await getCollection(kb)).count();
    } catch {
      count = -1;
    }
    rows.push({ name, kb, count });
  }
  return rows.sort((a, b) => a.kb.localeCompare(b.kb));
}

export async function dropCollection(kb: string): Promise<void> {
  const name = collectionNameFor(kb);
  const c = await connect();
  collections.delete(name);
  try {
    await c.deleteCollection(name);
    logger.info("collection dropped", { collection: name });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    if (!/not exist|no such/i.test(message)) throw wrapDbError(err, "deleteCollection");
  }
}

export async function close(): Promise<void> {
  const c = client;
  client = null;
  collections.clear();
  if (!c) return;
  try {
    await c.close();
    logger.info("seekdb closed");
  } catch (err) {
    logger.warn("seekdb close failed", { err: err instanceof Error ? err.message : String(err) });
  }
}

export function connectionInfo() {
  return {
    mode: config.SEEKDB_MODE,
    path: dbPath,
    host: config.SEEKDB_MODE === "server" ? `${config.SEEKDB_HOST}:${config.SEEKDB_PORT}` : undefined,
    database: config.SEEKDB_DATABASE,
    connected: client?.isConnected() ?? false,
    collections: collections.size,
  };
}

export function requireConnected(): void {
  if (!client?.isConnected()) {
    throw new DatabaseError("Database is not connected");
  }
}
