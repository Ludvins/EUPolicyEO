import { Release } from "./assets";
import { renderAssessment } from "./assessment";
import { parseBounds, parseDates } from "./constraints";
import { renderEmbeddingChart } from "./embedding-chart";
import { renderDataset } from "./release-panels";
import { evidenceUseLabels, showRecord } from "./result-details";
import { setupScreening } from "./screening-panel";
import { formatScore, searchModes } from "./search-modes";
import type { BBox, Constraints, Document as RecordDoc, EmbeddingPoint, Evidence, Mode, Result } from "./types";
import "./styles.css";

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id)! as T;
const node = <K extends keyof HTMLElementTagNameMap>(tag: K, text?: string) => {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  return el;
};

const articleTopics: Record<string, string> = {
  a: "Habitat condition and trends",
  b: "Urban green space and tree canopy",
  c: "Agricultural biodiversity indicators",
  d: "Farmland bird populations",
  e: "Forest biodiversity indicator under Article 12(2)",
  f: "Forest biodiversity indicators under Article 12(3)",
  g: "Pollinator abundance and diversity",
  h: "Habitat area and condition",
  i: "Species habitat area and quality",
  j: "Habitat deterioration and compensation areas",
};

const examples = [
  ["Wetland restoration", "wetland surface water restoration"],
  ["Vegetation cover", "fraction of green vegetation cover"],
  ["Forest canopy change", "forest canopy cover change from satellite imagery"],
];

const sources: Record<string, string> = {
  cdse: "Copernicus Data Space",
  cmr: "NASA Earthdata",
  cordis: "CORDIS",
};

const coverageLabels = {
  compatible: "Overlaps selected coverage",
  incompatible: "Outside selected coverage",
  unknown: "Coverage unclear",
  not_requested: "",
};

const form = $<HTMLFormElement>("search-form");
const query = $<HTMLInputElement>("query");
const mode = $<HTMLSelectElement>("mode");
const requirement = $<HTMLSelectElement>("requirement");
const evidence = $("evidence");
const status = $("search-status");
const fallback = $<HTMLButtonElement>("fallback");
const results = document.querySelector<HTMLElement>(".results")!;
const embeddingMap = $<HTMLDetailsElement>("embedding-map");
const screening = setupScreening($<HTMLDetailsElement>("search-assessment"));

let release: Release;
const legalExamples = new Map<string, Evidence>();
let worker: Worker | undefined;
let requestId = 0;
type MapController = Awaited<ReturnType<typeof import("./bbox-map")["setupMap"]>>;
const mapDetails = $<HTMLDetailsElement>("map-details");
const coordinateFields = ["west", "south", "east", "north"].map(id => $<HTMLInputElement>(id));
let areaMap: Promise<MapController> | undefined;

results.hidden = true;

function showEvidence() {
  const selected = legalExamples.get(requirement.value);
  evidence.replaceChildren();
  evidence.hidden = !selected;
  if (!selected) return;
  const { requirement: req, section } = selected;
  if (req.parent_evidence) evidence.append(node("p", req.parent_evidence));
  evidence.append(node("blockquote", req.verbatim_evidence));

  const url = new URL(section.provenance.source_url);
  if (url.protocol === "https:" && url.host === "eur-lex.europa.eu" && !url.username && !url.password) {
    const article = section.article + (section.paragraph ? "(" + section.paragraph + ")" : "") +
      (section.point ? "(" + section.point + ")" : "");
    const source = node("a", "Article " + article + " on EUR-Lex");
    source.href = url.href;
    source.target = "_blank";
    source.rel = "noopener noreferrer";
    evidence.append(source);
  }
  if (req.search_profile && Object.keys(req.search_profile.record_evidence ?? {}).length) {
    evidence.append(node("p", "Source-documented results appear first. Open a result to see what it supports."));
  }
  query.value = (req.search_profile?.query ?? req.query).slice(0, 2000);
}

