# Article 20 policy-to-product assessment

The explorer links Article 20 monitoring provisions to EO catalogue searches. It can screen the returned collections in the browser. The reproducible Andalusia worked example also draws on item-level evidence archived by the local stack. [Legal text](https://eur-lex.europa.eu/eli/reg/2024/1991/oj/eng#art_20)

## Interactive assessment

Choose an Article 20(1) monitoring provision and run the search. **Assess these collections** appears when the search returns EO records. The matrix preserves the returned EO collection list and order. Each product opens the same source record shown in search.

Choose direct measurement or allow documented supporting context. You can also set a maximum spatial resolution, a bounding rectangle and UTC dates. Area and dates start with the search filters. Editing assessment criteria screens the same candidate set, and editing the search clears the previous assessment.

The browser scopes collection searches for Article 20(1)(a), (h), and (j) before ranking. It prioritizes documented uses, excludes reviewed records outside the monitoring scope, and requires both topic concepts to match a collection title or measured variable for other candidates. For Article 20(1)(h), NASA's GLanCE land-cover maps provide historical context for identifying possible habitats. The USGS campground study is excluded because its observations cover a site in North Carolina. [NASA GLanCE](https://doi.org/10.5067/MEaSUREs/GLanCE/GLanCE30.001) · [USGS study](https://pubs.usgs.gov/of/2004/1073/)

The screen uses the release's documented evidence links, catalogue fields and provider records checked for specific provision–collection pairs. A direct measurement describes a specific contribution to the provision.

Catalogue overlap provides partial evidence for area and dates. Missing metadata or a missing documented contribution produces an unknown criterion. The overall result reports the first applicable outcome in this order **Fails**, **Unknown**, **Partial**, **Meets**. Open **Evidence by collection** for the reasoning and sources. Review local accuracy and individual observations before relying on a result for reporting.

## Andalusia case

The example screens an Andalusia bounding rectangle across 2021–2024, using annual observations, raster resolution of 20 m or finer, and a vector mapping unit of 0.25 ha or smaller. Those are analyst-selected criteria. The legal panel separately gives the Article 20(1)(b) passage, the commencement and monitoring cycle, and the obligation to use mapped urban ecosystem areas. The four screened Copernicus products have seven evidence-linked criteria for each of two indicators. [Article 8](https://eur-lex.europa.eu/eli/reg/2024/1991/oj/eng#art_8) · [Article 14](https://eur-lex.europa.eu/eli/reg/2024/1991/oj/eng#art_14)

- **Tree canopy.** The 10 m product measures fractional tree crown cover and passes the resolution screen. The result is partial because urban boundaries, coverage completeness and local accuracy still require evidence. The 100 m aggregation fails the selected raster-resolution criterion.
- **Green space.** Urban Atlas offers useful input classes. The example still requires a defensible vegetation and inland-water class mapping, the correct urban boundaries, and evidence at the selected annual cadence.
- **Observed availability.** Four collection requests and four bounded item requests returned HTTP 200. The item check verified three intersecting item envelopes per year for the 10 m product, with 12 in total. The search checked envelopes. The actual pixels and their validity are open evidence gaps. Raw responses and hashes are stored locally under `artifacts/article20-assessment/provider/`.

## Search changes and measured results

The Pages build added a controlled measurement vocabulary from archived STAC bands and CMR variable keywords. Both public runs used the same 400 collection and 1,000 project IDs, pinned encoder and ranking logic. The revised build added terms to 49 collections. The local passage experiment retained those same IDs and indexed the longer archived descriptions and objectives separately from titles, topics, and documented measurement terms. It kept the best matching passage per record for each ranker and merged the two ranked lists with reciprocal rank fusion.

The table reports a Python replay of the public records through rank 50 and the local passage experiment. The browser returns up to ten records per corpus.

| Known-item result | First result | Top five | Top 50 |
| --- | ---: | ---: | ---: |
| Earlier public keyword | 5/13 | 6/13 | 8/13 |
| Revised public keyword | 6/13 | 9/13 | 10/13 |
| Earlier public semantic | 5/13 | 8/13 | 8/13 |
| Revised public semantic | 5/13 | 10/13 | 10/13 |
| Local passage hybrid on the same IDs | 10/13 | 12/13 | 13/13 |

The revised public rankings put the 300 m chlorophyll-a family fifth in keyword search and third in semantic search. The corresponding ranks for the 100 m floating cyanobacteria family were first and second. The tree canopy, mowing dates and Urban Atlas targets were outside the public top 50 for their paraphrased queries. Local passage search found those three first. The protocol measures recovery of specified source records. [Frozen known targets](../eval/policy_product_targets.json) · [Aggregate](../reports/policy_product_checks.json) · [Free-text relevance comparison](verification.md#search-quality)

Edge reproduced the revised top-five retrieval counts and found 10 of the 13 known targets in hybrid mode. Browser hybrid search fuses keyword and semantic rankings over public record fields. The local passage experiment uses fuller archived descriptions and objectives. [Browser verification](verification.md#search-quality)

## Inventory identity and refresh

The inventory resolver grouped 62 documented COG and NetCDF delivery families across 741 archived catalogue records and retained all 124 underlying records and provider identifiers. It kept different processing versions, grids and resolutions distinct. The replay found no shared CDSE–CMR dataset DOI in this snapshot. Eight sampled upstream collection requests returned HTTP 200 after provider retries.

The bounded live refresh reused checksum-verified legal and CORDIS inputs and refreshed CDSE and CMR. It received two HTTP 200 responses with 18 collections in 4.33 seconds including normalization and comparison. The smaller request scope excluded 723 earlier records from its results. The comparison marks those as outside the observed scope. The local evidence is under `artifacts/inventory-resolution/`.

The optional local model provides review advice for uncertain identity pairs. In a six-pair diagnostic it matched five source-based decisions. It proposed a historical Lake Water Quality equivalence without enough stable identity evidence. The resolver kept the pair unresolved and left authoritative membership unchanged. [Entity resolution](../src/eupolicyeo/entity_resolution.py)

## Local model and reporting brief

The legal model drafts structured requirements from the archived operative passage and its lead-in. Draft fields include source excerpts and offsets. The validator checks every quoted span against the supplied evidence. The existing rule-based extraction supplies the verified matrix. The reporting command retrieves a bounded set of legal, scenario, product and gap passages from that matrix, then asks the local model to generate individually cited claims.

The fixed legal diagnostic covered six passages and seven checks. The rules passed seven checks and local Qwen passed five. The model omitted part of the scope of Article 20(3), and the exact-span validator rejected its combined quotation for Article 20(11)(a). A separate qualitative check found that the model confused the subject with the actor in Article 20(4). The five span-validated passages took a median of 4.5464 seconds.

The example brief retrieved 13 passages and generated four claims in 14.6867 seconds. Eleven citations passed source-ID and exact-excerpt checks. The draft describes the legal requirement, a partial Tree Cover Density contribution, and evidence gaps. An unrelated train query returned insufficient evidence before model invocation. The Pages demo shows the draft for the matching assessment ID. [Generation checks](../reports/generation_checks.json) · [Displayed brief](../reports/policy_brief.json)

These commands use a running loopback Ollama service with `qwen3.5:9b` installed. The measured local model was Q4_K_M and occupied 6.59 GB. Pass `--expected-digest` to require a specific installed model digest. The browser release bundles only the pinned MiniLM retrieval encoder.

```sh
uv run eupolicyeo extract-with-llm --snapshot SNAPSHOT --section 32024R1991:eng:20:1:b --output artifacts/legal-draft.json
uv run eupolicyeo evidence-brief --assessment artifacts/assessment.json --question "What can EO contribute to urban canopy reporting in Andalusia, and what evidence is missing?" --output artifacts/evidence-brief.json
```

### Use a European language model

`--model` selects the locally installed Ollama model for legal extraction, catalogue pair review and evidence briefs. Ministral 3 8B Instruct from Mistral AI is an Apache-2.0 option. The Ollama package is approximately 6 GB. Use the same validation schemas and benchmark queries when comparing its output with the recorded Qwen run. [Mistral model documentation](https://docs.mistral.ai/models/ministral-3-8b-25-12) · [Ollama model tag](https://ollama.com/library/ministral-3:8b)

```sh
ollama pull ministral-3:8b
uv run eupolicyeo extract-with-llm --snapshot "$SNAPSHOT" --section 32024R1991:eng:20:1:b --model ministral-3:8b
uv run eupolicyeo evidence-brief --assessment artifacts/assessment.json --question "What can EO contribute to urban canopy reporting in Andalusia?" --model ministral-3:8b
```

The recorded generation checks and the example on the page identify Qwen as their source. The benchmark runner accepts the new model tag and its full digest from Ollama's model list. [Generation benchmark](../eval/generation_benchmark.py) · [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)

## Reproduce locally

The commands assume a completed snapshot. Replace `SNAPSHOT` and `RELEASE` with the local snapshot ID and a verified Pages bundle for that snapshot. Any files written under `artifacts/` are local outputs.

```sh
uv run eupolicyeo assess-urban --snapshot SNAPSHOT --output artifacts/assessment.json
uv run eupolicyeo discover --snapshot SNAPSHOT --browser-release RELEASE --corpus eo --query "Percentage of ground covered by tree crowns across Europe"
uv run eupolicyeo resolve-inventory --snapshot SNAPSHOT --output artifacts/inventory.json
uv run eupolicyeo refresh-inventory --previous SNAPSHOT --output artifacts/refresh.json
```

`GET /assessments/urban` serves the Andalusia matrix from the loaded registry model. `POST /assessments/urban` accepts a scenario with different bounds, years and thresholds for that case. Open **Worked example** from the browser navigation to view the archived matrix. [API and deployment guide](deployment.md)
