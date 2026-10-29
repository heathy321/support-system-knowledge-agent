# Publication preparation — v0.12.0

Checked on 2026-10-29. This record describes local preparation and the subsequent publication of the source repository to [heathy321/support-system-knowledge-agent](https://github.com/heathy321/support-system-knowledge-agent). No application was deployed; publishing the source does not host a server.

## Reviewer entry points

- [README](../README.md): support-staff use case, one-question workflow, agent/MCP responsibilities, optional Gemini, validation and limitations.
- [Quickstart](quickstart.md): first setup, existing setup, Windows and Linux/macOS commands, troubleshooting.
- [Three-minute walkthrough](offline-demo.md): clarification, cited checks, outcome reporting and engineering handoff.
- [API contract](api.md): status versus resolution, pending IDs, developer overrides and memory limits.
- [Third-party notices](../THIRD_PARTY_NOTICES.md): public osTicket source/document attribution and licensing status.

## Fresh Windows setup

An independent copy of the candidate source files was created under ignored `data/release-check-v012/`. It did not reuse the application's virtual environment or code index.

| Check | Result |
|---|---|
| New Python virtual environment | Created with Python 3.12 |
| Install `requirements.lock` | Passed; package downloads used the local pip cache where available |
| `pip check` | No broken requirements |
| Fresh osTicket clone | Downloaded from the public GitHub repository, not copied from the existing checkout |
| Rebuild pinned index | 755 indexed files; 1,511 skipped entries |
| Unit/integration suite in the new environment | 228 passed; one existing Starlette TestClient/httpx deprecation warning |
| Real stdio MCP smoke | Discovery, search and read passed |
| Gemini dry-run suite | Three cases passed; zero model calls |
| Start actual Uvicorn server | Passed on an isolated localhost port; test process stopped afterward |
| HTTP health and support workflow | v0.12.0 health passed; 401 clarification → three checks → engineering handoff passed through real MCP |

Logs and generated results stay inside ignored `data/`. The user-facing server on port 8000 was not restarted. Linux/macOS instructions are supplied but were not executed in this Windows check. The Ubuntu GitHub Actions test workflow later passed on the published commit (see [Publication](#publication)); that covers the automated tests, not a manual Linux walkthrough.

## Frontend redesign after the fresh setup

The web UI (`app/static/`) was redesigned after the fresh setup above: typography, palette, motion and interaction polish. API endpoints, agent logic, retrieval and response contracts were not changed, and every label referenced by the walkthrough is still present. Re-checked in the application's own environment:

| Check | Result |
|---|---|
| Unit/integration suite | 228 passed |
| Browser walkthrough over real MCP, headless Chrome | 401 clarification → three checks (`checks_available`, `awaiting_reply`, `context_used=true`, `user_turns=2`) → engineering handoff with download; **New question** reset → user-reported resolution; document answer, unsupported-version boundary and combined document/code question |
| Screenshot | `support-checks-redesign.png` recaptured from the redesigned UI |

Code-evidence excerpts render with font ligatures disabled, so `->` and `!=` are shown exactly as in the source.

## Candidate file and history checks

The review considered existing tracked files and non-ignored new files, excluding tracked paths deleted in the working tree. Common credential patterns were checked in that set, in the historical ZIP's entries and in all 57 blob objects reachable from local Git references. No pattern findings were found. This is a heuristic check, not a guarantee that every possible secret is detectable.

The candidate file set excludes `.venv/`, `data/`, `.env` and server logs. `.env.example` contains an empty key placeholder. Indexes, external checkouts, environment files and runtime logs remain local. The archive SHA-256 remains:

```text
089cf967dc864e6d48aaca6f781ded8f832f411f9ac85a6aed5b82688f946945
```

Historical artifacts remain preserved, with their earlier languages, case sets and limitations. They are not relabeled as current English benchmark results.

## Publication

| Item | Status |
|---|---|
| Repository | Public: [heathy321/support-system-knowledge-agent](https://github.com/heathy321/support-system-knowledge-agent); the local directory keeps its historical name |
| First published commit | `d012441` on `main`, following the preserved v0.4 commit. It includes the intentional removal of the former travel-policy demo and the English osTicket implementation |
| Pre-push check | 88 changed files scanned for common credential patterns and files over 1 MB; no findings |
| GitHub Actions | `tests` workflow passed on `d012441` (Ubuntu) |
| License | Deliberately not added. The original code is public for review without a reuse license; upstream material retains its own notices |

No credential is required to run the offline demo. Publishing source code is separate from hosting a server; this release remains a localhost demo without authentication or a shared session store.
