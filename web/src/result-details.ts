import type { BBox, Document, Mode, Result } from "./types";
import { formatScore, searchModes } from "./search-modes";
import "./result-details.css";

export const evidenceUseLabels = {
  direct_measurement: "Direct measurement",
  research_method: "Research method",
  supporting_context: "Supporting context",
} as const;

type Fact = [label: string, value: string];

const dateFormat = new Intl.DateTimeFormat("en-GB", {
  day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
});
const degreeFormat = new Intl.NumberFormat("en", { maximumFractionDigits: 5 });

function element<K extends keyof HTMLElementTagNameMap>(tag: K, content?: string, className?: string) {
  const node = document.createElement(tag);
  if (content) node.textContent = content;
  if (className) node.className = className;
  return node;
}

function dateLabel(raw: string): string {
  const value = new Date(raw);
  return Number.isNaN(value.getTime()) ? raw : dateFormat.format(value);
}

function rangeLabel(start?: string | null, end?: string | null, ongoing?: boolean | null): string {
  if (start && end) {
    const first = dateLabel(start);
    const last = dateLabel(end);
    return first === last ? first : first + " – " + last;
  }
  if (start) return dateLabel(start) + (ongoing ? " – ongoing" : " · end date unspecified");
  if (end) return "Through " + dateLabel(end);
  return "Dates unavailable";
}

function reported(values?: string[]): string[] {
  return (values ?? []).filter(value =>
    value.trim() && !/^(?:not provided|unknown|unspecified|n\/a)$/i.test(value.trim()));
}

function facts(items: Fact[]) {
  const list = element("dl", undefined, "record-facts");
  for (const [label, value] of items) {
    const cell = element("div");
    cell.append(element("dt", label), element("dd", value));
    list.append(cell);
  }
  return list;
}

function secureLink(label: string, href: string, allowedHosts: string[]): HTMLAnchorElement | undefined {
  const url = URL.canParse(href) ? new URL(href) : undefined;
  if (url?.protocol !== "https:" || !allowedHosts.includes(url.host) || url.username || url.password) {
    return undefined;
  }
  const anchor = element("a", label);
  anchor.href = url.href;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  return anchor;
}

function sourceInfo(doc: Document) {
  const { source } = doc.provenance;
  if (source === "cdse") return { label: "Copernicus Data Space Ecosystem", kind: "Collection" };
  if (source === "cmr") return { label: "NASA Earthdata", kind: "Collection" };
  if (source === "cordis") return { label: "CORDIS", kind: "Research project" };
  return { label: source.toUpperCase(), kind: "Source record" };
}

function sourceLinks(doc: Document) {
  const { source, source_id, source_url } = doc.provenance;
  const id = encodeURIComponent(source_id);
  let primary: HTMLAnchorElement | undefined;
  const links: HTMLAnchorElement[] = [];
  if (source === "cordis") {
    primary = secureLink("Open project on CORDIS", source_url, ["cordis.europa.eu"]);
  }
  if (source === "cdse" && /^[a-z\d_.-]+$/i.test(source_id)) {
    primary = secureLink("Open in the Copernicus catalogue",
      "https://browser.stac.dataspace.copernicus.eu/collections/" + id,
      ["browser.stac.dataspace.copernicus.eu"]);
    const raw = secureLink("Raw catalogue record (JSON)", source_url, ["stac.dataspace.copernicus.eu"]);
    if (raw) links.push(raw);
  }
  if (source === "cmr" && /^C\d+-[\w.-]+$/.test(source_id)) {
    primary = secureLink("Open in NASA Earthdata",
      "https://search.earthdata.nasa.gov/search/granules?p=" + id, ["search.earthdata.nasa.gov"]);
    const raw = secureLink("Raw catalogue record (JSON)",
      "https://cmr.earthdata.nasa.gov/search/collections.umm_json?concept_id=" + id,
      ["cmr.earthdata.nasa.gov"]);
    if (raw) links.push(raw);
    const providerPage = secureLink("Data provider page", source_url,
      ["doi.org", "www.earthdata.nasa.gov", "earthdata.nasa.gov"]);
    if (providerPage) links.push(providerPage);
  }
  return { primary, links };
}

