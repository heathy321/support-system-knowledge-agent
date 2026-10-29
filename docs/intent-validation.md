# English migration validation

Verified on 2026-10-28: **155 tests passed**, **18/18** English support cases, **20/20** English code cases and local/MCP parity, and **3/3** Gemini dry runs without model requests. A new local environment passed the locked dependency installation, `pip check`, 155 tests, index rebuilding and actual MCP smoke flow. The repository was cloned locally from existing public Git objects; a fresh GitHub download and live Gemini were not tested. One existing Starlette TestClient/httpx deprecation warning remains.

See [machine-readable validation](validation-v08.json), [English support baseline](../evals/support-v08-en-mcp-baseline.json) and [English code baseline](../evals/code-v08-en-mcp-baseline.json).

v0.8.0 replaces Chinese user-facing content and routing cues with English. Scope checks, status contracts, citation integrity and no-cost offline behavior are retained. Code search now removes English question scaffolding and prioritizes explicit identifiers over broad concept aliases.

The active suites contain 18 support/document cases and 20 pinned-repository code cases, adapted into English from the earlier development suites. They are same-author development regressions, not blind or independent benchmarks. Translation changes the inputs and their hashes; historical Chinese percentages are not directly comparable.

Regression coverage includes all six documented topics, ambiguous routing, unsupported versions/topics, explicit code identifiers, exact status codes, unknown symbols, combined-evidence completeness and local/MCP parity. Localization tests check English output paths and scan active project text for untranslated Chinese. Code excerpts remain exact upstream evidence.

Gemini tests use mocked HTTP responses and prohibit real HTTP transport. The prompt requires English output even if the question asks for another language. A CJK-ideograph check rejects Chinese generated claims with `llm_output_language_error`; this is not a general English-language classifier or a semantic correctness check. No real model evaluation is included.

Run the commands in the [README](../README.md#validation). Current results and their case/corpus hashes are recorded separately from the historical archive.

## Historical evidence

The [pre-English archive](archive/pre-english-v07.zip) retains the original 6/8 and 10/12 first acceptance reports, their frozen cases/protocols and prior baselines. Manifest checks test that the stored bytes are unchanged. The current evaluator only runs the development suite; it does not overwrite archived acceptance results.