function showResults(id: string, records: Result[], ranker: Mode, scoped: boolean) {
  const root = $(id);
  root.replaceChildren();
  if (!records.length) {
    const empty = node("p", scoped
      ? "No records matched the legal topic and current filters."
      : release.manifest.free_text_policy
        ? "No records had enough matching evidence for this query and filters."
        : "No matches for the current query and filters.");
    empty.className = "empty";
    root.append(empty);
    return;
  }
  for (const result of records) {
    const {doc, score, compatibility} = result;
    const card = node("article");
    card.className = "result";
    const tag = node("p", sources[doc.provenance.source] ?? doc.provider ?? doc.provenance.source);
    tag.className = "source";
    const title = node("h3");
    const titleButton = node("button", doc.title);
    titleButton.type = "button";
    titleButton.className = "result-title";
    titleButton.addEventListener("click", () => showRecord(result, ranker, showOnMap));
    title.append(titleButton);
    const meta = node("div");
    meta.className = "result-meta";
    meta.append(node("span", searchModes[ranker].scoreLabel + " " + formatScore(score, ranker)));
    if (result.evidence_use) {
      const role = node("span", evidenceUseLabels[result.evidence_use.role]);
      role.className = "evidence-use";
      meta.append(role);
    }
    if (coverageLabels[compatibility]) {
      const coverage = node("span", coverageLabels[compatibility]);
      coverage.className = "coverage-badge";
      coverage.dataset.status = compatibility;
      meta.append(coverage);
    }
    card.append(tag, title, meta);
    if (doc.description) card.append(node("p", doc.description));
    if (doc.bbox_parts?.length) {
      const extent = node("button", "Show extent on map");
      extent.className = "extent-button";
      extent.type = "button";
      extent.addEventListener("click", () => void showOnMap(doc));
      card.append(extent);
    }
    root.append(card);
  }
}

async function showOnMap(doc: RecordDoc) {
  if (!doc.bbox_parts?.length) return;
  $("collection-filters").setAttribute("open", "");
  mapDetails.open = true;
  const map = await openMap();
  if (map) {
    map.setCoverage({title: doc.title, parts: doc.bbox_parts});
    $("map-clear").hidden = false;
    mapDetails.scrollIntoView({block: "start"});
    mapDetails.querySelector("summary")?.focus({preventScroll: true});
  }
}

function bounds(): BBox | undefined {
  return parseBounds(coordinateFields.map(field => field.value));
}

function updateMap(map: MapController) {
  try { map.setArea(bounds()); } catch { map.setArea(undefined); }
}

function writeArea(area: BBox) {
  if (coordinateFields.some((field, i) => field.value !== String(area[i]))) clearSearchResults();
  coordinateFields.forEach((field, i) => { field.value = String(area[i]); });
  void areaMap?.then(updateMap);
}

async function openMap() {
  $("map-status").textContent = "Loading map outlines…";
  try {
    areaMap ??= import("./bbox-map").then(module => module.setupMap(writeArea));
    const map = await areaMap;
    updateMap(map);
    $("map-status").textContent = "";
    $("map-body").hidden = false;
    return map;
  } catch {
    areaMap = undefined;
    $("map-status").textContent = "Map unavailable. Enter the decimal-degree coordinates above.";
  }
}

function filters(): Constraints {
  const start = $<HTMLInputElement>("start").value;
  const end = $<HTMLInputElement>("end").value;
  const dates = parseDates(start, end);
  return {
    bbox: bounds(),
    ...dates,
    strict_metadata: $<HTMLInputElement>("strict").checked,
  };
}

function clearSearchResults() {
  requestId++;
  status.textContent = "";
  fallback.hidden = true;
  results.hidden = true;
  screening.clear();
  embeddingMap.hidden = true;
  $("embedding-content").replaceChildren();
}

function search(event?: Event) {
  event?.preventDefault();
  clearSearchResults();
  const id = requestId;
  try {
    if (!query.value.trim()) throw new Error("Enter a search query.");
    const constraints = filters();
    const selectedMode = mode.value as Mode;
    const selected = legalExamples.get(requirement.value);
    const profile = selected?.requirement.search_profile;
    const point = selected?.section.point;
    const provision = requirement.value ? requirement.selectedOptions[0].textContent : "";
    const method = searchModes[selectedMode].label;
    status.textContent = "Running " + method.toLowerCase() + "…";
    worker ??= new Worker(new URL("./search.worker.ts", import.meta.url), { type: "module" });
    worker.onmessage = ({ data }) => {
      if (data.id !== requestId) return;
      if ("error" in data) {
        status.textContent = selectedMode === "bm25"
          ? "Search is temporarily unavailable. Try again or reload the page."
          : "This search mode is temporarily unavailable. You can try keyword search.";
        fallback.hidden = selectedMode === "bm25";
        return;
      }
      const eo: Result[] = data.eo;
      const projects: Result[] = data.projects;
      const points: EmbeddingPoint[] | undefined = data.projection;
      showResults("eo", eo, selectedMode, !!profile);
      showResults("projects", projects, selectedMode, !!profile);
      results.hidden = false;
      if (point) screening.show({
        provision, point, collections: eo, constraints,
        openRecord: result => showRecord(result, selectedMode, showOnMap),
      });
      const count = eo.length + projects.length;
      status.textContent = count + (count === 1 ? " result" : " results") + " · " + method;
      if (points?.length) {
        embeddingMap.hidden = false;
        renderEmbeddingChart($("embedding-content"), points, [...eo, ...projects],
          result => showRecord(result, selectedMode, showOnMap));
      }
    };
    worker.onerror = () => {
      worker?.terminate();
      worker = undefined;
      if (id !== requestId) return;
      status.textContent = "Search was interrupted. Try again.";
      fallback.hidden = selectedMode === "bm25";
    };
    worker.postMessage({ id, releaseId: release.manifest.release_id,
      query: query.value, mode: selectedMode, constraints, profile, project: selectedMode === "dense" });
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : "Search failed.";
  }
}

