import { assessmentTable, badge, element, link } from "./assessment";
import { parseBounds, parseDates } from "./constraints";
import { assessCollections } from "./screening";
import type { Constraints, Result } from "./types";

interface SearchContext {
  provision: string;
  point: string;
  collections: Result[];
  constraints: Constraints;
  openRecord: (result: Result) => void;
}

export function setupScreening(panel: HTMLDetailsElement) {
  const $ = <T extends HTMLElement = HTMLElement>(id: string) => panel.querySelector<T>("#" + id)!;
  const form = $<HTMLFormElement>("screening-form");
  const scope = $<HTMLDetailsElement>("screening-scope");
  const start = $<HTMLInputElement>("screening-start");
  const end = $<HTMLInputElement>("screening-end");
  const coordinates = ["west", "south", "east", "north"].map(key => $<HTMLInputElement>("screening-" + key));
  const resolution = $<HTMLInputElement>("screening-resolution");
  const contribution = $<HTMLSelectElement>("screening-contribution");
  const output = $("screening-results");
  const status = $("screening-status");
  let current: SearchContext | undefined;

  function clearAssessment() {
    status.textContent = "";
    output.replaceChildren();
  }

  form.addEventListener("input", clearAssessment);
  form.addEventListener("invalid", event => {
    if (scope.contains(event.target as Node)) scope.open = true;
  }, true);
  form.addEventListener("submit", event => {
    event.preventDefault();
    if (!current) return;
    clearAssessment();
    const { collections, openRecord, point } = current;
    try {
      const assessed = assessCollections(collections, {
        allowContext: contribution.value === "documented",
        maxResolution: resolution.value ? resolution.valueAsNumber : undefined,
        bbox: parseBounds(coordinates.map(field => field.value)),
        ...parseDates(start.value, end.value),
      }, point);
      const columns = assessed[0].checks.map(check => check.label);
      const table = assessmentTable("Assessment of search results", columns, assessed.map(({ result, checks, overall }) => {
        const title = element("button", result.doc.title, "result-title");
        title.type = "button";
        title.addEventListener("click", () => openRecord(result));
        return { title, statuses: [...checks.map(check => check.status), overall] };
      }), "Scrollable matrix for assessed search results");
      const evidence = element("div", undefined, "assessment-evidence");
      for (const { result, checks } of assessed) {
        const details = element("details");
        const reasons = element("dl");
        for (const check of checks) {
          const term = element("dt", check.label);
          term.append(badge(check.status));
          const explanation = element("dd", check.detail);
          if (check.sourceUrl) explanation.append(" ", link("Read evidence", check.sourceUrl));
          reasons.append(term, explanation);
        }
        details.append(element("summary", "Evidence for " + result.doc.title), reasons);
        evidence.append(details);
      }
      const notes = element("details", undefined, "screening-notes");
      notes.append(element("summary", "Evidence by collection"), evidence);
      output.replaceChildren(table, notes);
      status.textContent = assessed.length === 1 ? "1 collection assessed." : assessed.length + " collections assessed.";
    } catch (error) {
      status.textContent = error instanceof Error ? error.message : "The assessment could not be completed.";
    }
  });

  return {
    show(context: SearchContext) {
      if (!context.collections.length) return;
      current = context;
      const { bbox, start: from, end: through } = context.constraints;
      coordinates.forEach((field, i) => { field.value = bbox ? String(bbox[i]) : ""; });
      start.value = from?.slice(0, 10) ?? "";
      end.value = through?.slice(0, 10) ?? "";
      scope.open = Boolean(bbox || from || through);
      $("screening-provision").textContent = "Article " + context.provision;
      $("screening-scope-description").textContent = context.collections.length === 1
        ? "Screen the EO collection returned by this search."
        : `Screen the ${context.collections.length} EO collections returned by this search.`;
      panel.hidden = false;
    },
    clear() {
      current = undefined;
      panel.hidden = true;
      panel.open = false;
      clearAssessment();
    },
  };
}
