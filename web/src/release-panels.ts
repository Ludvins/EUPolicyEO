import type { Manifest } from "./types";
import "./release-panels.css";

type Terms = Record<string, { url: string; credit: string }>;

const sources = [
  { key: "cellar", title: "EUR-Lex", channel: "CELLAR", unit: "legal requirements" },
  { key: "cordis", title: "CORDIS", channel: "Horizon Europe", unit: "research projects" },
  { key: "cdse", title: "Copernicus Data Space", channel: "STAC catalogue", unit: "EO collections" },
  { key: "cmr", title: "NASA Earthdata", channel: "CMR catalogue", unit: "EO collections" },
] as const;

const sourceHosts = new Set([
  "eur-lex.europa.eu", "publications.europa.eu", "cordis.europa.eu",
  "stac.dataspace.copernicus.eu", "land.copernicus.eu", "cmr.earthdata.nasa.gov",
  "earthdata.nasa.gov", "www.earthdata.nasa.gov", "huggingface.co",
]);

const date = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeZone: "UTC" });
const number = new Intl.NumberFormat("en", { maximumFractionDigits: 2 });

function make<K extends keyof HTMLElementTagNameMap>(tag: K, value?: string, className?: string) {
  const element = document.createElement(tag);
  if (value !== undefined) element.textContent = value;
  if (className) element.className = className;
  return element;
}

function safeUrl(value: unknown) {
  if (typeof value !== "string") return;
  try {
    const url = new URL(value);
    if (url.protocol === "https:" && sourceHosts.has(url.host) && !url.username && !url.password)
      return url;
  } catch { /* An invalid endpoint is not made clickable. */ }
}

function sourceLink(url: URL | undefined, text: string) {
  if (!url) return make("span", text);
  const anchor = make("a", text);
  anchor.href = url.href;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  return anchor;
}

function time(value: unknown) {
  if (typeof value !== "string" || !Number.isFinite(Date.parse(value))) return;
  const element = make("time", date.format(new Date(value)));
  element.dateTime = value;
  return element;
}

function format(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? number.format(value) : "—";
}

function disclosure(label: string, context?: string) {
  const details = make("details", undefined, "rp-disclosure");
  const summary = make("summary", label);
  if (context) summary.setAttribute("aria-label", label + " for " + context);
  details.append(summary);
  return details;
}

function definitions(entries: readonly (readonly [string, string | HTMLElement])[], kind = "") {
  const list = make("dl", undefined, "rp-definitions " + kind);
  for (const [label, value] of entries) {
    const item = make("div");
    const valueNode = make("dd");
    valueNode.append(value);
    item.append(make("dt", label), valueNode);
    list.append(item);
  }
  return list;
}

function endpointLabel(url: URL | undefined, index: number) {
  const keyword = url?.searchParams.get("keyword");
  const offset = url?.searchParams.get("offset");
  if (keyword) return "Search for " + keyword;
  if (offset) return "Catalogue page at offset " + offset;
  if (url?.pathname.endsWith(".zip")) return "Project data archive";
  return index === 0 ? "Source endpoint" : "Source endpoint " + (index + 1);
}

export function renderDataset(root: HTMLElement, manifest: Manifest, terms: Terms): void {
  const cards = make("div", undefined, "rp-source-grid");
  for (const { key, title, channel, unit } of sources) {
    const freshness = manifest.source_freshness[key];
    if (!freshness) continue;
    const card = make("article", undefined, "rp-source");
    const heading = make("div", undefined, "rp-source-heading");
    heading.append(make("h3", title), make("p", channel));
    const quantity = make("p", undefined, "rp-quantity");
    quantity.append(make("strong", format(manifest.source_counts[key])), make("span", unit));
    card.append(heading, quantity);
    const accessed = time(freshness.latest);
    if (accessed) {
      const line = make("p", undefined, "rp-source-date");
      line.append(freshness.mode === "import" ? "Imported " : "Fetched ", accessed);
      card.append(line);
    }
    const showDetails = disclosure("Source details", title);
    const termsUrl = safeUrl(terms[key]?.url);
    if (terms[key]?.credit) showDetails.append(make("p", terms[key].credit));
    if (termsUrl) showDetails.append(sourceLink(termsUrl, "Reuse terms"));
    if (freshness.bounds.length) {
      const bounds = make("ul", undefined, "rp-bound-list");
      for (const [index, bound] of freshness.bounds.entries()) {
        const url = safeUrl(bound);
        const item = make("li");
        const anchor = sourceLink(url, endpointLabel(url, index));
        if (url) anchor.title = url.href;
        item.append(anchor);
        bounds.append(item);
      }
      showDetails.append(bounds);
    }
    card.append(showDetails);
    cards.append(card);
  }
  const provenance = disclosure("Release provenance");
  provenance.classList.add("rp-box");
  const published = time(manifest.created_at);
  const rows: [string, string | HTMLElement][] = [
    ["Release", make("code", manifest.release_id)],
    ["Source snapshot", make("code", manifest.parent_snapshot_id)],
    ["Corpus hash", make("code", manifest.public_corpus_hash)],
    ["Registry", "v" + manifest.registry_version + " · " + manifest.parent_ranker],
    ["Browser search", manifest.dense ? "Keyword (BM25), semantic (MiniLM ONNX) and hybrid" : "Keyword (BM25)"],
  ];
  if (published) rows.push(["Built", published]);
  if (manifest.git_revision) rows.push(["Code revision", make("code", manifest.git_revision)]);
  if (manifest.dense) rows.push(["Encoder revision", make("code", manifest.dense.revision)]);
  provenance.append(definitions(rows, "rp-provenance"), make("p", manifest.subset_policy));
  if (manifest.dense && terms.encoder?.credit) {
    const encoder = make("p");
    encoder.append(terms.encoder.credit + " ", sourceLink(safeUrl(terms.encoder.url), "Model source"));
    provenance.append(encoder);
  }
  root.classList.add("release-panels");
  root.replaceChildren(cards, provenance);
}
