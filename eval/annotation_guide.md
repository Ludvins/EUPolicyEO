# Article 20 benchmark annotation

Keep the original snapshot and candidate pool immutable. Run the commands below with a completed snapshot ID and copy the three JSONL files to `artifacts/reviewed-annotation` for reviewer edits before evaluating.

```bash
uv run eupolicyeo annotation-pool --snapshot "$SNAPSHOT" --output artifacts/annotation
uv run eupolicyeo evaluate --snapshot "$SNAPSHOT" --ranker bm25 --annotations artifacts/reviewed-annotation
```

Read the official act and parent lead-in. Verify evidence offsets in the stored normalized section, actor/modality, action, observable and conditions. Use stable requirement IDs. Record reviewer and set reviewed only after human inspection. Add counterexamples and omitted source evidence when appropriate.

For each corpus, judge direct source evidence as 2, thematic or incomplete evidence as 1, and irrelevant evidence as 0. Leave uninspected pairs null. For each reviewed query and relevance judgment, complete the review fields, including the reviewer and supporting reason and source link where required. Include weak or underspecified queries and expand the pool with independently discovered records present in the chosen corpus. Record excluded relevant records in a coverage note. Treat Article 20 siblings as a single scope and avoid tuning on the test queries. Expand to a different held-out article or act before making generalization claims.

## Public search holdout

The [frozen questions](holdout_queries.json) were defined before retrieving results for this holdout. There are five Earth observation questions and five project questions, including one out-of-domain control and two questions with explicit collection filters. These are free-text questions on Article 20-adjacent topics.

Serve the built release locally and set `RELEASE` to the matching bundle directory containing `manifest.json`. The capture verifies the release and takes up to five candidates each from keyword and semantic search. The worksheet deduplicates and shuffles the candidates. The capture defaults to Microsoft Edge. To use Playwright Chromium, install it and set `E2E_CHANNEL=chromium`.

```bash
node web/scripts/capture-holdout.mjs --release "$RELEASE"
uv run python scripts/holdout_review.py prepare --release "$RELEASE"
```

Open `artifacts/coverage-evaluation/human-review.html`. Rate each record after checking its official source. Add a brief reason and finish a question’s candidate list before moving on. Download judgments to save progress at any time. The form can restore a saved export from the same packet.

```bash
uv run python scripts/holdout_review.py score --judgments /path/to/holdout-judgments.json
```

Scoring counts direct matches in the top three and questions with useful evidence in the top five, using only fully judged questions. Empty returns are counted across all frozen questions. The worksheet, ranking audit and human judgments stay local under `artifacts/coverage-evaluation/`. If you supply a different `prepare --output` directory, pass its `review-packet.json` to `score --packet`. The optional capture flag `--hybrid` records hybrid results for separate analysis.

## Paired free-text release comparison

The [frozen comparison questions](search_quality_queries.json) include eight topical questions and two out-of-domain controls. Both releases use the same archived source snapshot. Set `BASELINE` and `CANDIDATE` to the two bundle directories. Run each capture while its release is staged and served by the local preview.

```bash
QUESTIONS=eval/search_quality_queries.json
RUN=artifacts/relevance-comparison
node web/scripts/capture-holdout.mjs --questions "$QUESTIONS" --release "$BASELINE" --output "$RUN/baseline-rankings.json"
node web/scripts/capture-holdout.mjs --questions "$QUESTIONS" --release "$CANDIDATE" --output "$RUN/candidate-rankings.json"
uv run python -m eval.search_quality prepare --questions "$QUESTIONS" --baseline "$BASELINE" --candidate "$CANDIDATE" \
  --baseline-rankings "$RUN/baseline-rankings.json" --candidate-rankings "$RUN/candidate-rankings.json" \
  --output "$RUN/review" --blind-case-ids
```

Pass each model reviewer only their bucket file from `$RUN/review/`. The packet contains source evidence for the shared top-five pool and withholds both releases’ rankings. Save three independent, complete ballots per bucket in `$RUN/review/votes/`. Each ballot needs a unique `reviewer`, the exact `bucket` name, and a `ratings` object keyed by pair, with an integer `label` and a short evidence `reason` in every entry.

```bash
uv run python -m eval.search_quality score --output "$RUN/review" --votes "$RUN/review/votes"
```

A pair reaches consensus when two or more reviewers agree. Relevance metrics count only topical questions with a resolved judgment for every pair in their shared pool. Empty topical returns and both controls are reported separately. The report records model judgments and zero human judgments.

The [confirmatory questions](search_quality_confirmatory_queries.json) freeze six different topical queries and two controls. Use that file as `QUESTIONS` for both captures and packet preparation, with a new `RUN` directory. Preserve the capture files and runtime hashes. When reconstructing the baseline with a later build, verify the original ranking IDs, order, scores and compatibility before capturing the confirmatory answers.
