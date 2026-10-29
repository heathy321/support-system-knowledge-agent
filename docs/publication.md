# Publication preparation — v0.12.0

Checked on 2026-10-29. This record describes local preparation for publishing the source repository. No GitHub repository was created, no commit or push was made, and no application was deployed during this preparation.

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

Logs and generated results stay inside ignored `data/`. The user-facing server on port 8000 was not restarted. Linux/macOS instructions are supplied but were not executed in this Windows check. The Ubuntu GitHub Actions workflow is configured; no remote CI run has been observed yet.

## Candidate file and history checks

The review considered existing tracked files and non-ignored new files, excluding tracked paths deleted in the working tree. Common credential patterns were checked in that set, in the historical ZIP's entries and in all 57 blob objects reachable from local Git references. No pattern findings were found. This is a heuristic check, not a guarantee that every possible secret is detectable.

The candidate file set excludes `.venv/`, `data/`, `.env` and server logs. `.env.example` contains an empty key placeholder. Indexes, external checkouts, environment files and runtime logs remain local. The archive SHA-256 remains:

```text
089cf967dc864e6d48aaca6f781ded8f832f411f9ac85a6aed5b82688f946945
```

Historical artifacts remain preserved, with their earlier languages, case sets and limitations. They are not relabeled as current English benchmark results.

## Decisions before publishing

1. Choose the GitHub repository name and visibility. `support-system-knowledge-agent` matches the current project name; the existing local directory can keep its historical name.
2. Choose a reuse license for the original implementation. No project license has been added on the owner's behalf; upstream material retains its own notices.
3. Review the full pending diff, including intentional removal of the former travel-policy demo and addition of the English osTicket implementation. Those changes predate this documentation pass and must not be mistaken for newly introduced deletions.
4. Create the remote repository, commit the reviewed files and push. Confirm the first GitHub Actions run before displaying a passing CI badge or claiming Linux validation.

No credential is required to run the offline demo. Publishing source code is separate from hosting a server; this release remains a localhost demo without authentication or a shared session store.
