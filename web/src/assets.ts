import type { Corpus, Document, LexicalIndex, Manifest } from "./types";
import { FREE_TEXT_POLICIES } from "./ranking";

const SHA = /^[a-f0-9]{64}$/;
const ID = /^[a-f0-9]{24}$/;
const TOKENIZER = "nfkc-lower-unicode-alnum-v1";
const BASE = new URL(import.meta.env.BASE_URL, globalThis.location?.origin ?? "http://localhost");
const MAX_BYTES = 150 * 1024 ** 2;
const SAFE_ASSET = /^(?:[a-zA-Z0-9_.-]+\/)*[a-zA-Z0-9_.-]+$/;

function safeAsset(path: string) {
  return SAFE_ASSET.test(path) && !path.split("/").some(part => part === "." || part === "..");
}

async function sha256(data: ArrayBuffer) {
  const value = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(value), byte => byte.toString(16).padStart(2, "0")).join("");
}

async function get(url: URL): Promise<ArrayBuffer> {
  if (url.origin !== BASE.origin) throw new Error("Asset URL is outside this site");
  const response = await fetch(url, { redirect: "error", credentials: "same-origin" });
  if (!response.ok) throw new Error(`Could not load ${url.pathname} (HTTP ${response.status})`);
  return response.arrayBuffer();
}

function parse<T>(data: ArrayBuffer): T {
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(data)) as T;
}

export class Release {
  constructor(readonly root: URL, readonly manifest: Manifest) {}

  static async open() {
    const pointer = parse<{release_id: string; manifest_sha256: string}>(
      await get(new URL("active.json", BASE)),
    );
    if (!ID.test(pointer.release_id) || !SHA.test(pointer.manifest_sha256)) throw new Error("Invalid release pointer");
    const root = new URL(`releases/${pointer.release_id}/`, BASE);
    const data = await get(new URL("manifest.json", root));
    if (await sha256(data) !== pointer.manifest_sha256) throw new Error("Manifest integrity check failed");
    const manifest = parse<Manifest>(data);
    if (manifest.schema_version !== 1 || manifest.release_id !== pointer.release_id ||
        !ID.test(manifest.parent_snapshot_id) || !/^\d+$/.test(manifest.registry_version) ||
        manifest.tokenizer !== TOKENIZER || !manifest.rankers.includes("bm25") ||
        (manifest.free_text_policy !== undefined && !FREE_TEXT_POLICIES.includes(manifest.free_text_policy)) ||
        !manifest.assets["requirements.json"]) throw new Error("Unsupported release manifest");
    let total = 0;
    for (const [name, meta] of Object.entries(manifest.assets)) {
      if (!safeAsset(name) || !SHA.test(meta.sha256) || !Number.isSafeInteger(meta.bytes) || meta.bytes < 0) {
        throw new Error("Invalid asset descriptor");
      }
      total += meta.bytes;
    }
    if (total > MAX_BYTES) throw new Error("Release exceeds size limit");
    return new Release(root, manifest);
  }

  async binary(path: string): Promise<ArrayBuffer> {
    const meta = this.manifest.assets[path];
    if (!safeAsset(path) || !Object.hasOwn(this.manifest.assets, path)) throw new Error(`Unlisted asset: ${path}`);
    const data = await get(new URL(path, this.root));
    if (meta.bytes !== data.byteLength || meta.sha256 !== await sha256(data)) {
      throw new Error(`Integrity check failed: ${path}`);
    }
    return data;
  }

  async json<T>(path: string): Promise<T> {
    return parse<T>(await this.binary(path));
  }

  async corpus(corpus: Corpus) {
    const [docs, index] = await Promise.all([
      this.json<Document[]>(corpus === "eo" ? "collections.json" : "projects.json"),
      this.json<LexicalIndex>(`lexical/${corpus}.json`),
    ]);
    if (docs.length !== this.manifest.counts[corpus] || index.ids.length !== docs.length ||
        index.lengths.length !== docs.length || index.tokenizer !== TOKENIZER ||
        docs.some((doc, i) => !doc.title || doc.id !== index.ids[i] ||
          doc.provenance.snapshot_id !== this.manifest.parent_snapshot_id || (i > 0 && doc.id <= docs[i - 1].id))) {
      throw new Error(`Inconsistent corpus: ${corpus}`);
    }
    return { docs, index };
  }
}
