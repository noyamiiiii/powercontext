/**
 * Resumable download helper.
 *
 * Node's built-in fetch ignores http_proxy / https_proxy, which breaks downloads
 * behind a corporate or local proxy (common in CN networks). curl honours those
 * env vars, so we prefer curl and fall back to fetch when it is unavailable.
 */
import { spawnSync } from "node:child_process";
import { createWriteStream, existsSync, mkdirSync, renameSync, statSync, unlinkSync } from "node:fs";
import { dirname } from "node:path";

function hasCurl() {
  const res = spawnSync("curl", ["--version"], { encoding: "utf8" });
  return res.status === 0;
}

function remoteSize(url) {
  const res = spawnSync("curl", ["-sSIL", "--max-time", "30", url], { encoding: "utf8" });
  if (res.status !== 0 || !res.stdout) return null;
  const matches = [...res.stdout.matchAll(/^content-length:\s*(\d+)/gim)];
  if (!matches.length) return null;
  return Number(matches[matches.length - 1][1]);
}

export function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return "n/a";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

async function fetchToFile(url, dest) {
  const res = await fetch(url, { redirect: "follow" });
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
  const tmp = `${dest}.part`;
  mkdirSync(dirname(dest), { recursive: true });
  await new Promise((resolve, reject) => {
    const stream = createWriteStream(tmp);
    res.body.pipeTo(new WritableStream({
      write(chunk) {
        stream.write(Buffer.from(chunk));
      },
      close() {
        stream.end(resolve);
      },
      abort(err) {
        stream.destroy();
        reject(err);
      },
    })).catch(reject);
  });
  renameSync(tmp, dest);
}

/**
 * Download `url` to `dest`, resuming a partial file when possible.
 * Returns { path, bytes, skipped }.
 */
export function download(url, dest, { label = "", retries = 6, log = console.log } = {}) {
  mkdirSync(dirname(dest), { recursive: true });
  const total = hasCurl() ? remoteSize(url) : null;

  if (existsSync(dest)) {
    const have = statSync(dest).size;
    if (total === null ? have > 0 : have === total) {
      log(`  = ${label || dest} already present (${formatBytes(have)})`);
      return { path: dest, bytes: have, skipped: true };
    }
    if (total !== null && have > total) {
      unlinkSync(dest);
    }
  }

  if (!hasCurl()) {
    log(`  > ${label || dest} via fetch (no curl found)`);
    return fetchToFile(url, dest).then(() => ({
      path: dest,
      bytes: statSync(dest).size,
      skipped: false,
    }));
  }

  for (let attempt = 1; attempt <= retries; attempt += 1) {
    const have = existsSync(dest) ? statSync(dest).size : 0;
    if (total !== null && have >= total) break;
    log(`  > ${label || dest} attempt ${attempt}/${retries}, have ${formatBytes(have)}${total ? ` / ${formatBytes(total)}` : ""}`);
    const res = spawnSync(
      "curl",
      ["-sS", "-L", "-C", "-", "--retry", "3", "--retry-delay", "2", "--connect-timeout", "30", "-o", dest, url],
      { encoding: "utf8", stdio: "inherit" },
    );
    if (res.status === 0) {
      const now = existsSync(dest) ? statSync(dest).size : 0;
      if (total === null || now >= total) break;
    }
  }

  const finalBytes = existsSync(dest) ? statSync(dest).size : 0;
  if (total !== null && finalBytes !== total) {
    throw new Error(`Incomplete download for ${url}: ${finalBytes}/${total} bytes`);
  }
  log(`  ✓ ${label || dest} ${formatBytes(finalBytes)}`);
  return { path: dest, bytes: finalBytes, skipped: false };
}