function coverageTable(boxes: BBox[]) {
  const table = element("table", undefined, "record-coverage-table");
  table.append(element("caption", "Collection bounding boxes in decimal degrees", "record-sr-only"));
  const head = table.createTHead().insertRow();
  for (const label of ["West", "South", "East", "North"]) {
    const cell = element("th", label);
    cell.scope = "col";
    head.append(cell);
  }
  const body = table.createTBody();
  for (const box of boxes) {
    const row = body.insertRow();
    for (const degree of box) {
      const cell = row.insertCell();
      cell.textContent = degreeFormat.format(degree) + "°";
    }
  }
  return table;
}

function collectionMetadata(doc: Document) {
  const section = element("section", undefined, "record-section");
  section.append(element("h3", "Collection coverage"));
  const periods = doc.intervals?.length ? doc.intervals :
    [{ start: doc.temporal_start, end: doc.temporal_end, ongoing: doc.ongoing }];
  const labels = [...new Set(periods.map(period => rangeLabel(period.start, period.end, period.ongoing)))];
  const boxes = doc.bbox_parts ?? [];
  const resolution = doc.spatial_resolution_m;
  const items: Fact[] = [
    ["Dates in catalogue", labels.length > 1 ? labels.length + " periods" : labels[0]],
    ["Spatial resolution", resolution != null ? degreeFormat.format(resolution) + " m" : "Unavailable"],
    ["Geographic extent", boxes.length ? (boxes.length === 1 ? "1 bounding box" : boxes.length + " bounding boxes") : "Unavailable"],
  ];
  const platform = reported(doc.platform);
  const instrument = reported(doc.instrument);
  if (platform.length) items.push(["Platforms", platform.join(", ")]);
  if (instrument.length) items.push(["Instruments", instrument.join(", ")]);
  if (doc.processing_level) items.push(["Processing level", doc.processing_level]);
  section.append(facts(items));
  if (labels.length > 1 || boxes.length) {
    const details = element("details");
    details.append(element("summary", "Dates and coordinate bounds"));
    if (labels.length > 1) {
      const periods = element("ul");
      for (const label of labels) periods.append(element("li", label));
      details.append(periods);
    }
    if (boxes.length) details.append(coverageTable(boxes));
    section.append(details);
  }
  section.append(element("p", "Check the source catalogue for individual observations.", "record-note"));
  return section;
}

function projectMetadata(doc: Document) {
  const section = element("section", undefined, "record-section");
  section.append(element("h3", "Project information"));
  const items: Fact[] = [["Dates", rangeLabel(doc.start_date, doc.end_date)]];
  if (doc.acronym) items.push(["Acronym", doc.acronym]);
  if (doc.programme) items.push(["Programme", doc.programme === "HORIZON" ? "Horizon Europe" : doc.programme]);
  section.append(facts(items));
  if (doc.metadata_quality_flags.includes("public_objective_omitted")) {
    section.append(element("p", "Project objectives are available on CORDIS.", "record-note"));
  }
  return section;
}

function matchDetails(result: Result, ranker: Mode) {
  const { score, compatibility } = result;
  const section = element("section", undefined, "record-section record-match");
  section.append(element("h3", "Search match"));
  const {scoreLabel, note} = searchModes[ranker];
  const descriptions = {
    compatible: "Collection metadata overlaps the selected filters.",
    incompatible: "Collection metadata falls outside at least one selected filter.",
    unknown: "Available coverage metadata cannot establish whether the selected filters match.",
    not_requested: "",
  };
  section.append(facts([[scoreLabel, formatScore(score, ranker)]]));
  section.append(element("p", note, "record-note"));
  if (result.evidence_use) {
    const { role, note, source_url } = result.evidence_use;
    section.append(element("h4", evidenceUseLabels[role]), element("p", note));
    const source = secureLink("Read the evidence source", source_url,
      ["land.copernicus.eu", "cordis.europa.eu", "stac.dataspace.copernicus.eu", "cmr.earthdata.nasa.gov", "doi.org"]);
    if (source) {
      if (source.hostname === "stac.dataspace.copernicus.eu") source.append(" (STAC JSON)");
      if (source.hostname === "cmr.earthdata.nasa.gov") source.append(" (CMR JSON)");
      section.append(source);
    }
  }
  if (descriptions[compatibility]) section.append(element("p", descriptions[compatibility]));
  return section;
}

