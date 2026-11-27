import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "vite";

function readJson(path: string) {
  return existsSync(path) ? JSON.parse(readFileSync(path, "utf-8")) : undefined;
}

const stage = resolve(process.cwd(), "public");
const active = readJson(resolve(stage, "active.json"));
const manifest = typeof active?.release_id === "string" && /^[a-f0-9]{24}$/.test(active.release_id) ?
  readJson(resolve(stage, "releases", active.release_id, "manifest.json")) : undefined;
const base = process.env.PAGES_BASE || "/EUPolicyEO/";
if (!/^\/(?:[\w.-]+\/)*$/.test(base) || base.split("/").some(part => part === ".." || part === ".")) {
  throw new Error("PAGES_BASE must be a same-origin path with leading and trailing slashes");
}

export default defineConfig({
  base,
  define: {
    __DENSE_ENABLED__: JSON.stringify(!!manifest?.dense),
  },
  plugins: [{
    name: "project-license",
    apply: "build",
    generateBundle() {
      this.emitFile({
        type: "asset",
        fileName: "licenses/EUPolicyEO-MIT.txt",
        source: readFileSync(new URL("../LICENSE", import.meta.url)),
      });
    },
  }],
  worker: { format: "es" },
});
