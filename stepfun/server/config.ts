import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { z } from "zod";

/**
 * Minimal .env loader (no extra dependency). Existing process.env values win,
 * so `PORT=9000 npm start` still overrides the file.
 */
function loadDotEnv(): void {
  const file = join(process.cwd(), ".env");
  if (!existsSync(file)) return;
  for (const rawLine of readFileSync(file, "utf8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (process.env[key] === undefined) process.env[key] = value;
  }
}

loadDotEnv();

const envSchema = z.object({
  NODE_ENV: z.enum(["development", "production", "test"]).default("development"),
  HOST: z.string().min(1).default("127.0.0.1"),
  PORT: z.coerce.number().int().min(1).max(65535).default(8787),

  /**
   * seekdb deployment mode:
   *   embedded - the database runs in-process (no daemon; needs the native binding)
   *   server   - connect to a local/remote seekdb or OceanBase instance over MySQL protocol
   *
   * Embedded is the default because it keeps everything on one machine. Server
   * mode exists for platforms where the embedded native binding is unavailable
   * (see README "Windows 说明").
   */
  SEEKDB_MODE: z.enum(["embedded", "server"]).default("embedded"),
  /** seekdb embedded database directory (created on first run). */
  SEEKDB_PATH: z.string().min(1).default("./data/seekdb"),
  SEEKDB_DATABASE: z.string().regex(/^[A-Za-z0-9_]+$/, "SEEKDB_DATABASE must be [A-Za-z0-9_]").default("mini_kb"),
  /** Server mode connection settings. */
  SEEKDB_HOST: z.string().default("127.0.0.1"),
  SEEKDB_PORT: z.coerce.number().int().min(1).max(65535).default(2881),
  SEEKDB_USER: z.string().default("root"),
  SEEKDB_PASSWORD: z.string().default(""),
  /** OceanBase only: tenant name. Leave empty for seekdb server. */
  SEEKDB_TENANT: z.string().optional(),
  /** One seekdb collection is created per knowledge base, named `${COLLECTION_PREFIX}${slug}`. */
  COLLECTION_PREFIX: z.string().regex(/^[A-Za-z0-9_]*$/, "COLLECTION_PREFIX must be [A-Za-z0-9_]").default("kb_"),
  DEFAULT_KB: z.string().regex(/^[a-z0-9][a-z0-9-]*$/, "DEFAULT_KB must be lower-kebab-case").default("default"),

  /** Must match the embedding model output size (bge-small-zh-v1.5 => 512). */
  EMBEDDING_DIM: z.coerce.number().int().min(8).max(4096).default(512),
  EMBEDDING_MODEL: z.string().min(1).default("Xenova/bge-small-zh-v1.5"),
  /** bge-zh models are asymmetric: queries get an instruction prefix. */
  QUERY_INSTRUCTION: z.string().default("为这个句子生成表示以用于检索相关文章："),

  /** Full-text analyzer for the seekdb fulltext index (ngram handles CJK). */
  FULLTEXT_ANALYZER: z.enum(["ngram", "ngram2", "ik", "space", "beng"]).default("ngram"),
  FULLTEXT_TOKEN_SIZE: z.coerce.number().int().min(1).max(8).default(2),

  CORS_ORIGIN: z.string().default("http://localhost:5173,http://127.0.0.1:5173"),
  LOG_LEVEL: z.enum(["debug", "info", "warn", "error"]).default("info"),

  MAX_DOCUMENTS_PER_REQUEST: z.coerce.number().int().min(1).max(2000).default(256),
  MAX_DOCUMENT_CHARS: z.coerce.number().int().min(100).max(100000).default(8000),
  /**
   * always   - refresh the vector index right after every write batch
   * deferred - refresh only when a search arrives after new writes
   * manual   - only on POST /api/refresh
   */
  REFRESH_MODE: z.enum(["always", "deferred", "manual"]).default("always"),
});

export type AppConfig = z.infer<typeof envSchema> & {
  corsOrigins: string[];
  dbPath: string;
};function build(): AppConfig {
  const parsed = envSchema.safeParse(process.env);
  if (!parsed.success) {
    const issues = parsed.error.issues.map((i) => `  - ${i.path.join(".") || "(root)"}: ${i.message}`).join("\n");
    throw new Error(`Invalid environment configuration:\n${issues}\nSee .env.example for the expected keys.`);
  }
  const env = parsed.data;
  return {
    ...env,
    corsOrigins: env.CORS_ORIGIN.split(",").map((s) => s.trim()).filter(Boolean),
    dbPath: env.SEEKDB_PATH,
  };
}

export const config: AppConfig = build();

/** Safe subset exposed to the browser (no paths beyond what the UI needs). */
export function publicConfig() {
  return {
    embeddingModel: config.EMBEDDING_MODEL,
    embeddingDim: config.EMBEDDING_DIM,
    queryInstruction: config.QUERY_INSTRUCTION,
    defaultKb: config.DEFAULT_KB,
    collectionPrefix: config.COLLECTION_PREFIX,
    database: config.SEEKDB_DATABASE,
    fulltextAnalyzer: config.FULLTEXT_ANALYZER,
    fulltextTokenSize: config.FULLTEXT_TOKEN_SIZE,
    refreshMode: config.REFRESH_MODE,
    maxDocumentsPerRequest: config.MAX_DOCUMENTS_PER_REQUEST,
    maxDocumentChars: config.MAX_DOCUMENT_CHARS,
    mode: config.SEEKDB_MODE,
  };
}
