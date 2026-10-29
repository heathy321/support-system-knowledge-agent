# API and conversation contract


```json
{"question":"What information do we need to collect to create a ticket through the API?"}
```

Send to `POST /ask`. If the response has `conversation.state=awaiting_reply`, send the next message with `clarification_id` from that response. Treat the ID as a bearer capability; do not share it. `POST /conversation/reset` with that ID clears pending context. Unknown or expired IDs prompt a fresh complete question without retrieval or model calls. Original request settings are retained; explicit option changes require a new question. Optional `task` is `auto`, `documentation`, `code_analysis` or `combined`. Optional `file_path` is repository-relative. `repository` accepts only osTicket. `product_version` applies to documents, not the code snapshot. Unknown request fields are rejected. `answer_mode` defaults to `auto`: offline when the operator has not enabled Gemini, otherwise Gemini after successful retrieval. Explicit `offline` and `gemini` overrides remain for API clients and developer tests; these controls are not shown to staff.

| Status | Meaning |
|---|---|
| `answered` | Evidence was found; inspect claims and citations |
| `needs_clarification` | Missing intent, ambiguous target or conflicting context |
| `insufficient_evidence` | Uncovered topic/version or no matching evidence |
| `upstream_error` | Retrieval or generation failed; HTTP 503 |

`resolution` distinguishes guidance, missing context, `checks_available`, `resolved_reported`, engineering review and unresolved questions. Code-location success alone is not a resolved support incident. `support_checks` contains reviewed read-only steps with citation IDs; `follow_up_questions` asks for the error and results. An `answered` response can still have `conversation.state=awaiting_reply`. API clients must use conversation state, not answer status, to decide whether to retain the ID.

The first reviewed playbook covers **401 while creating an osTicket ticket through the API**: inspect the header, key activity/source IP, and ticket-creation permission. Both pinned code excerpts must match reviewed digests. A different snapshot, missing excerpt, provider failure or unsupported workflow does not produce these checks. No settings or tickets are changed. Other incidents retain conservative handoff behavior until they have reviewed checks.

Replies to offered checks use bounded deterministic rules and cached evidence, with no additional model or retrieval calls. A report that all checks were completed and the error persists, inability to inspect settings, an explicit escalation request, or the four-turn conversation limit produces a local handoff. Partial or ambiguous reports ask for details. `It works now.` closes as **user-reported**, never independently verified. These rules are not general language understanding; use New question for another topic. `handoff` packages the user messages, offered checks, escalation reason, retrieved references and limitations. It is downloadable and is never automatically sent.

Responses include claims, typed sources, request ID, latency, warnings, agent trace, repository/document provenance, branch outcomes and generation metadata. Code citations preserve exact source text with commit, path and line range. Document citations are reviewed English summaries, **not verbatim quotations**. Citation validation does not prove semantic entailment.

`GET /health` checks code and document readiness independently, returning 503 if either is unavailable. `/repositories` probes the configured code backend; `/documentation` lists corpus sources. `/agents` describes configuration. `/generation` checks local Gemini configuration only. None of these endpoints calls Gemini.

The `intent_generation` field records intent-classification usage separately from answer `generation`. A skipped answer generation does not mean no classifier call occurred. An ambiguous request can make at most two model calls: one classification, then one evidence-based answer. There are no automatic model retries.

## Conversation memory


Only pending clarifications and check-result follow-ups are stored, in one local server process (maximum 128). Check follow-ups also retain the earlier evidence and offered checks; they do not inspect the live installation. The browser keeps its token and visible messages only in page memory, not cookies or localStorage. Refresh starts a new conversation; unreachable server entries expire automatically. A new unrelated question must use **New question** while a reply is pending. There is no automatic topic-change detector or semantic correction merger.

Retrieval receives only combined user messages. Prior assistant clarification questions are passed separately to Gemini as untrusted context, never evidence. Original versions and restrictions are retained; conflicting details may still require a fresh summarized question. For an explicit upstream failure, the pending context survives so a manual retry does not duplicate the failed reply. Lost network responses can invalidate the old ID; the UI then requests a fresh question. IDs rotate after each successful clarification step. Concurrent replies to the same ID are rejected, and reset during processing cannot recreate the session.

This local demo has no login or shared database. It is designed for a single worker; multiple workers or a production deployment need an authenticated, shared session store. Stateless Python/CLI calls to CustomerSupportAgent remain supported; clarification memory is provided by the Web API wrapper.

See the [README](../README.md) for setup and the [demo](offline-demo.md) for the support workflow.
