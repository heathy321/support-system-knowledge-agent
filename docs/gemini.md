# Optional Gemini integration

The Gemini Developer API adapter passed a live documentation-answer smoke test on 2026-10-29. General quality and billing entitlement remain unverified. The new intent classifier has mocked integration coverage but has not been live-tested. English is required for claims and clarifications. Code controls tools and validates model route decisions; answer synthesis still requires successful retrieval.

## No-cost validation

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.try_gemini
.\.venv\Scripts\python.exe -m evals.run_gemini --limit 3
```

The last two commands default to dry runs: retrieve evidence, build a payload and check its character budget. No key is read, no Google request is sent and no model answer is fabricated. The three cases cover documentation, code and combined evidence; the latter two require the local index. Add `--backend mcp_stdio` for real MCP retrieval. CLI defaults to `local`; Web defaults to MCP.

Tests use `httpx.MockTransport` and forbid real HTTP transport. They cover successful responses, schema/citation failures, abstention, Chinese-output rejection, truncation, timeouts, rate limits, authentication/upstream errors, redirects and size limits. They do not establish semantic entailment, prompt-injection resistance or live model quality.

## Free Tier setup for the local support UI

The configurable default is `gemini-3.5-flash-lite`. The [official model page](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) describes a low-cost model with structured output; the [lifecycle page](https://ai.google.dev/gemini-api/docs/deprecations) recommends this series for new projects (checked 2026-10-28). Availability and billing depend on your account and [current pricing](https://ai.google.dev/gemini-api/docs/pricing). No free quota is guaranteed.

For the no-spend workflow, use a project marked **Free Tier** in [Google AI Studio](https://aistudio.google.com/). Do not enable paid billing. The [pricing page](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.5-flash-lite) lists free input/output for this model on Free Tier (checked 2026-10-28), subject to account availability and quotas. Free-tier content may be used for product improvement; use public or synthetic questions only. A model name or working key does not prove free-tier entitlement.

Run from the project directory (the launcher replaces only a verified server belonging to this project):

```powershell
.\start-gemini.ps1
```

The script asks you to confirm Free Tier and enter the key at a hidden prompt. It starts the localhost server with `gemini-3.5-flash-lite`, keeps the key in process memory/environment, and restores previous environment values when it exits. It saves no key to disk. Startup and page load make zero model requests. Ask one supported question to test. The application cannot verify billing entitlement from your key; the operator must check the console. There is no paid-model fallback or automatic retry. A 429 is surfaced and does not trigger another request.

### Manual configuration for CLI testing

`.env.example` is a template; `.env` is not auto-loaded. Keep keys out of Git and the browser. In PowerShell:

```powershell
$env:ENABLE_GEMINI = '1'
$env:GEMINI_MODEL = 'gemini-3.5-flash-lite'
$env:GEMINI_MAX_OUTPUT_TOKENS = '1024'
$env:GEMINI_TIMEOUT_SECONDS = '20'
# Hidden prompt keeps literal key text out of command history.
$geminiSecret = Read-Host 'Gemini API key' -AsSecureString
$geminiPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($geminiSecret)
try { $env:GEMINI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($geminiPointer) }
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($geminiPointer)
    $geminiSecret.Dispose()
    Remove-Variable geminiSecret, geminiPointer
}
```

Run a dry run first. After checking the key belongs to your Free Tier project, explicitly opt in to one real call:

```powershell
# At most one model request, no automatic retries.
.\.venv\Scripts\python.exe -m scripts.try_gemini --live
# Optional bounded suite: 1–3 requests, stopping after the first failure.
.\.venv\Scripts\python.exe -m evals.run_gemini --live --limit 1
```

Live smoke reports go to ignored `evals/gemini-live-latest.json`, separate from offline regressions and archived acceptance reports. Operational success is not semantic accuracy. Model name, evidence provenance, generation latency and reported usage are retained; missing token fields stay null, not zero. Billed cost is not estimated.

Restart the Web server from the configured terminal and submit a question. The system chooses the answer mode automatically. `/generation` distinguishes configured status from a tested connection; page load and health/configuration checks never call the model. Disable `ENABLE_GEMINI` and restart to return the UI to offline answers.

This demo has no user authentication or global spending quota. Keep a key-enabled server bound to `127.0.0.1`. After testing, stop it and clear the terminal configuration:

```powershell
Remove-Item Env:GEMINI_API_KEY -ErrorAction SilentlyContinue
$env:ENABLE_GEMINI = '0'
```

## Request and response behavior

```json
{"question":"Which fields are required to create a ticket through the API?","task":"documentation","answer_mode":"gemini"}
```

Generation needs an enabled server, valid configuration and an `answered` retrieval result. Default `answer_mode=auto` follows the operator configuration; explicit `offline` never calls the model. Explicit `gemini` remains available for developer API clients. Otherwise retrieval status is preserved with `generation.status=skipped` and no call. The model may return insufficient evidence. Every generated claim must reference existing source IDs; combined answers must cite both evidence types. The app constructs the answer from validated claims and never accepts model-generated source URLs.

`generation` records backend, status, model, latency and provider-reported tokens. `mode` still identifies the retrieval route. Combined `branches` describe retrieval outcomes even if generation subsequently fails. Errors clear answer, claims and sources; no offline success is substituted. `retryable` informs a manual decision, not an automatic retry.

| Condition | Status / reason |
|---|---|
| Explicit Gemini when disabled, or enabled Gemini with missing key/invalid settings | `upstream_error` / `llm_not_enabled`, `llm_missing_key`, `llm_invalid_config` |
| Generated claims validated | `answered` / `llm_generated_from_evidence` |
| Model abstains | `insufficient_evidence` / `llm_insufficient_evidence` |
| Invalid structure/citations or missing evidence type | `upstream_error` / `llm_invalid_output`, `llm_invalid_citations`, `llm_incomplete_evidence_coverage` |
| Chinese generated claims | `upstream_error` / `llm_output_language_error` |
| Timeout, connection, throttling, server error | `upstream_error` / `llm_timeout`, `llm_connection_error`, `llm_rate_limited`, `llm_provider_error` |
| Auth, unknown model, rejected request | `upstream_error` / `llm_auth_error`, `llm_model_unavailable`, `llm_request_rejected` |
| Blocked, truncated, unexpected response | `upstream_error` / `llm_blocked`, `llm_output_truncated`, `llm_invalid_response` |
| Input/response budget exceeded | `upstream_error` / `llm_input_budget_exceeded`, `llm_response_too_large` |

## Implementation limits

- Uses the official [generateContent REST API](https://ai.google.dev/api/generate-content), `x-goog-api-key` header, `responseMimeType` and `responseJsonSchema`. Basic answer synthesis has been smoke-tested live; the new intent schema remains untested against the live provider. No Vertex AI or OpenAI-compatible gateway.
- Intent classification sends the composed user question and fixed scope instructions. During a pending clarification, both classification and answer synthesis also receive the bounded prior user messages and assistant clarification questions as untrusted context. Answer synthesis additionally receives selected public evidence and scope. No complete repository, prior generated answers or environment variables are sent. The key is not sent to MCP; logs omit questions, headers and raw provider error bodies.
- At most one intent request for unrecognized automatic routes plus one answer-synthesis request after successful retrieval. Explicit routes skip intent classification. Each request has one candidate and no retries. Intent output is capped at 512 tokens (or the smaller configured ceiling). Default output ceiling 1024 tokens, configurable 128–2048; input JSON ceiling 48,000 characters; response ceiling 128,000 bytes. Character limits are not precise token or monetary limits.
- Network deadline defaults to 20 seconds, configurable 1–30. No redirects or system HTTP proxy settings; direct API connectivity is required.
- Format and citation validation do not prove semantic correctness. The language guard detects CJK ideographs, not every non-English sentence. Original code evidence is preserved verbatim.
- No model tool loop, vector retrieval, external search or vendor file search. Classification may select an allowlisted route but cannot rewrite queries, change versions or invent evidence. Retrieval can still fail after a valid route decision.

Accurate portfolio description: **Offline-first English support assistant with real MCP retrieval, an optional Gemini synthesis adapter, mocked integration tests and an opt-in live smoke workflow. Live model quality and cost have not yet been evaluated.**

## Intent fallback (v0.10.0)

Only ambiguous automatic routes use Gemini intent classification. Explicit API routes, known scope guards, the bare-error clarification guard and offline requests bypass it. Decisions are limited to documentation, code_analysis, combined, needs_clarification, outside_scope and insufficient_evidence. Extra keys, unknown routes and inconsistent clarification fields fail closed. Schema and language checks are not semantic or prompt-injection guarantees.

`intent_generation` records classifier status, model, latency and provider token usage separately from answer `generation`. Thus `generation.status=skipped` may coexist with a completed intent call. Sum reported token counts across both fields; null usage is not zero. Intent errors return `upstream_error`, stop the flow and never trigger a retry.

The prompt asks the classifier to disambiguate ticket bookings from osTicket support cases. A clarification produces no business answer and no sources. The Web UI retains pending clarification context: reply with only the missing details. CLI calls remain stateless. The default CLI task is documentation (one call); `scripts.try_gemini --live --task auto` can make two calls. The fixed three-case smoke suite uses explicit routes and remains limited to one call per case.
