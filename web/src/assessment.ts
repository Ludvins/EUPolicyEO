import type { Release } from "./assets";
import briefExample from "../../reports/policy_brief.json" with { type: "json" };
import "./assessment.css";

type Status = "meets" | "partial" | "fails" | "unknown";
type Criterion = {key: string; label: string; status: Status; detail: string; source_url: string};
type Product = {id: string; title: string; source_url: string;
  results: {indicator: string; status: Status; summary: string; criteria: Criterion[]}[];
  observation_sample?: {basis: string; years: {year: number; items: {id: string}[]; url: string}[]}};
type Matrix = {
  schema_version: number; snapshot_id: string; assessment_id: string; assessment_scope: string;
  scenario: {title: string; start_year: number; end_year: number; basis: string; thresholds: {
    max_raster_resolution_m: number; max_urban_mapping_unit_ha: number; max_cadence_years: number; accuracy: string;
  }};
  requirement: {provision: string; source_url: string; verbatim: string; lead_in?: string;
    related: {provision: string; text: string; source_url: string}[]};
  indicators: {id: string; label: string}[];
  products: Product[];
  gaps: {indicator: string; summary: string; next_step: string; source_url: string}[];
};

const labels: Record<Status, string> = {meets: "Meets", partial: "Partial", fails: "Fails", unknown: "Unknown"};
const domains = new Set(["eur-lex.europa.eu", "land.copernicus.eu", "library.land.copernicus.eu", "stac.dataspace.copernicus.eu"]);
const report = "reports/suitability.json";

function element<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, className?: string) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function link(label: string, target: string) {
  const url = new URL(target);
  if (url.protocol !== "https:" || !domains.has(url.host) || url.username || url.password) return element("span", label);
  if (url.host === "stac.dataspace.copernicus.eu") label += " (STAC JSON)";
  const anchor = element("a", label);
  anchor.href = url.href;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  return anchor;
}

function badge(status: Status) {
  return element("span", labels[status], "assessment-status status-" + status);
}

function criterionDetail(criterion: Criterion) {
  // Keep the archived assessment and its linked reporting brief reproducible.
  return criterion.detail.replace(
    "The catalogue uses a global placeholder extent. Confirm valid pixels or features in each reporting area using the item inventory.",
    "The catalogue reports worldwide bounds. Check the item inventory for valid coverage in the reporting area.",
  );
}

function reportingBrief(assessmentId: string) {
  if (assessmentId !== briefExample.assessment_id) return;
  const brief = element("details", undefined, "assessment-brief");
  brief.append(element("summary", "Example reporting brief"), element("p", briefExample.question),
    element("p", "This example uses " + briefExample.model + " to summarise the assessment evidence and cite its sources."));
  const claims = element("ul");
  for (const claim of briefExample.claims) {
    const row = element("li");
    row.append(element("p", claim.statement));
    const citations = element("div", undefined, "assessment-brief-citations");
    for (const source of claim.citations) {
      const label = source.label.split(" · ").at(-1) ?? source.label;
      citations.append(link(label, source.url));
    }
    row.append(citations);
    claims.append(row);
  }
  brief.append(claims);
  return brief;
}

