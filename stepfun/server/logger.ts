/**
 * Structured JSON logger.
 *
 * Every line is a single JSON object so logs can be shipped and queried, and
 * every request-scoped child carries the request id. Secrets are never logged.
 */
import { config } from "./config";

const LEVELS = { debug: 10, info: 20, warn: 30, error: 40 } as const;
export type LogLevel = keyof typeof LEVELS;
export type LogFields = Record<string, unknown>;

const REDACT_KEYS = /^(password|token|authorization|api_?key|secret|cookie)$/i;

function sanitize(fields: LogFields): LogFields {
  const out: LogFields = {};
  for (const [key, value] of Object.entries(fields)) {
    if (REDACT_KEYS.test(key)) {
      out[key] = "[redacted]";
      continue;
    }
    if (typeof value === "string" && value.length > 2000) {
      out[key] = `${value.slice(0, 2000)}…`;
      continue;
    }
    out[key] = value;
  }
  return out;
}

export interface Logger {
  debug(msg: string, fields?: LogFields): void;
  info(msg: string, fields?: LogFields): void;
  warn(msg: string, fields?: LogFields): void;
  error(msg: string, fields?: LogFields): void;
  child(fields: LogFields): Logger;
}

function emit(level: LogLevel, base: LogFields, msg: string, fields?: LogFields): void {
  if (LEVELS[level] < LEVELS[config.LOG_LEVEL]) return;
  const line = JSON.stringify({
    time: new Date().toISOString(),
    level,
    msg,
    ...sanitize(base),
    ...(fields ? sanitize(fields) : {}),
  });
  if (level === "error" || level === "warn") process.stderr.write(`${line}\n`);
  else process.stdout.write(`${line}\n`);
}

export function createLogger(base: LogFields = {}): Logger {
  return {
    debug: (msg, fields) => emit("debug", base, msg, fields),
    info: (msg, fields) => emit("info", base, msg, fields),
    warn: (msg, fields) => emit("warn", base, msg, fields),
    error: (msg, fields) => emit("error", base, msg, fields),
    child: (fields) => createLogger({ ...base, ...fields }),
  };
}

export const logger = createLogger({ service: "stepfun-mini-kb" });
