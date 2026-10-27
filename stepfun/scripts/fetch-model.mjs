/**
 * Fetch the ONNX embedding model used for browser-side inference.
 *
 * The app ships no model weights in git (98 MB total would bloat the repo).
 * This script downloads them once into `public/models/<modelId>/`, after which
 * the whole pipeline runs fully offline: inference happens in the browser and
 * the weights are served from the local static directory.
 *
 * Usage:
 *   node scripts/fetch-model.mjs                 # fp32 baseline + fp16 + int8
 *   node scripts/fetch-model.mjs --dtype int8    # only what WASM needs
 *
 * Env:
 *   MODEL_ID            default Xenova/bge-small-zh-v1.5
 *   HF_ENDPOINT         default https://huggingface.co (use https://hf-mirror.com in CN)
 *   MODEL_DTYPES        comma separated, default fp32,fp16,int8
 */
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { download, formatBytes } from "./lib/download.mjs";

const MODEL_ID = process.env.MODEL_ID || "Xenova/bge-small-zh-v1.5";
const HF_ENDPOINT = (process.env.HF_ENDPOINT || "https://huggingface.co").replace(/\/$/, "");
const DTYPES = (process.env.MODEL_DTYPES || "fp32,fp16,int8")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

const dtypeToFile = {
  fp32: "onnx/model.onnx",
  fp16: "onnx/model_fp16.onnx",
  int8: "onnx/model_int8.onnx",
  q8: "onnx/model_quantized.onnx",
  uint8: "onnx/model_uint8.onnx",
  q4: "onnx/model_q4.onnx",
};

const SHARED_FILES = ["config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"];

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = join(root, "public", "models", MODEL_ID);

console.log(`[fetch-model] model   : ${MODEL_ID}`);
console.log(`[fetch-model] endpoint: ${HF_ENDPOINT}`);
console.log(`[fetch-model] target  : ${outDir}`);
console.log(`[fetch-model] dtypes  : ${DTYPES.join(", ")}`);

mkdirSync(outDir, { recursive: true });

const results = [];
for (const file of [...SHARED_FILES, ...DTYPES.map((d) => dtypeToFile[d]).filter(Boolean)]) {
  const url = `${HF_ENDPOINT}/${MODEL_ID}/resolve/main/${file}`;
  const dest = join(outDir, file);
  try {
    const r = download(url, dest, { label: file });
    results.push({ file, bytes: r.bytes });
  } catch (err) {
    console.warn(`  ! ${file}: ${err.message}`);
    if (!file.startsWith("onnx/")) throw err;
  }
}

// Record sizes so BENCHMARK.md numbers can be re-derived without re-downloading.
const manifest = {
  modelId: MODEL_ID,
  endpoint: HF_ENDPOINT,
  files: results.map((r) => ({ file: r.file, bytes: r.bytes, human: formatBytes(r.bytes) })),
  onnx: Object.fromEntries(
    results
      .filter((r) => r.file.startsWith("onnx/"))
      .map((r) => [r.file, { bytes: r.bytes, human: formatBytes(r.bytes) }]),
  ),
  generatedAt: new Date().toISOString(),
};
writeFileSync(join(outDir, "model-manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);

const baseline = results.find((r) => r.file === "onnx/model.onnx")?.bytes;
console.log("\n[fetch-model] model size report");
for (const r of results.filter((x) => x.file.startsWith("onnx/"))) {
  const ratio = baseline ? ` compression ${(baseline / r.bytes).toFixed(2)}x` : "";
  console.log(`  ${r.file.padEnd(24)} ${formatBytes(r.bytes).padStart(9)}${ratio}`);
}
if (!existsSync(join(outDir, "onnx", "model.onnx")) && DTYPES.includes("fp32") === false) {
  console.log("  (fp32 baseline not downloaded: quality comparison will use the default dtype)");
}
console.log("[fetch-model] done");
