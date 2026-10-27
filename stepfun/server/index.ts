import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { join } from "node:path";
import cors from "cors";
import express, { type NextFunction, type Request, type Response } from "express";
import knowledgeController from "./controllers/knowledgeController";
import { config } from "./config";
import { connect, close as closeDb, connectionInfo } from "./db/seekdb";
import { errorHandler, notFoundHandler } from "./errors";
import { createLogger, logger } from "./logger";
import { knowledgeService } from "./services/knowledgeService";

const app = express();

app.disable("x-powered-by");
app.set("trust proxy", "loopback");

/**
 * Request scoped context: id for log correlation, child logger, and timing.
 * The id is echoed back in every response (and in error payloads) so a user
 * visible failure can be grepped straight out of the JSON logs.
 */
app.use((req: Request, res: Response, next: NextFunction) => {
  const requestId = (req.header("x-request-id") || randomUUID()).slice(0, 64);
  res.locals.requestId = requestId;
  res.setHeader("x-request-id", requestId);
  const requestLogger = createLogger({ requestId, method: req.method, path: req.path });
  res.locals.log = requestLogger;
  const start = performance.now();
  res.on("finish", () => {
    requestLogger.info("request completed", {
      status: res.statusCode,
      durationMs: Math.round((performance.now() - start) * 100) / 100,
    });
  });
  next();
});

// Baseline security headers (no extra dependency for a local-first app).
app.use((_req, res, next) => {
  res.setHeader("x-content-type-options", "nosniff");
  res.setHeader("referrer-policy", "no-referrer");
  res.setHeader("x-frame-options", "DENY");
  // The SPA is cross-origin isolated so onnxruntime-web can use
  // SharedArrayBuffer for multi-threaded WASM. API responses must stay
  // readable from that isolated page, hence CORP: cross-origin.
  res.setHeader("cross-origin-resource-policy", "cross-origin");
  res.setHeader("cross-origin-opener-policy", "same-origin");
  next();
});

app.use(
  cors({
    origin(origin, callback) {
      // Same-origin / curl requests carry no Origin header.
      if (!origin) return callback(null, true);
      if (config.corsOrigins.includes(origin)) return callback(null, true);
      if (config.NODE_ENV !== "production" && /^http:\/\/(localhost|127\.0\.0\.1):\d+$/.test(origin)) {
        return callback(null, true);
      }
      return callback(null, false);
    },
    methods: ["GET", "POST", "OPTIONS"],
    allowedHeaders: ["content-type", "x-request-id"],
    exposedHeaders: ["x-request-id"],
    maxAge: 600,
  }),
);

app.use(express.json({ limit: "32mb" }));

app.get("/api/health", (_req, res) => {
  res.json({ status: "ok", uptime: Math.round(process.uptime()), env: config.NODE_ENV });
});

/** Readiness proves the database (not just the process) can serve requests. */
app.get("/api/ready", async (_req, res) => {
  try {
    const kbStats = await knowledgeService.stats(config.DEFAULT_KB);
    res.json({ ready: true, db: connectionInfo(), defaultKb: kbStats });
  } catch (err) {
    logger.warn("readiness check failed", { err: err instanceof Error ? err.message : String(err) });
    res.status(503).json({ ready: false, db: connectionInfo() });
  }
});

app.use("/api", knowledgeController);

// Production: serve the built SPA from the same origin (no CORS, one command).
const webDist = join(process.cwd(), "dist", "web");
if (existsSync(webDist)) {
  app.use(express.static(webDist, { index: "index.html", maxAge: "1h" }));
  app.get("*", (req, res, next) => {
    if (req.path.startsWith("/api/")) return next();
    res.sendFile(join(webDist, "index.html"));
  });
}

app.use(notFoundHandler);
app.use(errorHandler);

async function main(): Promise<void> {
  logger.info("starting", {
    env: config.NODE_ENV,
    host: config.HOST,
    port: config.PORT,
    embeddingDim: config.EMBEDDING_DIM,
    embeddingModel: config.EMBEDDING_MODEL,
    refreshMode: config.REFRESH_MODE,
  });

  await connect();
  // Warm the default collection so the first user request is not the one that pays for DDL.
  await knowledgeService.stats(config.DEFAULT_KB);

  const server = app.listen(config.PORT, config.HOST, () => {
    logger.info("listening", {
      url: `http://${config.HOST}:${config.PORT}`,
      webDist: existsSync(webDist) ? webDist : "(dev mode: use vite on :5173)",
    });
  });

  let shuttingDown = false;
  const shutdown = async (signal: string) => {
    if (shuttingDown) return;
    shuttingDown = true;
    logger.info("shutdown initiated", { signal });
    server.close(async () => {
      await closeDb();
      logger.info("shutdown complete");
      process.exit(0);
    });
    // Hard stop if in-flight requests never drain.
    setTimeout(() => {
      logger.error("forced shutdown after timeout");
      process.exit(1);
    }, 10_000).unref();
  };

  process.on("SIGINT", () => void shutdown("SIGINT"));
  process.on("SIGTERM", () => void shutdown("SIGTERM"));
  process.on("unhandledRejection", (reason) => {
    logger.error("unhandled rejection", { err: reason instanceof Error ? reason.message : String(reason) });
  });
  process.on("uncaughtException", (err) => {
    logger.error("uncaught exception", { err: err.message, stack: err.stack?.split("\n")[1] });
    void shutdown("uncaughtException");
  });
}

main().catch((err) => {
  logger.error("failed to start", { err: err instanceof Error ? err.message : String(err) });
  process.exit(1);
});
