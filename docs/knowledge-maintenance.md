# Reviewing and extending the corpus

1. Open each official URL in `knowledge/peach.json` and inspect the named section. Review linked qualifications and booking-channel restrictions. Do not treat a crawl date as the policy effective date.
2. Compare the local Chinese paraphrase with the source. Correct it without copying an entire article. Keep source IDs stable when the same fact group remains; use a new ID for a new fact group.
3. Confirm that metadata matches the paragraph: topic, fare family and source document. The first version has one canonical paragraph per topic/fare; split new subtopics in the schema/router rather than adding unrelated paragraphs to the same group.
4. Set `reviewed_at` only after actually reviewing that source. Bump the corpus version. Never extend freshness by merely changing the date or the review window.
5. Update expected outcomes in `evals/cases.json` only when evidence justifies the policy change. Add negative cases for newly discovered exceptions. Manually assess whether the cited source supports each summary.
6. Run `python -m pytest -q` and `python -m evals.run`. The evaluator uses a fixed reference date, so intentionally update its reference date and tests when releasing a newly dated corpus. Inspect both the source diff and the resulting report before updating `evals/baseline.json`.

The corpus is read on each retrieval, so a saved update is visible without rebuilding an index. Invalid JSON, non-official source URLs and invalid references produce a storage error. Empty retrieval is evidence insufficiency. Divergent paragraphs sharing one applicability group are treated as conflicts until reviewed.

## Source interpretation notes

- The carry-on page's English size wording says “less than 115 cm”. The summary preserves this boundary rather than silently changing it to an inclusive limit. This is a translation/interpretation point to verify before expanding individual baggage eligibility checks.
- The checked-baggage page distinguishes ordinary limits from overweight and oversize options. The summary does not claim that every bag outside ordinary limits is prohibited.
- Voluntary cancellation summaries omit numeric fees and exact refund calculations because the amount depends on more conditions than this demo models.
- The source pages may link to disruption policies, special-item policies and agent-booking procedures. A link existing on a page does not mean that the linked policy is covered by this corpus.

## Failure demonstration

The real store-failure path is exercised by API tests using a temporary missing file. To reproduce manually in a separate terminal, start a second server with an invalid path:

```powershell
$env:TRAVEL_OPS_KNOWLEDGE_PATH = 'knowledge/missing-demo.json'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --log-config logging.json
```

Ask a supported question such as `Peach 手提行李重量限制？` at port 8001; it returns HTTP 503 with `upstream_error`. Questions rejected before retrieval may still return clarification or scope refusal. Stop the second server with Ctrl+C, then restore the shell:

```powershell
Remove-Item Env:TRAVEL_OPS_KNOWLEDGE_PATH
```

This is an actual failed dependency read, not a canned public “simulate error” switch.
