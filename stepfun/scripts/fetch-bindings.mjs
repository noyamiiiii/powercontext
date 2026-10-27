/**
 * Pre-fetch the seekdb native bindings.
 *
 * `@seekdb/js-bindings` downloads a ~90 MB prebuilt binary from S3 on first use
 * via Node's fetch. Node's fetch does not honour http_proxy / https_proxy, so on
 * proxied networks (or slow links) the first query dies with "fetch failed".
 * This script downloads the very same archive with curl (proxy-aware, resumable)
 * into the exact cache location the loader expects, then lets the official
 * loader unzip it.
 *
 * Usage: node scripts/fetch-bindings.mjs
 */
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { download } from "./lib/download.mjs";

const require = createRequire(import.meta.url);
// The package exposes no "./download.js" export entry, so resolve the main
// entry and require its sibling by absolute path.
const mainEntry = require.resolve("@seekdb/js-bindings");
const loaderPath = join(dirname(mainEntry), "download.js");
const loader = require(loaderPath);

function resolveBaseUrl() {
  if (process.env.SEEKDB_BINDINGS_BASE_URL) return process.env.SEEKDB_BINDINGS_BASE_URL.replace(/\/$/, "");
  const src = readFileSync(loaderPath, "utf8");
  const match = src.match(/DEFAULT_BASE_URL\s*=\s*"([^"]+)"/);
  if (!match) throw new Error("Cannot determine SEEKDB_BINDINGS_BASE_URL from @seekdb/js-bindings");
  return match[1].replace(/\/$/, "");
}

/** Mirrors getCacheDir() in download.js, which is not exported. */
function resolveCacheDir(baseUrl, platform) {
  const base = process.env.SEEKDB_BINDINGS_CACHE_DIR || join(homedir(), ".seekdb", "bindings");
  const segments = new URL(baseUrl).pathname.split("/").filter(Boolean);
  const version = segments.length ? segments[segments.length - 1] : "unknown";
  return join(base, version, platform);
}

const platform = loader.getPlatformArch();
const baseUrl = resolveBaseUrl();
const cacheDir = resolveCacheDir(baseUrl, platform);
const zipName = `seekdb-js-bindings-${platform}.zip`;

console.log(`[fetch-bindings] platform: ${platform}`);
console.log(`[fetch-bindings] cache   : ${cacheDir}`);
console.log(`[fetch-bindings] source  : ${baseUrl}/${zipName}`);

download(`${baseUrl}/${zipName}`, join(cacheDir, zipName), { label: zipName, retries: 8 });

const ready = await loader.ensureBindingsDownloaded();
console.log(`[fetch-bindings] native bindings ready at ${ready}`);
