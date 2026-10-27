$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw 'Create the environment first: py -3.12 -m venv .venv; then install requirements.lock (see README.md).'
}
& $projectPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-config logging.json