function clearLegalSelection() {
  clearSearchResults();
  requirement.value = "";
  showEvidence();
}

function addFreeTextExamples() {
  const label = node("span", "Try a query");
  const choices = examples.map(([title, text]) => {
    const button = node("button", title);
    button.type = "button";
    button.addEventListener("click", () => {
      clearLegalSelection();
      query.value = text;
      query.focus();
    });
    return button;
  });
  $("search-examples").replaceChildren(label, ...choices);
}

async function initialize() {
  $("retry").hidden = true;
  $("load-status").textContent = "Loading the dataset…";
  try {
    release = await Release.open();
    const [requirements, terms] = await Promise.all([
      release.json<Evidence[]>("requirements.json"),
      release.json<Record<string, {url: string; credit: string}>>("licenses.json"),
    ]);
    if (requirements.length !== release.manifest.source_counts.cellar) throw new Error("Legal evidence count mismatch");

    const examplesGroup = $<HTMLOptGroupElement>("legal-examples");
    examplesGroup.replaceChildren();
    legalExamples.clear();
    for (const row of requirements) {
      const { article, paragraph, point } = row.section;
      if (article !== "20" || paragraph !== "1" || !point || !Object.hasOwn(articleTopics, point)) continue;
      const option = node("option");
      option.value = row.requirement.id;
      const citation = node("span", "20(1)(" + point + ")");
      citation.className = "picker-citation";
      const separator = node("span", " · ");
      separator.className = "picker-separator";
      option.append(citation, separator, node("span", articleTopics[point]));
      legalExamples.set(option.value, row);
      examplesGroup.append(option);
    }

    clearLegalSelection();
    query.value = "";
    addFreeTextExamples();
    for (const option of mode.options) {
      if (option.value !== "bm25") option.disabled = !release.manifest.dense;
    }
    if (!release.manifest.dense) mode.value = "bm25";
    renderDataset($("dataset-data"), release.manifest, terms);
    void renderAssessment($("assessment"), $("assessment-content"), release).then(available => {
      $("assessment-entry").hidden = !available;
      $("assessment-nav").hidden = !available;
    });
    $("workspace").hidden = false;
    $("load-status").textContent = "";
  } catch {
    $("load-status").textContent = "The dataset could not be loaded. Try again.";
    $("retry").hidden = false;
  }
}

$("retry").addEventListener("click", initialize);
mapDetails.addEventListener("toggle", () => { if (mapDetails.open) void openMap(); });
coordinateFields.forEach(field => field.addEventListener("input", () => {
  clearSearchResults();
  void areaMap?.then(updateMap).catch(() => {});
}));
$("map-example").addEventListener("click", async () => {
  writeArea([-7.5, 36, -1.5, 38.8]);
  await areaMap;
  $<HTMLButtonElement>("map-fit").click();
});
$("map-clear").addEventListener("click", async () => {
  (await areaMap)?.setCoverage(undefined);
  $("map-clear").hidden = true;
});
requirement.addEventListener("change", () => {
  clearSearchResults();
  if (!requirement.value) query.value = "";
  showEvidence();
});
query.addEventListener("input", clearLegalSelection);
for (const field of [mode, $("start"), $("end"), $("strict")]) {
  field.addEventListener("change", clearSearchResults);
}
form.addEventListener("submit", search);
fallback.addEventListener("click", () => { mode.value = "bm25"; search(); });
void initialize();
