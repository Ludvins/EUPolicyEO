# Article 20 benchmark notes

These diagnostics describe extraction and candidate selection for the 26 November 2026 snapshot `0c19de8d261c9d6c464f475c`. The 44-query, 400-pair pool establishes the scope of the original review exercise. Subsequent model judgments and known-record retrieval checks are reported with their own methods and releases. [Annotation procedure](../eval/annotation_guide.md) · [Measured results](verification.md)

## Evidence integrity

All 22 direct evidence excerpts matched their saved section text at the recorded offsets. All 10 inherited excerpts matched their parent sections. The 400 candidate pairs were unique, and each displayed evidence excerpt appeared in its candidate's saved description or title. [Original English regulation](https://eur-lex.europa.eu/eli/reg/2024/1991/oj/eng#art_20)

## Baseline extraction observations

The table describes the extraction in the original public-release candidate and first pilot. The revised extractor and subsequent evaluation are recorded separately. [Before-and-after comparison](../reports/article20_comparison.json)

| Provision | Observation |
| --- | --- |
| 20(1)(b) | The extraction preserves the two observables and urban ecosystem scope, with Member States and the duty to monitor recovered from paragraph 1. The cited definitions and area delineation matter for choosing an EO collection. Article 3(21) specifically refers to the Copernicus Land Monitoring Service Tree Cover Density data. [Articles 3 and 20](https://eur-lex.europa.eu/eli/reg/2024/1991/oj/eng) |
| 20(1)(g) | The draft preserves pollinator abundance and diversity and the Article 10(2) cross-reference. A vegetation or habitat product can supply environmental context. Its record needs evidence of species observations before it qualifies as a direct measurement of this requirement. [Articles 10 and 20](https://eur-lex.europa.eu/eli/reg/2024/1991/oj/eng) |
| 20(3) | The source gives a start date for monitoring under five points in paragraph 1. The generated query is `start on 18 August 2024`, and `deadline_text` is null. Attach this as commencement information to the referenced obligations, or route it to legal evidence without product retrieval. [Article 20](https://eur-lex.europa.eu/eli/reg/2024/1991/oj/eng#art_20) |
| 20(6) | The five sentences are preserved, but the extracted action is `be` and the annual clause has no frequency value. The sentence starting at offset 1115 also requires coordination with reporting and assessment cycles. The draft retains that text inside the observable field. [Article 20](https://eur-lex.europa.eu/eli/reg/2024/1991/oj/eng#art_20) |
| 20(9) | The draft captures operation on databases and GIS. The coordinated obligation to maximise access and use of data and services is inside the same observable. Keep the coordinated actions distinct, with the original evidence span. [Article 20](https://eur-lex.europa.eu/eli/reg/2024/1991/oj/eng#art_20) |
| 20(11)(a) and (b) | These parsed points describe optional Commission action on indicator methods. The parent lead-in uses `may, by means of implementing acts` and the draft misses both points. If surfaced, their modality is permission. [Article 20](https://eur-lex.europa.eu/eli/reg/2024/1991/oj/eng#art_20) |

## Baseline candidate judgments

The diagnostic sample covers 13 of 58 pooled pairs for the urban canopy, pollinator and start-date queries. The scale assigns 2 to a direct match, 1 to a useful partial match and 0 to an unrelated result. These provisional judgments support error analysis and consider the captured metadata, the legal observable and its geographic scope.

| Provision | Candidate | Label | Reason |
| --- | --- | --- | --- |
| 20(1)(b) | `cdse:clms_lcm_global_10m_yearly_v1_cog` | 1 | Annual global land-cover classification with a tree-cover class. It does not establish fractional canopy density or include the full statutory urban green space definition. [CDSE collection](https://stac.dataspace.copernicus.eu/v1/collections/clms_lcm_global_10m_yearly_v1_cog) |
| 20(1)(b) | `cmr:C2763266352-LPCLOUD` | 1 | Genuine global 30 m tree-canopy information for historical epochs from 2000 through 2015. Useful as context with coverage ending before the monitoring commencement in Article 20(3). [Collection DOI](https://doi.org/10.5067/MEaSUREs/GFCC/GFCC30TC.003) |
| 20(1)(b) | `cmr:C2395504063-ORNL_CLOUD` | 0 | Scenario projections at about 5.6 km in the conterminous US. The record does not support measuring EU urban canopy. [Collection DOI](https://doi.org/10.3334/ORNLDAAC/1216) |
| 20(1)(b) | `cmr:C1214587409-SCIOPS` | 0 | Airborne forest structure data from a research station and its surroundings in Costa Rica. The captured collection has no EU urban coverage. [CMR record](https://cmr.earthdata.nasa.gov/search/collections.umm_json?concept_id=C1214587409-SCIOPS) |
| 20(1)(b) | `cordis:101039795` | 1 | Terrestrial laser scanning and EO methods for observing canopy structure are transferable. The project studies forest disturbance and recovery, with no urban ecosystem delineation in the objective. [CORDIS SPACETWIN](https://cordis.europa.eu/project/id/101039795) |
| 20(1)(b) | `cordis:101069506` | 0 | The published objective focuses on urban energy, mobility and circular economy. It provides no evidence of green space or tree-canopy measurement. [CORDIS DUT](https://cordis.europa.eu/project/id/101069506) |
| 20(1)(b) | `cordis:101054069` | 0 | Historical sound and urban ritual account for shared words. The project contains no vegetation or monitoring method. [CORDIS project](https://cordis.europa.eu/project/id/101054069) |
| 20(1)(g) | `cdse:clms_lwq-nrt_global_100m_10daily_v1_cog` | 0 | Lake-water quality metadata supply no evidence of measurements of pollinator abundance or diversity. [CDSE collection](https://stac.dataspace.copernicus.eu/v1/collections/clms_lwq-nrt_global_100m_10daily_v1_cog) |
| 20(1)(g) | `cmr:C2102656211-NOAA_NCEI` | 0 | Scuba fish-diversity surveys describe a different taxonomic group and study region. [CMR record](https://cmr.earthdata.nasa.gov/search/collections.umm_json?concept_id=C2102656211-NOAA_NCEI) |
| 20(1)(g) | `cordis:101042392` | 0 | The laboratory system covers a plant, herbivorous mites and predatory mites. The objective gives no evidence of pollinator surveys. [CORDIS DYNAMICTRIO](https://cordis.europa.eu/project/id/101042392) |
| 20(1)(g) | `cordis:101059418` | 0 | The project studies how bird species respond to environmental change. Its species-distribution topic does not establish pollinator monitoring. [CORDIS project](https://cordis.europa.eu/project/id/101059418) |
| 20(3) | `cdse:clms_lie_northernhemisphere_500m_daily_v1_cog` | 0 | The lake-ice dataset has a date range overlapping commencement. Its observable does not align with the cited provisions. [CDSE collection](https://stac.dataspace.copernicus.eu/v1/collections/clms_lie_northernhemisphere_500m_daily_v1_cog) |
| 20(3) | `cordis:101056931` | 0 | A 2024 transport conference shares the year. It offers no research method for the referenced monitoring obligations. [CORDIS TRA2024](https://cordis.europa.eu/project/id/101056931) |

## Baseline coverage gaps

- The official CLMS catalogue identifies the yearly 10 m European Tree Cover Density product. The 120 captured CDSE collections include no ID containing `tree-cover-density`. This example is outside the judged local pool. [Official CLMS product family](https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover?tab=tree_cover_density)
- CORDIS reports that PollinERA ran pollinator biodiversity surveys across European agricultural landscapes. Grant `101135005` appears at project data row 9,799 in the downloaded ZIP. The 1,000-project cap excludes it, so no ranker in this snapshot could return it. [CORDIS PollinERA reporting](https://cordis.europa.eu/project/id/101135005/reporting)
- The pool uses a single act and assigns all 44 queries to the test split. Some queries reference the same paragraph 1 points and differ mainly in scope or timing. Those queries form related groups for broader evaluation.
