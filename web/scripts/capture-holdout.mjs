import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { parseArgs } from "node:util";
import { chromium } from "playwright";

const { values } = parseArgs({
  options: {
    url: { type: "string", default: "http://127.0.0.1:4173/EUPolicyEO/" },
    release: { type: "string", default: "artifacts/coverage-release/pages" },
    output: { type: "string", default: "artifacts/coverage-evaluation/rankings.json" },
    questions: { type: "string" },
    hybrid: { type: "boolean", default: false },
  },
});
const url = new URL(values.url);
if (url.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(url.hostname) ||
    url.username || url.password || url.search || url.hash || !url.pathname.endsWith("/")) {
  throw new Error("Provide a loopback HTTP preview URL ending in a slash.");
}

const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");
const questions = await readFile(values.questions ?? new URL("../../eval/holdout_queries.json", import.meta.url));
const config = JSON.parse(questions);
const manifest = await readFile(`${values.release}/manifest.json`);
const release = JSON.parse(manifest);
if (config.top_k !== 5 || !["bm25", "dense"].every(mode => release.rankers.includes(mode))) {
  throw new Error("The frozen protocol requires five slots per ranker and a dual-ranker release.");
}
const expected = { releaseId: release.release_id, manifestSha256: hash(manifest) };

const browser = await chromium.launch({ channel: process.env.E2E_CHANNEL ?? "msedge" });
try {
  const page = await browser.newPage();
  await page.route("**/*", route => {
    if (new URL(route.request().url()).origin === url.origin) return route.continue();
    return route.abort("blockedbyclient");
  });
  await page.goto(url.href);
  const { results, runtime } = await page.evaluate(async ({ expected, queries, topK, hybrid }) => {
    async function read(path, format) {
      const target = new URL(path, location.href);
      if (target.origin !== location.origin) throw new Error("Unexpected asset origin");
      const response = await fetch(target);
      if (!response.ok) throw new Error(`${target.pathname} returned HTTP ${response.status}`);
      return response[format]();
    }

    const active = await read("active.json", "json");
    if (active.release_id !== expected.releaseId || active.manifest_sha256 !== expected.manifestSha256) {
      throw new Error("The preview does not serve the requested exported release.");
    }
    const entry = document.querySelector('script[type="module"][src]');
    if (!entry) throw new Error("The production entry module is missing.");
    const main = await read(entry.src, "text");
    const workerMatch = main.match(/([^"'\s]*search\.worker-[A-Za-z0-9_-]+\.js)/);
    if (!workerMatch) throw new Error("Run the production build before capturing holdout searches.");
    const workerUrl = new URL(workerMatch[1], location.href);
    if (workerUrl.origin !== location.origin) throw new Error("Unexpected worker origin.");
    const workerCode = await read(workerUrl, "arrayBuffer");
    const sha256 = async (bytes) => Array.from(
      new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
      byte => byte.toString(16).padStart(2, "0"),
    ).join("");
    const runtime = {
      entry_path: new URL(entry.src).pathname,
      entry_sha256: await sha256(new TextEncoder().encode(main)),
      worker_path: workerUrl.pathname,
      worker_sha256: await sha256(workerCode),
    };
    const worker = new Worker(workerUrl, { type: "module" });
    let id = 0;
    async function search(question, mode) {
      const payload = {
        id: ++id, releaseId: active.release_id, mode, query: question.query,
        constraints: question.filters ?? {},
      };
      return new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error(`Search timed out for ${question.id}.`)), 45_000);
        worker.onmessage = ({ data }) => {
          if (data.id !== payload.id) return;
          clearTimeout(timeout);
          if (data.error) return reject(new Error(data.error));
          resolve(data[question.corpus].slice(0, topK).map(({ doc, score, compatibility }) =>
            ({ id: doc.id, score, compatibility })));
        };
        worker.onerror = e => {
          clearTimeout(timeout);
          reject(new Error(e.message || "The search worker failed."));
        };
        worker.postMessage(payload);
      });
    }
    try {
      const output = [];
      for (const question of queries) {
        const result = {
          query_id: question.id,
          bm25: await search(question, "bm25"),
          dense: await search(question, "dense"),
        };
        if (hybrid) result.hybrid = await search(question, "hybrid");
        output.push(result);
      }
      return { results: output, runtime };
    } finally {
      worker.terminate();
    }
  }, { expected, queries: config.queries, topK: config.top_k, hybrid: values.hybrid });
  await mkdir(dirname(values.output), { recursive: true });
  await writeFile(values.output, JSON.stringify({
    protocol_id: config.id,
    query_sha256: hash(questions),
    release_id: expected.releaseId,
    manifest_sha256: expected.manifestSha256,
    browser_version: browser.version(),
    runtime,
    captured_at: new Date().toISOString(),
    top_k: config.top_k,
    results,
  }, null, 2) + "\n", { flag: "wx" });
  console.log(`Captured ${results.length} holdout questions from release ${expected.releaseId}.`);
} finally {
  await browser.close();
}