function provenanceDetails(doc: Document, links: HTMLAnchorElement[]) {
  const section = element("details", undefined, "record-provenance");
  section.append(element("summary", "Source and provenance"));
  const { source_id, snapshot_id, revision, retrieved_at, raw_sha256 } = doc.provenance;
  const items: Fact[] = [["Source identifier", source_id], ["Source snapshot", snapshot_id]];
  if (retrieved_at) items.push(["Retrieved", dateLabel(retrieved_at)]);
  if (revision) items.push(["Source revision", revision]);
  if (raw_sha256) items.push(["Source SHA-256", raw_sha256]);
  section.append(facts(items));
  if (links.length) {
    const actions = element("div", undefined, "record-secondary");
    actions.append(...links);
    section.append(actions);
  }
  return section;
}

export function showRecord(result: Result, ranker: Mode, showOnMap: (doc: Document) => void) {
  const { doc } = result;
  const dialog = document.querySelector<HTMLDialogElement>("#record-details")!;
  const content = dialog.querySelector<HTMLElement>("#record-content")!;
  const close = dialog.querySelector<HTMLButtonElement>("#record-close")!;
  dialog.setAttribute("aria-labelledby", "record-title");
  close.onclick = event => {
    event.preventDefault();
    dialog.close();
  };

  const { label, kind } = sourceInfo(doc);
  const sourceLabel = doc.provider && !["CDSE", "CORDIS"].includes(doc.provider)
    ? label + " · " + doc.provider : label;
  const head = element("header", undefined, "record-heading");
  const title = element("h2", doc.title);
  title.id = "record-title";
  title.tabIndex = -1;
  head.append(element("p", kind + " · " + sourceLabel, "record-label"), title);
  if (doc.description) head.append(element("p", doc.description, "record-description"));

  const { primary, links } = sourceLinks(doc);
  const actions = element("div", undefined, "record-actions");
  if (primary) {
    primary.className = "record-primary";
    actions.append(primary);
  }
  if (doc.bbox_parts?.length) {
    const map = element("button", "Show coverage on map", "record-map");
    map.type = "button";
    map.onclick = () => {
      dialog.close();
      showOnMap(doc);
    };
    actions.append(map);
  }
  if (actions.children.length) head.append(actions);

  const project = doc.provenance.source === "cordis";
  content.replaceChildren(head, project ? projectMetadata(doc) : collectionMetadata(doc));
  const themes = [...new Set(reported(project ? doc.topics : doc.keywords))];
  if (themes.length) {
    const section = element("section", undefined, "record-section");
    section.append(element("h3", project ? "Funding topics" : "Catalogue themes"));
    const tags = element("ul", undefined, "record-tags");
    for (const theme of themes) tags.append(element("li", theme));
    section.append(tags);
    content.append(section);
  }
  if (project && doc.discovery_terms?.length) {
    const section = element("section", undefined, "record-section");
    section.append(element("h3", "Discovery terms"));
    const tags = element("ul", undefined, "record-tags");
    for (const term of doc.discovery_terms) tags.append(element("li", term));
    section.append(tags, element("p", "Topics and methods mentioned in the CORDIS project objective.", "record-note"));
    content.append(section);
  }
  if (!project && doc.measurement_terms?.length) {
    const section = element("section", undefined, "record-section");
    section.append(element("h3", "Measurement terms"));
    const tags = element("ul", undefined, "record-tags");
    for (const term of doc.measurement_terms) tags.append(element("li", term));
    section.append(tags, element("p", "Terms from provider bands or catalogue variable keywords.", "record-note"));
    content.append(section);
  }
  content.append(matchDetails(result, ranker), provenanceDetails(doc, links));

  if (!dialog.open) dialog.showModal();
  dialog.scrollTop = 0;
  title.focus({ preventScroll: true });
}
