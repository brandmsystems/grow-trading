# Daily paper-trading auto-start. Run by Windows Task Scheduler at 09:00 (Mon-Fri).
# 1) starts the server if it is not running, 2) waits for it, 3) starts the engine in PAPER mode.
# Paper mode only: this script never sends the LIVE phrase and never places real orders.
# Log: data\logs\auto_start.log

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Base = "http://127.0.0.1:5000"
$LogDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force $LogDir | Out-Null
$Log = Join-Path $LogDir "auto_start.log"

function Write-Log($msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg" | Out-File -FilePath $Log -Append -Encoding utf8
}

# Engine settings. Edit here. Only paper mode is allowed.
$Config = @{
    trade_mode   = "paper"
    exec_mode    = "ATM_BUY"
    timeframe    = 15
    entry_start  = "09:30"
    cutoff       = "14:30"
    signal_mode  = "cross"
    risk_pct     = 1.0
    daily_risk_pct = 3.0
    max_trades_per_day = 6
}

function Test-Server {
    try { Invoke-RestMethod -Uri "$Base/api/live/status" -TimeoutSec 60 | Out-Null; return $true }
    catch { return $false }
}

try {
    Write-Log "Auto-start begins."
    if (-not (Test-Server)) {
        Write-Log "Server not running. Starting it."
        Start-Process -FilePath (Join-Path $Root ".venv\Scripts\python.exe") -ArgumentList "start.py" -WorkingDirectory $Root -WindowStyle Minimized
        $up = $false
        for ($i = 0; $i -lt 40; $i++) {       # wait up to about 6 minutes
            Start-Sleep -Seconds 9
            if (Test-Server) { $up = $true; break }
        }
        if (-not $up) { throw "Server did not come up in time." }
    }
    Write-Log "Server is up."

    $status = Invoke-RestMethod -Uri "$Base/api/live/status" -TimeoutSec 60
    if ($status.data.state -ne "stopped") {
        Write-Log "Engine already running (state: $($status.data.state)). Nothing to do."
        exit 0
    }

    $body = @{ config = $Config } | ConvertTo-Json -Depth 5
    $res = Invoke-RestMethod -Method Post -Uri "$Base/api/live/start" -ContentType "application/json" `
        -Body $body -TimeoutSec 120
    Write-Log "Paper engine started: state $($res.data.state)."
}
catch {
    $detail = $_.ErrorDetails.Message
    if (-not $detail) { $detail = $_.Exception.Message }
    Write-Log "FAILED: $detail"
    exit 1
}
