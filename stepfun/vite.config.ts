import { createReadStream, existsSync, statSync } from "node:fs";
import { join, normalize, resolve, sep } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

/**
 * Serve the ONNX Runtime Web runtime straight from `public/ort`.
 *
 * Without this, a request for `ort-wasm-simd-threaded.jsep.mjs?import` is picked
 * up by Vite's module-transform pipeline, which answers 500 and makes the
 * dynamic `import()` inside onnxruntime-web fail ("Failed to fetch dynamically
 * imported module"). Registering the handler from `configureServer` puts it in
 * front of those internal middlewares, so the file is streamed verbatim with
 * the correct content type.
 */
function ortRuntimePlugin(): Plugin {
  const dir = join(process.cwd(), "public", "ort");

  const serve = (req: { url?: string }, res: import("node:http").ServerResponse, next: () => void) => {
    const url = req.url ?? "";
    if (!url.startsWith("/ort/")) return next();
    const relative = decodeURIComponent(url.split("?")[0].slice("/ort/".length));
    const file = normalize(join(dir, relative));
    // Path traversal guard: the resolved file must stay inside `dir`.
    if (!file.startsWith(dir + sep) || !existsSync(file) || !statSync(file).isFile()) return next();

    res.setHeader(
      "content-type",
      file.endsWith(".wasm") ? "application/wasm" : "text/javascript; charset=utf-8",
    );
    res.setHeader("cross-origin-resource-policy", "cross-origin");
    res.setHeader("cache-control", "no-cache");
    createReadStream(file).pipe(res);
  };

  return {
    name: "serve-ort-runtime",
    configureServer(server) {
      server.middlewares.use(serve);
    },
    configurePreviewServer(server) {
      server.middlewares.use(serve);
    },
  };
}

/**
 * Vite root is `web/`; the heavy static assets (ONNX model + ORT wasm) live in
 * the repo-level `public/` so `npm run setup` can populate them once.
 *
 * COOP/COEP are enabled so SharedArrayBuffer exists and onnxruntime-web can run
 * multi-threaded WASM. In production the same headers are set by Express.
 */
export default defineConfig({
  root: "web",
  publicDir: "../public",
  plugins: [react(), ortRuntimePlugin()],
  build: {
    outDir: "../dist/web",
    emptyOutDir: true,
    target: "es2022",
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      // Two entry pages: the app (`index.html`) and the inference-only
      // benchmark (`bench.html`) that produces the tables in BENCHMARK.md.
      input: {
        main: resolve(process.cwd(), "web/index.html"),
        bench: resolve(process.cwd(), "web/bench.html"),
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    headers: {
      "Cross-Origin-Opener-Policy": "same-origin",
      "Cross-Origin-Embedder-Policy": "require-corp",
    },
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8787",
        changeOrigin: false,
      },
    },
    fs: {
      // `public/` sits one level above the vite root.
      allow: [".."],
    },
  },
  // transformers.js ships pre-bundled ESM + worker glue; let esbuild leave it alone.
  optimizeDeps: {
    exclude: ["@huggingface/transformers"],
  },
  worker: {
    format: "es",
  },
});
