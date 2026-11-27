import { compatibility } from "./ranking";
import { catalogueEvidence } from "./screening-evidence";
import type { Constraints, Document, Result } from "./types";

export type AssessmentStatus = "meets" | "partial" | "fails" | "unknown";

export interface ScreeningCriteria extends Omit<Constraints, "strict_metadata"> {
  allowContext: boolean;
  maxResolution?: number;
}

interface Criterion {
  label: string;
  status: AssessmentStatus;
  detail: string;
  sourceUrl?: string;
}

function contribution(result: Result, allowContext: boolean, catalogue: ReturnType<typeof catalogueEvidence>): Criterion {
  const label = "Documented contribution";
  const evidence = result.evidence_use;
  if (evidence?.role === "direct_measurement") {
    return { label, status: "meets", detail: evidence.note, sourceUrl: evidence.source_url };
  }
  if (evidence?.role === "supporting_context") {
    return {
      label,
      status: allowContext ? "meets" : "partial",
      detail: "Documented supporting context. " + evidence.note,
      sourceUrl: evidence.source_url,
    };
  }
  if (catalogue) {
    const status = catalogue.kind === "outside_scope" || catalogue.kind === "research_report" ? "fails" :
      catalogue.kind === "insufficient" ? "unknown" : allowContext ? "meets" : "partial";
    return { label, status, detail: catalogue.detail, sourceUrl: catalogue.sourceUrl };
  }
  return { label, status: "unknown", detail: "The release has no documented measurement or supporting role for this collection and provision." };
}

const areaFit: Record<"compatible" | "incompatible" | "unknown", [AssessmentStatus, string]> = {
  compatible: ["partial", "Catalogue bounds intersect the area. Check observation footprints for actual coverage."],
  incompatible: ["fails", "The catalogue bounds do not intersect the assessment area."],
  unknown: ["unknown", "The catalogue has no usable regional extent. Check observation footprints for this area."],
};

const periodFit: typeof areaFit = {
  compatible: ["partial", "Catalogue dates indicate possible overlap. Check regional dates, observation records, and cadence."],
  incompatible: ["fails", "No documented catalogue interval overlaps the assessment dates."],
  unknown: ["unknown", "The published intervals do not establish overlap with the requested dates."],
};

function scopeCriterion(label: string, doc: Document, scope: Constraints, descriptions: typeof areaFit): Criterion {
  const fit = compatibility(doc, scope);
  const [status, detail] = descriptions[fit === "not_requested" ? "unknown" : fit];
  return { label, status, detail };
}

export function assessCollections(results: Result[], criteria: ScreeningCriteria, point = "") {
  const { allowContext, maxResolution, bbox, start, end } = criteria;
  if (maxResolution !== undefined && (!Number.isFinite(maxResolution) || maxResolution <= 0)) {
    throw new Error("Enter a maximum spatial resolution greater than zero.");
  }
  return results.map(result => {
    const { doc } = result;
    const catalogue = catalogueEvidence(point, doc.id);
    const checks = [contribution(result, allowContext, catalogue)];
    if (maxResolution !== undefined) {
      const value = doc.spatial_resolution_m ?? catalogue?.resolutionM;
      checks.push({
        label: "Spatial resolution",
        status: value == null ? "unknown" : value <= maxResolution ? "meets" : "fails",
        detail: value == null
          ? "The catalogue does not report a spatial resolution in metres."
          : `The catalogue reports ${value} m. Your maximum is ${maxResolution} m.`,
        sourceUrl: doc.spatial_resolution_m == null && catalogue?.resolutionM ? catalogue.sourceUrl : undefined,
      });
    }
    if (bbox) {
      const worldwide = doc.bbox_parts?.some(([w, s, e, n]) => w === -180 && s === -90 && e === 180 && n === 90);
      checks.push(worldwide
        ? { label: "Geographic coverage", status: "unknown", detail: "The catalogue reports worldwide bounds. Check observation footprints for this area." }
        : scopeCriterion("Geographic coverage", doc, { bbox }, areaFit));
    }
    if (start || end) {
      const intervals = doc.intervals?.map(interval =>
        interval.start || interval.end ? interval : { ...interval, ongoing: false });
      const period = scopeCriterion("Observation dates", { ...doc, intervals }, { start, end }, periodFit);
      if (period.status === "partial" && catalogue?.europeanSeriesThrough && start &&
          start.slice(0, 10) > catalogue.europeanSeriesThrough) {
        checks.push({
          label: period.label,
          status: "unknown",
          detail: "The selected dates start after the European series. Check regional availability before relying on the catalogue-wide period.",
          sourceUrl: catalogue.sourceUrl,
        });
      } else {
        checks.push(period);
      }
    }
    const statuses = new Set(checks.map(check => check.status));
    const overall = (["fails", "unknown", "partial", "meets"] as const).find(status => statuses.has(status))!;
    return { result, checks, overall };
  });
}
