import type { NextFunction, Request, Response } from "express";
import { logger } from "./logger";

/**
 * Typed error hierarchy. Controllers/services throw these; the global handler
 * turns them into a stable JSON shape. Internal details (stack traces, SQL,
 * driver messages) never reach the client.
 */
export class AppError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status = 500,
    readonly details?: unknown,
  ) {
    super(message);
    this.name = new.target.name;
  }
}

export class ValidationError extends AppError {
  constructor(message: string, details?: unknown) {
    super("VALIDATION_ERROR", message, 400, details);
  }
}

export class NotFoundError extends AppError {
  constructor(message: string) {
    super("NOT_FOUND", message, 404);
  }
}

export class ConflictError extends AppError {
  constructor(message: string) {
    super("CONFLICT", message, 409);
  }
}

export class DatabaseError extends AppError {
  constructor(message: string, details?: unknown) {
    super("DATABASE_ERROR", message, 503, details);
  }
}

export class PayloadTooLargeError extends AppError {
  constructor(message: string) {
    super("PAYLOAD_TOO_LARGE", message, 413);
  }
}

interface DbLikeError {
  message?: string;
}

/** Normalise driver/SDK failures into DatabaseError without leaking internals. */
export function wrapDbError(err: unknown, operation: string): AppError {
  if (err instanceof AppError) return err;
  const message = (err as DbLikeError)?.message ?? String(err);
  logger.error("db operation failed", { operation, err: message });
  return new DatabaseError(`Database operation failed: ${operation}`);
}

export function notFoundHandler(req: Request, _res: Response, next: NextFunction): void {
  next(new NotFoundError(`Route not found: ${req.method} ${req.path}`));
}

export function errorHandler(err: unknown, req: Request, res: Response, _next: NextFunction): void {
  const requestId = (res.locals.requestId as string | undefined) ?? "unknown";
  const appError =
    err instanceof AppError
      ? err
      : new AppError("INTERNAL_ERROR", "Unexpected server error", 500);

  if (appError.status >= 500) {
    logger.error("request failed", {
      requestId,
      code: appError.code,
      status: appError.status,
      path: req.path,
      err: err instanceof Error ? err.message : String(err),
      stack: err instanceof Error ? err.stack?.split("\n").slice(0, 6).join(" | ") : undefined,
    });
  } else {
    logger.warn("request rejected", {
      requestId,
      code: appError.code,
      status: appError.status,
      path: req.path,
      message: appError.message,
    });
  }

  res.status(appError.status).json({
    error: {
      code: appError.code,
      message: appError.message,
      requestId,
      ...(appError.details !== undefined ? { details: appError.details } : {}),
    },
  });
}
