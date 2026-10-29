# Project history and evidence preservation

## v0.12.0 - Support checks before handoff

API ticket-creation 401 incidents now offer three read-only checks when both pinned excerpts match reviewed digests. Each check has citations and a follow-up question. Answered checks retain the bounded conversation so support staff can report results. Deterministic outcome handling uses cached evidence without another model or retrieval call. Failed completed checks, lack of access, explicit escalation or the turn limit prepare a handoff including user messages and offered checks. Success is labeled user-reported, never a verified fix. Other workflows keep their evidence boundaries. No live model calls were made to implement or validate this release.

## v0.11.0 - Pending clarification context

The Web API keeps pending clarification context behind rotating opaque IDs. Replies restore earlier user messages; previous assistant questions are separate untrusted model context, never retrieval evidence. The UI adds Send reply, Conversation so far and New question. Memory is bounded to 15 minutes of inactivity, four user turns, 6,000 composed characters and 128 pending entries per process. Completed requests clear context; explicit upstream failures preserve the earlier state for manual retry. Tests cover isolation, reset, expiry, concurrency, budgets and mock Gemini payloads. No live model request was made to implement this feature.


## v0.10.0 - Model-assisted intent fallback

Rules remain first. Ambiguous automatic routes optionally use one structured Gemini decision. Code controls all tools and keeps the original question, repository and version unchanged. Clarification and out-of-scope decisions stop before retrieval and answer synthesis. Usage is recorded separately in intent_generation. Known bare-error clarifications remain model-free; offline mode is unchanged. New classifier behavior is mock-tested, not live-evaluated. A basic live synthesis smoke test succeeded before this change on 2026-10-29; it does not validate the classifier.


## 2026-10-29 - Clarify unscoped error reports

The user-reported question `it occurs a 401 error` previously retrieved several unrelated error branches and proceeded to generation and engineering review. Automatic routing now asks for the affected workflow first, returning `needs_clarification` / `missing_error_context` without retrieval or a model call. Named workflows and explicit engineering targets still proceed. Clarification remains stateless; resubmit the original error with added context. Validation: 182 tests passed, including tool/model non-invocation and resubmission regressions. No live model call was needed for this fix.

## v0.9.0 - Support staff workflow

The UI now accepts only a question. Retrieval and answer mode are automatic. Business-context clarification replaces asking staff to select documentation or code. Technical metadata is collapsed, and unresolved requests can download a local engineering handoff. Code-location success remains distinct from incident resolution. API overrides remain for developers; offline regression runners explicitly disable model generation.

Gemini prompts target support staff. A hidden-input PowerShell launcher supports an operator-confirmed Free Tier project without storing keys. No live API call or entitlement verification has been performed. Work scenarios remain in the README, not on the input screen. Earlier validation artifacts are retained unchanged.

## v0.8.0 — English workspace

UI, API messages, traces, curated document summaries, Gemini instructions, examples, tests and documentation are English. Agent names are Support System Agent and Code Analyzer. The active document corpus has a new `en-v2` version and hash. Official source URLs, source HTML hashes and pinned code remain unchanged.

English intent rules replace the previous Chinese cues. Evaluation questions are translated development adaptations with new hashes. Their results must not be compared as controlled improvements over Chinese scores. Original third-party code is kept exact, including any non-English content in upstream excerpts.

The [pre-English archive](archive/pre-english-v07.zip) preserves prior documentation, screenshots, corpora, evaluation cases, protocols and reports byte-for-byte. Its `manifest.json` contains a SHA-256 for each archived file. Historical Chinese content is retained only as historical evidence, not as the current UI or documentation. Original acceptance scores remain 6/8 and 10/12; no report has been relabeled as an English acceptance result.

## Earlier releases

- v0.7.0: optional Gemini HTTP synthesis adapter, local configuration endpoint, mocked tests and opt-in live smoke commands. No live model evaluation.
- v0.6.1: improved Chinese document intent recognition and ambiguous-query clarification. 107 tests; 18/18 development regressions. The new same-author acceptance set first scored 10/12; two paraphrases remained unresolved.
- v0.6: reviewed official-document corpus, explicit version boundaries and independent combined retrieval. The first same-author acceptance run scored 6/8. Its failures were later reclassified as development cases.
- v0.5: focused the application on support-system documentation and code, removing the unrelated travel-policy branch. Legacy policy request fields return 422.
- v0.4: bounded declaration excerpts and explicit context completeness.
- v0.3: real File Search MCP integration.

The earlier travel-policy demo is recoverable from Git commit `89a0493`, tagged `archive/travel-demo-v0.4`. It is not the current project scope. The local directory name may still reflect that origin.
