# =====================================================================
#  KDP Quality Dashboard - Watchdog (auto-restart)
#  - Restarts the dashboard (port 8502) and the alarm scheduler
#    (oot_alarm.py) if either is not running.
#  - Windows Task Scheduler runs this every 2 minutes.
#  - Manual run/check:  powershell -ExecutionPolicy Bypass -File watchdog.ps1
#  NOTE: ASCII-only on purpose (PowerShell 5.1 mis-reads non-BOM UTF-8).
# =====================================================================
$ErrorActionPreference = 'SilentlyContinue'

$Dir = Split-Path -Parent $MyInvocation.MyCommand.Definition
if (-not $Dir) { $Dir = (Get-Location).Path }
Set-Location $Dir

$Port     = 8502
$Log      = Join-Path $Dir 'watchdog.log'
$WebBat   = Join-Path $Dir 'run_webapp.bat'
$AlarmBat = Join-Path $Dir 'run_alarm.bat'
$HideVbs  = Join-Path $Dir 'run_hidden.vbs'

# 배치 파일을 콘솔 창 없이(숨김) 실행. run_hidden.vbs 가 있으면 그걸로, 없으면 최소화로 폴백.
function Start-Hidden($batName) {
  $bat = Join-Path $Dir $batName
  if (Test-Path $HideVbs) {
    Start-Process -FilePath 'wscript.exe' -ArgumentList (('"{0}"' -f $HideVbs), $batName) -WorkingDirectory $Dir
  } else {
    Start-Process -FilePath $bat -WorkingDirectory $Dir -WindowStyle Hidden
  }
}

# --- rotate log if larger than 1MB ---
try {
  if ((Test-Path $Log) -and ((Get-Item $Log).Length -gt 1MB)) { Clear-Content $Log }
} catch {}

function Log($m) {
  $line = "{0} {1}" -f ([DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss')), $m
  try { Add-Content -Path $Log -Value $line -Encoding UTF8 } catch {}
}

# --- 1) Dashboard: is port 8502 in LISTENING state? ---
$dashUp = $false
try {
  $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
  if ($c) { $dashUp = $true }
} catch {
  $ns = netstat -ano | Select-String (":{0}\s" -f $Port) | Select-String 'LISTENING'
  if ($ns) { $dashUp = $true }
}

if (-not $dashUp) {
  Log "[DASH] DOWN -> restarting run_webapp.bat (hidden)"
  Start-Hidden 'run_webapp.bat'
}

# --- 2) Alarm: is a python* process running oot_alarm.py? ---
#     (name limited to python* to avoid false positives from bash/grep)
$alarmUp = $false
$procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue
foreach ($p in $procs) {
  if (($p.Name -match '^python') -and $p.CommandLine -and ($p.CommandLine -like '*oot_alarm.py*')) {
    $alarmUp = $true; break
  }
}

if (-not $alarmUp) {
  Log "[ALARM] DOWN -> restarting run_alarm.bat (hidden)"
  Start-Hidden 'run_alarm.bat'
}

# --- status line (to confirm the watchdog is alive) ---
$ds = if ($dashUp) { 'up' } else { 'restart' }
$as = if ($alarmUp) { 'up' } else { 'restart' }
Log ("[CHECK] dashboard={0} alarm={1}" -f $ds, $as)
