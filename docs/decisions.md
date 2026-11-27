# Implementation decisions

| Decision | Rationale |
| --- | --- |
| Store raw payloads with input digests | A reviewer can replay normalization and tie legal evidence or search records to exact source bytes. Replaying the two recorded snapshots reproduced the canonical outputs. |
| Scope legal-preset retrieval to observable metadata | Article 20 presets prioritize records with documented evidence roles and require each concept group to match for other catalogue candidates. Timing and procedure preserve the legal passage and can yield an empty recommendation. |
| Resolve the observed CELLAR redirect to HTTPS | CELLAR emitted an HTTP redirect to its own host. The adapter verifies the destination and retrieves the publication over HTTPS. Extraction accounts for `art_20` subdivisions and the observed lettered-point tables. |
| Record the CORDIS revision with the import | The Projects CSV ZIP is distributed through the official dataset. The published revision and local import timestamp describe separate events. |
| Preserve provider IDs and revisions | CDSE collection discovery returned pages of ten. CMR reports a response format version and per-record revisions. These details are useful for bounded replay and diagnosing changes in coverage. |
| Share the pinned ONNX graph and tokenizer | The official MiniLM export runs in both Python and the browser. A shared encoder and explicit probes make parity measurable. |
| Release a dedicated public corpus | Publication applies a field allowlist before building both indexes for the selected documents. Source and model attribution, corpus lineage and checksums travel with the bundle. |
| Keep the base map and city search local to the browser | A small Natural Earth overview handles the world view. Detail geometry and place names load on demand from the same origin. The map uses provider rectangles and the search filter's antimeridian rules. |

[Source contracts and reuse](data_sources.md) · [Architecture](architecture.md) · [Run evidence](verification.md)
