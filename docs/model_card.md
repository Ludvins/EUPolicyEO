# Ranking model card

EUPolicyEO uses BM25 and MiniLM to find candidate research projects and Earth observation collections for EU monitoring requirements. The browser can fuse their rankings. The original law and provider records remain the evidence for interpreting each match.

## Rankers and scores

| Ranker | Method | Score |
| --- | --- | --- |
| **BM25** | NFKC normalization, lowercase Unicode letter and number runs, fixed stop words, positive Robertson IDF, `k1=1.2`, `b=0.75`. Equal scores use stable IDs. | A query-relative term match score. Larger values have greater lexical relevance. The score has no fixed upper bound. |
| **MiniLM** | Pinned fp32 ONNX encoder, maximum 256 tokens, attention-mask mean pooling and L2 normalization. Long inputs use the start of the token sequence. | Raw cosine similarity in the range −1 to 1. Larger values indicate closer vector directions. |
| **Browser hybrid** | Reciprocal rank fusion of up to 60 eligible results from each ranker, with rank constant 60. The BM25 list contributes only positive-score results. | Sum of the two reciprocal rank contributions for that record. |

BM25 assigns positive scores to exact normalized-token matches. The eligibility rules below can admit zero-score results. Score differences depend on the query, ranker and corpus. Treat the scores as ranking signals and verify the match against its original source. [Retrieval implementation](../src/eupolicyeo/retrieval.py) · [Pinned MiniLM model](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/tree/1110a243fdf4706b3f48f1d95db1a4f5529b4d41)

## Local and browser variants

The local rankers use the normalized snapshot. Publication applies a field allowlist, topic quotas and source caps, then builds indexes and document vectors for the resulting public corpus. The browser worker encodes queries with the same MiniLM graph using single-thread WASM. Model and query processing stay in the browser. The release records the parent registry version, snapshot hash, encoder revision and public corpus hash. [Architecture](architecture.md) · [Data sources](data_sources.md)

For legal presets, documented direct measurements and research methods come first, followed by documented supporting context and catalogue term matches. Within each group, the selected ranker uses its original score and stable ID ties. A documented result can have a zero BM25 score when its indexed fields share no query tokens. The evidence note links to the source used to establish the result's role.

The free-text evidence policy checks candidate support before BM25 or cosine ordering. It removes generic request words and normalizes simple plurals. A single informative term needs one match. Queries with two to four informative terms need two distinct matching forms. Longer queries need three matching forms or two neighboring query terms. The check can miss relevant records described with different terminology. [Retriever](../src/eupolicyeo/retrieval.py)

Semantic results offer an optional two-dimensional PCA view of the query and currently returned document vectors. It is a projection of the displayed sample. The result order and similarity scores use the original embedding dimensions.

## Validation

| Check | Evidence |
| --- | --- |
| Tokenization, filters and lexical parity | The verified browser build matched Python on 67 cases, including temporal and antimeridian examples. |
| Dense execution and parity | The browser ran MiniLM on 21 probe queries. Mean top-10 set overlap with Python was 1.0 across 42 query–corpus comparisons. The browser fell back to keyword search after a failed model fetch. |
| Local deployment | The Compose API served registered versions before promotion, after promotion and after rollback. The API reported the loaded version and metrics identified invalid requests. |
| Pilot judgments | Two rounds used 20 model reviews each and six matching legal passages. The results distinguish judged candidates from unfilled slots. [Pilot comparison](../reports/article20_comparison.json) |
| Evaluation scope | The original 44-query pool contains 400 candidate pairs for annotation. The reported relevance studies use model judgments, and the known-record study measures retrieval of specified source records. [Evaluation methods](verification.md#search-quality) |

Browser parity verifies implementation agreement. Local benchmark timings measure the tested workload and platform. [Run evidence](verification.md) · [Initial extraction and candidate diagnostics](benchmark-notes.md)

## Limitations and reuse

- The demonstration focuses on one article. Article 20 timing clauses and optional provisions need additional review. The ranking can return plausible but tangential matches.
- The local and public corpora differ in coverage and fields. Programme, catalogue and record caps can exclude a relevant project or collection. Geographic and temporal compatibility describe the metadata in the selected release.
- The browser uses Hugging Face Tokenizers.js and ONNX Runtime Web. The semantic archive includes the model's Apache-2.0 license. The static distribution includes the browser runtime notices. [Data and model terms](data_sources.md)

For review labels, follow the [annotation guide](../eval/annotation_guide.md).
