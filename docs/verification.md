# Verification

The browser release uses a bounded snapshot of the English Article 20 text, 400 EO collections and 1,000 Horizon Europe projects. The local pipeline replays hashed source responses, validates extracted legal spans and writes normalized JSON and Parquet tables. The GitHub Pages workflow checks the data archive and code revision before it builds and runs the browser tests. [Deployment guide](deployment.md) · [Data sources and reuse](data_sources.md)

## Operational checks

| Check | Recorded result |
| --- | --- |
| Local pipeline | Offline replay reproduced the canonical JSON and Parquet byte for byte. The larger source snapshot contains 741 collections, 10,000 projects and 29 extracted legal entries. |
| Registry | A local Compose run served MLflow versions 3 → 4 → 3. FastAPI reported the loaded version, and Prometheus recorded a healthy scrape and a rejected request. |
| Browser reference tests | The Edge worker matched Python on all 67 BM25 cases and all 42 MiniLM query–corpus top-10 lists, of which 25 returned results. |
| Local ranking latency | Warm in-process p95 was 2.15 ms for BM25 and 6.69 ms for MiniLM over 84 calls per ranker in the expanded run. The measurements exclude HTTP transport. |

[Build and browser measurements](../reports/release_checks.json) · [Ranking model card](model_card.md)

## Search quality

The controlled known-record test asks whether each query retrieves a specified source record in the top five. The browser found 9 of 13 with BM25 and 10 with MiniLM or hybrid search. The local passage experiment found 12 using richer archived fields and a separate ranking procedure. Three known targets remained outside the browser's top five for MiniLM and hybrid search. [Known-target queries](../eval/policy_product_targets.json) · [Results and scope](policy_assessment.md#search-changes-and-measured-results)

The separate free-text comparison pooled results from six topical questions and two domain controls. Model reviewers found fewer unrelated results under the revised filter, while the number of topical questions with a direct result in the top three stayed at one of six for both rankers. The revised semantic ranker also lost a partial match. These are model judgments from a small sample. [Free-text aggregate](../reports/free_text_comparison.json) · [Other evaluation reports](../reports/README.md)

## Policy-to-product assessment

The Andalusia case links Article 20(1)(b) to two indicators and four Copernicus products. A bounded STAC check found three intersecting 10 m Tree Cover Density item envelopes in each year from 2021 to 2024. Envelope overlap supports availability screening. Local accuracy and complete coverage require additional evidence. The example reporting brief cites the source records used for its four claims. [Assessment evidence](policy_assessment.md#andalusia-case) · [Generation checks](../reports/generation_checks.json)
