import { Router, type NextFunction, type Request, type Response } from "express";
import { z } from "zod";
import { publicConfig } from "../config";
import { ValidationError } from "../errors";
import { knowledgeService } from "../services/knowledgeService";

/**
 * Controller layer: HTTP in, HTTP out.
 * Parsing and validation happen here; every decision lives in the service.
 */

const router = Router();

/** Wraps async handlers so rejected promises reach the global error handler. */
function handle(fn: (req: Request, res: Response) => Promise<void>) {
  return (req: Request, res: Response, next: NextFunction) => {
    fn(req, res).catch(next);
  };
}

function parseBody<T extends z.ZodTypeAny>(schema: T, body: unknown): z.infer<T> {
  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    throw new ValidationError(
      "Request body validation failed",
      parsed.error.issues.map((issue) => ({
        path: issue.path.join("."),
        message: issue.message,
      })),
    );
  }
  return parsed.data;
}

const kbParam = z.object({
  kb: z.string().regex(/^[a-z0-9][a-z0-9-]{0,47}$/, "kb must be 1-48 chars of lower-case letters, digits or dashes"),
});

const createKbSchema = z.object({
  name: z.string().regex(/^[a-z0-9][a-z0-9-]{0,47}$/),
});

const ingestSchema = z.object({
  mode: z.enum(["add", "upsert"]).optional(),
  documents: z
    .array(
      z.object({
        id: z.string().min(1).max(200),
        text: z.string().min(1),
        embedding: z.array(z.number()),
        metadata: z.record(z.union([z.string(), z.number(), z.boolean(), z.null()])).optional(),
      }),
    )
    .min(1),
});

const searchSchema = z.object({
  queryEmbedding: z.array(z.number()),
  queryText: z.string().max(2000).optional(),
  topK: z.number().int().min(1).max(100).default(10),
  mode: z.enum(["hybrid", "vector", "fulltext"]).default("hybrid"),
});

/** Static configuration the browser needs before it can embed anything. */
router.get("/meta", handle(async (_req, res) => {
  const kb = publicConfig().defaultKb;
  const stats = await knowledgeService.stats(kb);
  res.json({ config: publicConfig(), defaultKbStats: stats });
}));

router.get("/kbs", handle(async (_req, res) => {
  res.json(await knowledgeService.overview());
}));

router.post("/kbs", handle(async (req, res) => {
  const { name } = parseBody(createKbSchema, req.body);
  res.status(201).json(await knowledgeService.stats(name));
}));

router.get("/kbs/:kb/stats", handle(async (req, res) => {
  const { kb } = kbParam.parse(req.params);
  res.json(await knowledgeService.stats(kb));
}));

router.post("/kbs/:kb/reset", handle(async (req, res) => {
  const { kb } = kbParam.parse(req.params);
  res.json(await knowledgeService.reset(kb));
}));

router.get("/kbs/:kb/documents", handle(async (req, res) => {
  const { kb } = kbParam.parse(req.params);
  const limit = Number.parseInt(String(req.query.limit ?? "20"), 10);
  res.json({ kb, documents: await knowledgeService.preview(kb, Number.isFinite(limit) ? limit : 20) });
}));

router.post("/kbs/:kb/documents", handle(async (req, res) => {
  const { kb } = kbParam.parse(req.params);
  const body = parseBody(ingestSchema, req.body);
  const result = await knowledgeService.ingest(kb, body.documents, { mode: body.mode });
  res.status(201).json(result);
}));

router.post("/kbs/:kb/search", handle(async (req, res) => {
  const { kb } = kbParam.parse(req.params);
  const body = parseBody(searchSchema, req.body);
  res.json(await knowledgeService.search(kb, body));
}));

router.post("/kbs/:kb/refresh", handle(async (req, res) => {
  const { kb } = kbParam.parse(req.params);
  res.json(await knowledgeService.refresh(kb));
}));

export default router;
