interface CatalogueEvidence {
  points: string;
  kind: "context" | "outside_scope" | "research_report" | "insufficient";
  detail: string;
  sourceUrl: string;
  resolutionM?: number;
  europeanSeriesThrough?: string;
}

const cmr = "https://cmr.earthdata.nasa.gov/search/collections.umm_json?concept_id=";

// These assessments apply only to the verified provider collection and provision.
const catalogue: Record<string, CatalogueEvidence> = {
  "cdse:clms_vlcc_tree-cover-density-confidence-layer_europe_10m_yearly_v1": {
    points: "b",
    kind: "context",
    detail: "Provides a quality-support raster for European Tree Cover Density. Use it alongside the canopy measurement to judge confidence in the mapped result.",
    sourceUrl: "https://stac.dataspace.copernicus.eu/v1/collections/clms_vlcc_tree-cover-density-confidence-layer_europe_10m_yearly_v1",
  },
  "cdse:clms_urban-atlas_land-cover-use-change_europe_V010ha_vector_static_v01": {
    points: "aj",
    kind: "context",
    detail: "Maps land-cover and land-use transitions between 2018 and 2021 in covered European urban areas. Compare those transitions with mapped habitat types and condition observations.",
    sourceUrl: "https://stac.dataspace.copernicus.eu/v1/collections/clms_urban-atlas_land-cover-use-change_europe_V010ha_vector_static_v01",
  },
  "cmr:C1214155224-SCIOPS": {
    points: "a",
    kind: "context",
    detail: "Uses CORINE land-cover classes to assess vegetation-related susceptibility to desertification. Use it alongside monitoring of the habitat types and restoration areas.",
    sourceUrl: cmr + "C1214155224-SCIOPS",
  },
  "cmr:C2232848792-CEOS_EXTRA": {
    points: "h",
    kind: "context",
    detail: "Maps broad forest cover for conservation analysis. Use it as a baseline for locating forest habitats, then check the mapped extent and condition of the Annex habitat types.",
    sourceUrl: cmr + "C2232848792-CEOS_EXTRA",
  },
  "cmr:C2763264675-LPCLOUD": {
    points: "h",
    kind: "context",
    detail: "Annual Landsat maps show land-cover classes and changes. The European series covers 2001–2019. Use it as a historical baseline and verify Annex habitat types and condition against inventories.",
    sourceUrl: "https://doi.org/10.5067/MEaSUREs/GLanCE/GLanCE30.001",
    resolutionM: 30,
    europeanSeriesThrough: "2019-12-31",
  },
  "cmr:C3560154312-OB_DAAC": {
    points: "aj",
    kind: "outside_scope",
    detail: "The study sampled coastal waters of northern Alaska. Its observations fall outside the EU monitoring area.",
    sourceUrl: "https://seabass.gsfc.nasa.gov/experiment/ARCTIC_RSEC/",
  },
  "cmr:C2232411685-CEOS_EXTRA": {
    points: "ah",
    kind: "outside_scope",
    detail: "The hydrology study covers one campground in North Carolina in 2002. Its mapped sites fall outside the EU monitoring area.",
    sourceUrl: "https://pubs.usgs.gov/of/2004/1073/",
  },
  "cmr:C1214155282-SCIOPS": {
    points: "aj",
    kind: "research_report",
    detail: "The catalogue entry links to a project final report on semiarid tropical land use. A separate observation dataset is needed to assess EU habitats.",
    sourceUrl: cmr + "C1214155282-SCIOPS",
  },
  "cmr:C1214610817-SCIOPS": {
    points: "a",
    kind: "insufficient",
    detail: "The catalogue describes planned satellite support for a North Atlantic marine study. Check for a data product with documented measurements and coverage before using it for habitat condition.",
    sourceUrl: cmr + "C1214610817-SCIOPS",
  },
};

export function catalogueEvidence(point: string, id: string): CatalogueEvidence | undefined {
  const entry = catalogue[id];
  return point && entry?.points.includes(point) ? entry : undefined;
}
