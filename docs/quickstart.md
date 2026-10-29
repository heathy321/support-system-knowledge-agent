# Quickstart: Support System Agent v0.12.0

The workspace and generated explanations are English. The Support System Agent searches reviewed osTicket API documentation and delegates code tasks to the Code Analyzer through real File Search MCP. Offline is the default; no key or model cost is required.

## First setup

Use Python 3.12 and Git. Download or clone this project, then open its root directory (the one containing `pyproject.toml`). Windows commands are in the [README](../README.md#run-locally).

Linux/macOS equivalent, from the project root:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
git clone https://github.com/osTicket/osTicket.git data/repos/osticket
.venv/bin/python -m scripts.index_repository
.venv/bin/python -m scripts.mcp_smoke
ENABLE_GEMINI=0 CODE_SEARCH_BACKEND=mcp_stdio .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-config logging.json
```

No osTicket installation, PHP server, database, API key or `.env` file is needed for the offline demo. The documentation corpus ships with this project. The code index is generated locally and is not committed. The external repository is read as data, never executed. Use one server worker for the process-local conversation store.

## Existing local setup

In the project directory, stop an older server on port 8000 and run:

```powershell
$env:ENABLE_GEMINI = '0'
$env:CODE_SEARCH_BACKEND = 'mcp_stdio'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-config logging.json
```

Open [the workspace](http://127.0.0.1:8000/). The footer and `/health` should show v0.12.0. First-time setup is in the [README](../README.md#run-locally). Do not clone into an already populated repository directory.

## Using the workspace

Type a question and click **Get answer**. The system chooses sources and answer mode. No retrieval, model, version or file-path form controls are required. Include a version or exact error in the question when relevant.

Read the guidance and citations. If more information is needed, type only the requested details and click Send reply. The original question is retained for up to 15 minutes of inactivity and four user messages. Choose New question to clear pending context. Refreshing the page loses the browser reference; restarting the server clears its memory. When the system cannot resolve a question, download the engineering handoff, add reproduction details and share it yourself. Nothing is sent automatically. Engineers can expand code evidence, processing information and JSON.

Work scenarios are listed in the [walkthrough](offline-demo.md). For an offline demo, start with `ENABLE_GEMINI=0`. To enable the optional model workflow, run `./start-gemini.ps1`; see the [Gemini guide](gemini.md).

## Validation and troubleshooting

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.mcp_smoke
.\.venv\Scripts\python.exe -m scripts.try_gemini
```

If the index is absent, run `python -m scripts.index_repository` with the project virtual environment. `/health` reports code and document availability separately. One failing branch does not disable independent queries to the other branch. Use synthetic test fixtures to test failures rather than deleting real data.

| Symptom | Check |
|---|---|
| Clone destination already exists | Reuse the existing osTicket clone instead of cloning over it |
| Index build cannot find the pinned commit | Run `git -C data/repos/osticket fetch origin 8d38b0619649a50ee7cbbf37085f5d297fdc6f36`, then rebuild |
| MCP dependency or import error | Install `requirements.lock` using the same virtual environment that runs the server |
| Port 8000 is in use | Stop your previous server or select another local port |
| Gemini enabled unexpectedly | Set `ENABLE_GEMINI=0` in the server terminal and restart; `.env` is not auto-loaded |
| A short reply loses context | Use the same page before expiry; after refresh/restart, submit a complete question |
| Code search returns unrelated numeric matches | Lexical retrieval can match issue numbers as well as HTTP status codes; inspect the cited excerpt |

Linux/macOS commands are supplied for portability, but the recorded fresh-environment validation was performed on Windows. CI is configured for Ubuntu; no remote CI run is claimed until the project is pushed.

Optional model setup is in [the Gemini guide](gemini.md). Limited live synthesis smoke tests do not establish general model quality. The browser accepts no keys, and configuration readiness does not establish connectivity.

Try `it occurs a 401 error`, then reply `when creating a ticket through the API`. The structured response should show `conversation.context_used=true`, `user_turns=2`, `resolution=checks_available` and `conversation.state=awaiting_reply`. Read the three cited checks. In a demo, reply `I checked all three, but it still returns 401.` to test handoff, or `It works now.` to test user-reported closure. In real use, report only checks actually performed. Lack of access also produces a handoff for the administrator or integration owner. These outcome replies make no model calls. This playbook also works offline, and other incidents may still require engineering review.
