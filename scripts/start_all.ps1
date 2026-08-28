# ===========================================
# start_all.ps1 - one-command local startup of 3 services
#                 (openviking / dashboard / agent)
# ===========================================
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/start_all.ps1           # start
#   powershell -ExecutionPolicy Bypass -File scripts/start_all.ps1 -Action stop
#   powershell -ExecutionPolicy Bypass -File scripts/start_all.ps1 -Action status
#
# Deps: dsh (npm global), openviking-server (pip --user), python (etf-strategies)
# Run scripts/sync_dsh.ps1 first to align versions and profiles.
# ===========================================
param([ValidateSet("start","stop","status")][string]$Action = "start")

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot   = Split-Path -Parent $scriptRoot
$etfDir     = Join-Path $repoRoot "etf-strategies"
$logsDir    = Join-Path $scriptRoot "logs"
$pidDir     = Join-Path $scriptRoot ".pids"
New-Item -ItemType Directory -Force -Path $logsDir, $pidDir | Out-Null

# locate openviking-server (pip --user typical location)
$ovExe = (Get-Command openviking-server -ErrorAction SilentlyContinue).Source
if (-not $ovExe) {
  $ovExe = (Get-ChildItem "$env:APPDATA\Python\Python311\Scripts\openviking-server.exe" -ErrorAction SilentlyContinue).FullName
}

$services = @(
  @{ Name = "openviking"; PidFile = "openviking.pid"; Log = "openviking.log";
     Cmd  = $ovExe; Args = @() },
  @{ Name = "dashboard";  PidFile = "dashboard.pid";  Log = "dashboard.log";
     Cmd  = "python"; Args = @("dashboard\app.py"); WorkDir = $etfDir },
  @{ Name = "agent";      PidFile = "agent.pid";      Log = "agent.log";
     Cmd  = "python"; Args = @("-m", "agent"); WorkDir = $etfDir }
)

function Get-PidFile([string]$name) { Join-Path $pidDir $name }

function Is-Running([string]$pidFile) {
  if (Test-Path $pidFile) {
    $pid = [int](Get-Content $pidFile -ErrorAction SilentlyContinue)
    if ($pid -gt 0) { return [bool](Get-Process -Id $pid -ErrorAction SilentlyContinue) }
  }
  return $false
}

if ($Action -eq "stop") {
  # 严格零本地：停止前先把内存库/日志快照回传 TOS（若启用云恢复）
  if ($env:CLOUD_RESTORE_ON_START -eq "1") {
    Write-Host "Uploading latest state to cloud before stop..."
    python (Join-Path $scriptRoot "cloud_sync.py") 2>&1 | Select-Object -Last 2
  }
  foreach ($s in $services) {
    $pf = Get-PidFile $s.PidFile
    if (Is-Running $pf) {
      Stop-Process -Id ([int](Get-Content $pf)) -Force -ErrorAction SilentlyContinue
      Write-Host "stopped: $($s.Name)"
    } else { Write-Host "not running: $($s.Name)" }
    Remove-Item $pf -ErrorAction SilentlyContinue
  }
  # OpenViking 数据退出清理（Windows 极限：运行中临时目录，停止后零残留）
  if ($env:CLOUD_RESTORE_ON_START -eq "1") {
    $ovData = Join-Path $repoRoot "data"
    if (Test-Path $ovData) {
      Remove-Item $ovData -Recurse -Force -ErrorAction SilentlyContinue
      Write-Host "cleaned OpenViking local data (backed up to cloud)"
    }
  }
  exit 0
}

if ($Action -eq "status") {
  foreach ($s in $services) {
    $pf = Get-PidFile $s.PidFile
    $run = Is-Running $pf
    $extra = ""
    if ($s.Name -eq "openviking" -and $run) { $extra = " (port 1933)" }
    Write-Host ("{0,-12} {1}{2}" -f $s.Name, $(if ($run) { "running" } else { "stopped" }), $extra)
  }
  exit 0
}

# start
# 云恢复：CLOUD_RESTORE_ON_START=1 时启动前从 TOS 拉取（含 openviking data/、sqlite、持仓）
if ($env:CLOUD_RESTORE_ON_START -eq "1") {
  Write-Host "Restoring from cloud (TOS)..."
  python (Join-Path $scriptRoot "cloud_sync.py") --download 2>&1 | Select-Object -Last 3
}
foreach ($s in $services) {
  $pf = Get-PidFile $s.PidFile
  if (Is-Running $pf) { Write-Host "already running, skip: $($s.Name)"; continue }
  if (-not $s.Cmd) { Write-Warning "openviking-server not found (pip install --user openviking)"; continue }
  $logOut = Join-Path $logsDir $s.Log
  $proc = Start-Process -FilePath $s.Cmd -ArgumentList $s.Args -WorkingDirectory $s.WorkDir `
          -RedirectStandardOutput $logOut -RedirectStandardError "$logOut.err" `
          -WindowStyle Hidden -PassThru
  Set-Content $pf $proc.Id
  Write-Host "started: $($s.Name) (PID $($proc.Id), log $($s.Log))"
  Start-Sleep -Milliseconds 800
}

Write-Host ""
Write-Host "All services started."
Write-Host "  dashboard : http://localhost:8000"
Write-Host "  openviking: http://127.0.0.1:1933"
Write-Host "  logs      : $logsDir"
Write-Host "  stop      : rerun with -Action stop"
