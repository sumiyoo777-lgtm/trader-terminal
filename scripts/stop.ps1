# Stops the Trader Terminal servers (backend :8000, frontend :3000).
$ErrorActionPreference = 'SilentlyContinue'
$Log = Join-Path $env:TEMP 'trader-terminal-launch.log'
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] stop requested" | Out-File $Log -Append -Encoding utf8

foreach ($port in 8000, 3000) {
    try {
        Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique |
            ForEach-Object {
                "[$(Get-Date -Format 'HH:mm:ss')] stopping pid $_ (port $port)" | Out-File $Log -Append -Encoding utf8
                Stop-Process -Id $_ -Force
            }
    } catch {}
}
