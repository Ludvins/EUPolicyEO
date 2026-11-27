# Data sources and reuse

## Source scope

| Source | Local processing | Public release |
| --- | --- | --- |
| **CELLAR / EUR-Lex** | English original of the Nature Restoration Regulation, Article 20 subdivisions and source hashes | Normalized Article 20 sections and applicable parent sections, plus exact evidence spans with offsets, requirement IDs and citation links. © European Union. [CELLAR publications](https://op.europa.eu/en/web/cellar/cellar-data/publications) · [EUR-Lex reuse terms](https://eur-lex.europa.eu/content/help/data-reuse/reuse-contents-eurlex-details.html) |
| **CORDIS** | Horizon Europe Projects CSV with titles, objectives, grant IDs, topics and dates | Factual grant fields, topic identifiers and controlled discovery labels when enabled. Full beneficiary objectives remain in local mode. © European Union. [Projects dataset](https://data.europa.eu/data/datasets/cordis-eu-research-projects-under-horizon-europe-2021-2027?locale=en) · [Legal notice](https://cordis.europa.eu/about/legal) |
| **Copernicus Data Space Ecosystem** | STAC collection titles, descriptions, temporal intervals, bounding rectangles and supported metadata | Selected catalogue facts from the Copernicus Land Monitoring Service, which is funded by the European Union. The export normalizes selected fields. Follow the provider's terms for underlying products. [CDSE terms](https://dataspace.copernicus.eu/terms-and-conditions) · [CLMS data policy](https://land.copernicus.eu/en/data-policy) |
| **NASA CMR** | UMM-C collection records with provider and revision metadata, deduplicated by latest observed revision | Selected catalogue facts, science keywords, coverage and provider links. Records with a populated UMM-C `UseConstraints` field remain local. Provider abstracts, access details and files remain local. [CMR search API](https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html) · [UMM-C use constraints](https://wiki.earthdata.nasa.gov/spaces/CMR/pages/121311158/Use%2BConstraints) |

Topic quotas reserve space for the monitoring subjects defined in Article 20(1). Source-documented matches and public metadata matches have priority within each quota. Stable IDs break ties and fill remaining spaces up to each source cap. The release keeps the field allowlist above. Full descriptions, raw responses and imagery storage URLs remain local. [Release configuration](../configs/pages.yaml) · [Verification](verification.md)

CORDIS discovery labels come from a fixed vocabulary of environmental methods and measurements. The exporter matches terms in archived project objectives and retains up to 16 sorted labels with the original project citation. The labels indicate topics mentioned in the proposal. Use the linked CORDIS record to verify which work was carried out. The exporter discards the matched text and keeps objective prose in local storage. CORDIS identifies separate reuse terms for beneficiary materials. [Discovery vocabulary](../src/eupolicyeo/discovery_terms.py) · [CORDIS legal notice](https://cordis.europa.eu/about/legal)

For selected legal presets, the record detail shows a source-documented evidence role and the part of the provision it can support. A Copernicus Tree Cover Density layer measures canopy cover and needs urban boundaries to calculate the urban indicator. CORDIS project reports can document research methods, and land-use maps can supply context for screening. [Copernicus tree-cover product](https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover?tab=tree_cover_density) · [PollinERA field monitoring](https://cordis.europa.eu/project/id/101135005/reporting)

## Coverage and availability

- **Collection coverage** is based on provider bounding rectangles and observation intervals. Coordinates use WGS84 longitude and latitude in degrees. Rectangles crossing the antimeridian split into two parts, and edge contact counts as overlap. Temporal filtering compares individual intervals. Missing metadata retains an unknown status, including under strict filtering.
- **Granule availability** checks metadata in a bounded local inventory for the model's snapshot. The result describes compatible granules found in that inventory for the queried area and dates. The original catalogue remains the reference for current coverage and for individual observations outside the captured pages.
- **Geometry precision** is rectangular. Irregular collection footprints, sub-pixel coverage and jurisdictional borders require source-level verification.

## Map data

The browser uses Natural Earth public-domain vector data for the world view, zoomed coastlines and city lookup. Geometry and place names are bundled with the static build and load from the site's origin. The map draws the requested area and a selected collection extent using the same rectangular overlap rules as search. The overlays are useful for screening catalogue coverage. [Natural Earth terms of use](https://www.naturalearthdata.com/about/terms-of-use/)

| Layer | Version | Source archive SHA-256 |
| --- | --- | --- |
| [1:110m land](https://www.naturalearthdata.com/downloads/110m-physical-vectors/110m-land/) | 4.1.0 | `1926c621afd6ac67c3f36639bb1236134a48d82226dc675d3e3df53d02d2a3de` |
| [1:50m land](https://www.naturalearthdata.com/downloads/50m-physical-vectors/50m-land/) | 4.1.0 | `0b8e670cf80dce9cbebe2a193bc44ba5602758c22e1fa603980553646d7ff162` |
| [1:50m populated places, simple](https://www.naturalearthdata.com/downloads/50m-cultural-vectors/50m-populated-places/) | 5.1.2 | `a6ebb4be4672de4cd2b94b04cdc9a1bd5a5cb684d28c0e75f535152e5f07a296` |

The 67,009-byte overview rounds coastline coordinates to 0.1 degrees. The 953,984-byte detail asset rounds coastline coordinates to 0.01 degrees and place centers to 0.0001 degrees. These rounding choices describe the bundled representation. The source map scale determines geographic detail.

## Model terms and browser data

The project code is MIT-licensed. The pinned MiniLM graph and tokenizer carry the model's Apache-2.0 attribution and license. The static distribution retains the source attribution and dependency notices for Tokenizers.js and ONNX Runtime Web. [MIT License](../LICENSE) · [Pinned MiniLM revision](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/tree/1110a243fdf4706b3f48f1d95db1a4f5529b4d41) · [Model card](model_card.md)

Queries, area selection and ranking stay in the browser. Hosting providers may retain ordinary asset-request logs. Opening a source link goes directly to its publisher under that publisher's terms.
