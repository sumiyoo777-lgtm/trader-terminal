# Trader Terminal launcher — double-click entry point (via the desktop
# shortcut). Idempotent: skips anything already running, then opens the
# browser. Logs to %TEMP%\trader-terminal-launch.log.
$ErrorActionPreference = 'SilentlyContinue'
$Root = Split-Path -Parent $PSScriptRoot
$Log = Join-Path $env:TEMP 'trader-terminal-launch.log'
function Write-Log($msg) { "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg" | Out-File $Log -Append -Encoding utf8 }
Write-Log "launch requested (root=$Root)"

function Test-Port($port) {
    try {
        $null = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop
        return $true
    } catch { return $false }
}

# ---- backend (FastAPI + scheduler), port 8000 -----------------------------
if (-not (Test-Port 8000)) {
    Write-Log 'starting backend on :8000'
    Start-Process -FilePath (Join-Path $Root 'backend\.venv\Scripts\python.exe') `
        -ArgumentList '-m', 'uvicorn', 'app.main:app', '--port', '8000' `
        -WorkingDirectory (Join-Path $Root 'backend') -WindowStyle Hidden
} else {
    Write-Log 'backend already running'
}

# ---- frontend (Next.js production server), port 3000 ----------------------
$FrontendDir = Join-Path $Root 'frontend'
$NextCmd = Join-Path $FrontendDir 'node_modules\.bin\next.cmd'
if (-not (Test-Port 3000)) {
    if (-not (Test-Path (Join-Path $FrontendDir '.next\BUILD_ID'))) {
        Write-Log 'no production build found - building (one-time, ~1 min)'
        Start-Process -FilePath $NextCmd -ArgumentList 'build' `
            -WorkingDirectory $FrontendDir -WindowStyle Hidden -Wait
    }
    Write-Log 'starting frontend on :3000'
    Start-Process -FilePath $NextCmd -ArgumentList 'start', '-p', '3000' `
        -WorkingDirectory $FrontendDir -WindowStyle Hidden
} else {
    Write-Log 'frontend already running'
}

# ---- wait until both answer, then open the default browser ----------------
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    if ((Test-Port 8000) -and (Test-Port 3000)) { break }
    Start-Sleep -Milliseconds 500
}
Write-Log "opening browser (backend up: $(Test-Port 8000), frontend up: $(Test-Port 3000))"
Start-Process 'http://localhost:3000/dashboard/trader-terminal'
