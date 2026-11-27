# Verification reports

`release_checks.json` records local builds and Edge sessions from 26 and 27 November 2026. The first browser timing includes asset loading. Site sizes are uncompressed. The report compares browser and Python results on the specified queries and corpus. Relevance studies have separate protocols and reports.

[`article20_agreement.json`](article20_agreement.json) contains the aggregate model judgments and source report hash for the Article 20 pilot, with the matching source snapshot and public corpus hash.

[`article20_comparison.json`](article20_comparison.json) records both rounds of model judgments and binds the comparison to the revised release. It includes empty slots separately from rated search results.

[`article20_coverage.json`](article20_coverage.json) records which original cases supplied candidates and the model-reviewed results for ten frozen unseen questions. The aggregate is bound to the expanded release.

[`free_text_comparison.json`](free_text_comparison.json) compares the earlier and revised browser releases on six topical questions and two domain controls. It records query-level relevance, unrelated results, empty results and the provenance of the paired model review. The report records the revised release ID, snapshot and corpus hash. [Free-text comparison](../docs/verification.md#search-quality)

`policy_product_checks.json` compares recovery of 13 known source records across two public releases and a local passage experiment. `generation_checks.json` records the local extraction and RAG runs. `policy_brief.json` preserves the source-linked statements displayed for the matching assessment. [Policy-to-product report](../docs/policy_assessment.md)
