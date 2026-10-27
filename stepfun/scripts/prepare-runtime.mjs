/**
 * Copy the ONNX Runtime Web runtime files into `public/ort/` so the browser
 * never has to fetch them from a CDN.
 *
 * Without this, transformers.js points `wasmPaths` at jsdelivr, which breaks
 * offline demos and the "no network at inference time" property the task asks
 * for. Runs automatically through `npm run setup`.
 */
import { createRequire } from "node:module";
import { copyFileSync, existsSync, mkdirSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = join(root, "public", "ort");

/** onnxruntime-web does not export ./package.json, so locate dist/ by walking. */
function findOrtDist() {
  const entry = require.resolve("onnxruntime-web");
  const candidates = [dirname(entry), dirname(dirname(entry))];
  for (const dir of candidates) {
    if (!existsSync(dir)) continue;
    if (readdirSync(dir).some((f) => /^ort-wasm.*\.wasm$/.test(f))) return dir;
  }
  throw new Error(`Could not locate onnxruntime-web dist directory (entry: ${entry})`);
}

const ortDist = findOrtDist();
mkdirSync(outDir, { recursive: true });

const wanted = readdirSync(ortDist).filter((f) => /^ort-wasm.*\.(wasm|mjs)$/.test(f));
if (wanted.length === 0) throw new Error(`No ORT wasm artifacts found in ${ortDist}`);

let total = 0;
for (const file of wanted) {
  copyFileSync(join(ortDist, file), join(outDir, file));
  total += statSync(join(ortDist, file)).size;
}

console.log(
  `[prepare-runtime] copied ${wanted.length} ONNX Runtime Web files to public/ort (${(total / 1024 ** 2).toFixed(1)} MB)`,
);
for (const file of wanted) console.log(`  - ${file}`);
