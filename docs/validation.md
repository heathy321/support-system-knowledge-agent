# Initial validation — 2026-10-26

- Python 3.12 in a project-local virtual environment; exact dependencies in `requirements.lock`.
- `python -m pytest -q`: 63 passed. One upstream deprecation warning: Starlette's TestClient warns about the HTTPX integration. No warnings are suppressed.
- `python -m evals.run`: 36/36 cases passed. Exact case/corpus hashes and metrics are in `evals/baseline.json`. This is a small hand-authored regression set, not a held-out benchmark.
- `node --check app/static/app.js`: passed.
- Local server: Uvicorn bound to `127.0.0.1:8000`.
- Browser: checked the workspace at a narrow 600-pixel viewport; confirmed carry-on response/citation, missing-context clarification, disruption refusal, catalog links, Standard Plus change response and JSON view. Captured the actual result in `demo.png`.
- API tests cover actual unreadable storage returning HTTP 503, malformed corpus metadata, input validation, source/claim linkage and review-window boundaries.
- Git repository initialized on `main`; no remote or commit configured. `.venv`, `.env` and generated evaluation output verified ignored.
- GitHub CI is prepared but not executed remotely. Public deployment, real model integration, a wide-viewport visual review and production load/security testing are not part of this local validation.

The preview server is stopped after verification. See the startup commands in `README.md` or `开始使用.md` to run it again.

## Conversational follow-up — 2026-10-27

Four suggested challenge prompts were added to the regression set after the user reported results consistent with missing colloquial intent and generic multi-fare clarification. The original implementation failed the refund/rescheduling cases and the explicit conflict reason. The disruption refusal was already correct.

- Recognize limited ticket-refund and flight-date paraphrases without inferring fare family or cancellation reason from vague language.
- Distinguish conflicting passenger and booking-record fare reports from ordinary fare comparisons; request source verification without selecting either report automatically.
- Support fare names immediately adjacent to Chinese characters.
- Add API tests for missing-slot preservation, resubmission with confirmed context, fare-conflict wording and unrelated phrases that must not become flight-change answers.
- `python -m pytest -q`: 77 passed; the existing upstream deprecation warning remains.
- `python -m evals.run`: 40/40 passed; report saved in `evals/paraphrase-baseline.json`. Corpus and frozen evaluation date remain unchanged.
- No UI or knowledge-content changes. No live user server was stopped or restarted; restart Uvicorn to load the router changes if it was launched without `--reload`.
