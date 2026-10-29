# Use a Free Tier project. This script cannot verify billing entitlement from an API key.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) { throw 'Create .venv and install requirements.lock first.' }
function Stop-ProjectServer {
    $listeners = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
    $ownerIds = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($ownerIds.Count -eq 0) { return }
    if ($ownerIds.Count -ne 1) { throw 'Port 8000 has multiple owners. Stop the old server manually.' }
    $listenerProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($ownerIds[0])"
    $launcherProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($listenerProcess.ParentProcessId)"
    $isServer = $listenerProcess.CommandLine -match 'uvicorn app.main:app' -and $listenerProcess.CommandLine -match '--port 8000'
    if (-not $isServer) { throw 'Port 8000 belongs to another application. It has not been stopped.' }
    if ($listenerProcess.ExecutablePath -eq $projectPython) {
        Stop-Process -Id $listenerProcess.ProcessId
    } elseif ($launcherProcess.ExecutablePath -eq $projectPython -and $launcherProcess.CommandLine -match 'uvicorn app.main:app') {
        Stop-Process -Id $listenerProcess.ProcessId,$launcherProcess.ProcessId
    } else {
        throw 'Could not verify that port 8000 belongs to this project. Stop the old server manually.'
    }
    Write-Host 'Stopped the previous server belonging to this project.'
}
Write-Host 'Check your API key project in Google AI Studio: it must say Free Tier, with no paid billing enabled.'
Write-Host 'This script cannot verify your billing tier. Free quotas may be exhausted or unavailable.'
Write-Host 'Questions and selected evidence will be sent to Google. Never include customer data or secrets.'
$tierConfirmation = Read-Host 'Type FREE only after confirming the project is on Free Tier'
if ($tierConfirmation -cne 'FREE') { throw 'No model service enabled.' }
$secureKey = Read-Host 'Gemini API key (hidden; not saved to disk)' -AsSecureString
$keyPointer = [IntPtr]::Zero
$savedSettings = @{}
foreach ($settingName in @('GEMINI_API_KEY','GEMINI_MODEL','ENABLE_GEMINI','PYTHONUTF8')) {
    $savedSettings[$settingName] = [Environment]::GetEnvironmentVariable($settingName, 'Process')
}
try {
    $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    $env:GEMINI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    if ([string]::IsNullOrWhiteSpace($env:GEMINI_API_KEY)) { throw 'No API key entered.' }
    $env:GEMINI_MODEL = 'gemini-3.5-flash-lite'
    $env:ENABLE_GEMINI = '1'
    $env:PYTHONUTF8 = '1'
    Stop-ProjectServer
    Write-Host 'Starting on http://127.0.0.1:8000. Startup makes no model call. Submit one supported question to test.'
    & $projectPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-config logging.json
} finally {
    if ($keyPointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer) }
    $secureKey.Dispose()
    foreach ($settingName in $savedSettings.Keys) {
        [Environment]::SetEnvironmentVariable($settingName, $savedSettings[$settingName], 'Process')
    }
}