function resultsFor(matrix: Matrix, id: string) {
  const rows = matrix.products.flatMap(product => {
    const result = product.results.find(row => row.indicator === id);
    return result ? [{product, result}] : [];
  });
  const content = element("div");
  const gap = matrix.gaps.find(row => row.indicator === id);
  if (gap) {
    const summary = element("aside", undefined, "assessment-gap");
    const title = id === "canopy" ? "Urban boundaries and local accuracy" : gap.summary;
    summary.append(element("strong", title), element("p", gap.next_step), link("Reference", gap.source_url));
    content.append(summary);
  }
  if (!rows.length) {
    content.append(element("p", "No products were assessed for this indicator."));
    return content;
  }
  const table = element("table", undefined, "assessment-table");
  table.createCaption().textContent = "Fitness-for-purpose matrix";
  const headings = table.createTHead().insertRow();
  for (const title of ["EO product", ...rows[0].result.criteria.map(row => row.label), "Overall"]) {
    const header = element("th", title);
    header.scope = "col";
    headings.append(header);
  }
  const body = table.createTBody();
  const details = element("div", undefined, "assessment-evidence");
  for (const {product, result} of rows) {
    const item = body.insertRow();
    const title = element("th");
    title.scope = "row";
    title.append(link(product.title, product.source_url));
    item.append(title);
    for (const row of result.criteria) item.insertCell().append(badge(row.status));
    item.insertCell().append(badge(result.status));

    const disclosure = element("details");
    disclosure.append(element("summary", product.title), element("p", result.summary));
    const definitions = element("dl");
    for (const row of result.criteria) {
      const term = element("dt", row.label);
      term.append(badge(row.status));
      const explanation = element("dd", criterionDetail(row) + " ");
      explanation.append(link("Source", row.source_url));
      definitions.append(term, explanation);
    }
    disclosure.append(definitions);
    if (product.observation_sample) {
      disclosure.append(element("h4", "Sampled catalogue items"), element("p", product.observation_sample.basis));
      const samples = element("ul", undefined, "assessment-samples");
      for (const year of product.observation_sample.years) {
        const sample = element("li");
        sample.append(link(`${year.year} · ${year.items.length} intersecting items`, year.url));
        samples.append(sample);
      }
      disclosure.append(samples);
    }
    details.append(disclosure);
  }
  const scroll = element("div", undefined, "assessment-scroll");
  scroll.tabIndex = 0;
  scroll.setAttribute("role", "region");
  scroll.setAttribute("aria-label", "Scrollable EO product assessment matrix");
  scroll.append(table);
  content.append(element("p", "Scroll horizontally to see all criteria.", "assessment-scroll-hint"), scroll, details);
  return content;
}

export async function renderAssessment(section: HTMLElement, root: HTMLElement, release: Release) {
  section.hidden = true;
  if (!Object.hasOwn(release.manifest.assets, report)) return false;
  try {
    const matrix = await release.json<Matrix>(report);
    if (matrix.schema_version !== 1 || matrix.snapshot_id !== release.manifest.parent_snapshot_id || !matrix.indicators.length) {
      throw new Error("Assessment release mismatch");
    }
    const heading = element("div", undefined, "assessment-intro");
    const {scenario, requirement} = matrix;
    heading.append(element("h3", scenario.title),
      element("p", `${scenario.start_year}–${scenario.end_year} · ${requirement.provision}`),
      element("p", matrix.assessment_scope));
    const settings = element("div", undefined, "assessment-settings");
    const legal = element("details");
    legal.append(element("summary", "Legal obligation"), element("blockquote", requirement.verbatim),
                 link(requirement.provision + " on EUR-Lex", requirement.source_url));
    if (requirement.lead_in) legal.append(element("p", requirement.lead_in));
    for (const row of requirement.related) {
      const paragraph = element("p", row.text + " ");
      paragraph.append(link(row.provision, row.source_url));
      legal.append(paragraph);
    }
    const scope = element("details");
    const {thresholds} = scenario;
    scope.append(element("summary", "Analyst screening criteria"), element("p", scenario.basis));
    const conditions = element("ul");
    for (const text of [
      `Raster resolution of ${thresholds.max_raster_resolution_m} m or finer`,
      `Urban mapping unit of ${thresholds.max_urban_mapping_unit_ha} ha or smaller`,
      thresholds.max_cadence_years === 1 ? "Annual observations" : `Observations every ${thresholds.max_cadence_years} years`,
      thresholds.accuracy,
    ]) conditions.append(element("li", text));
    scope.append(conditions);
    settings.append(legal, scope);
    const controls = element("div", undefined, "assessment-controls");
    controls.setAttribute("role", "group");
    controls.setAttribute("aria-label", "Monitoring indicator");
    const rendered = element("div");
    for (const indicator of matrix.indicators) {
      const button = element("button", indicator.label);
      button.type = "button";
      button.setAttribute("aria-pressed", "false");
      button.addEventListener("click", () => {
        for (const choice of controls.children) choice.setAttribute("aria-pressed", String(choice === button));
        rendered.replaceChildren(resultsFor(matrix, indicator.id));
      });
      controls.append(button);
    }
    root.replaceChildren(heading, settings, controls, rendered);
    const brief = reportingBrief(matrix.assessment_id);
    if (brief) root.append(brief);
    controls.querySelector("button")!.click();
    section.hidden = false;
    if (location.hash === "#assessment") section.scrollIntoView();
    return true;
  } catch {
    root.replaceChildren(element("p", "The assessment could not be loaded."));
    section.hidden = false;
    return true;
  }
}
