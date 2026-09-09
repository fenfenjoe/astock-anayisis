# ===========================================
# start_all.ps1 - one-command local startup of 3 services
#                 (openviking / dashboard / agent)
# ===========================================
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/start_all.ps1           # start
#   powershell -ExecutionPolicy Bypass -File scripts/start_all.ps1 -Action stop
#   powershell -ExecutionPolicy Bypass -File scripts/start_all.ps1 -Action status
#
# Deps: node/npm (dsh 由 sync_dsh.ps1 自动检测/安装), python (etf-strategies)
# Run scripts/sync_dsh.ps1 first: it auto-installs pnpm/dsh if missing,
# syncs profiles, and installs profile plugin deps (dsh plugin --profile install).
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
     Cmd  = "python"; Args = @("-u", "dashboard\app.py"); WorkDir = $etfDir },
  @{ Name = "agent";      PidFile = "agent.pid";      Log = "agent.log";
     Cmd  = "python"; Args = @("-u", "-m", "agent"); WorkDir = $etfDir }
)

# dashboard 端口：8000 常被酷狗 KGService 等占用，改用 8010（app.py 支持 DASHBOARD_PORT）
$env:DASHBOARD_PORT = "8010"

# ── OpenViking 云版检测：ovcli.conf 指向云（非本地）→ 无需本地 server，跳过 ──
$ovCliConf = Join-Path $env:USERPROFILE ".openviking\ovcli.conf"
$cloudOpenViking = $false
if (Test-Path $ovCliConf) {
  try {
    $ovConf = Get-Content $ovCliConf -Raw | ConvertFrom-Json
    if ($ovConf.url -and $ovConf.url -notmatch "127\.0\.0\.1|localhost|:1933") {
      $cloudOpenViking = $true
    }
  } catch { }
}
if ($cloudOpenViking) {
  $services[0].Cmd = $null   # 云版：本地 openviking-server 不需要
  Write-Host "OpenViking 云版已配置（$($ovConf.url)）— 跳过本地 openviking-server"
}

function Get-PidFile([string]$name) { Join-Path $pidDir $name }

function Is-Running([string]$pidFile) {
  if (Test-Path $pidFile) {
    $procId = [int](Get-Content $pidFile -ErrorAction SilentlyContinue)
    if ($procId -gt 0) { return [bool](Get-Process -Id $procId -ErrorAction SilentlyContinue) }
  }
  return $false
}

if ($Action -eq "stop") {
  foreach ($s in $services) {
    $pf = Get-PidFile $s.PidFile
    if (Is-Running $pf) {
      Stop-Process -Id ([int](Get-Content $pf)) -Force -ErrorAction SilentlyContinue
      Write-Host "stopped: $($s.Name)"
    } else { Write-Host "not running: $($s.Name)" }
    Remove-Item $pf -ErrorAction SilentlyContinue
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
$started = @{}   # name -> pid（仅记录本次实际拉起的服务）
foreach ($s in $services) {
  $pf = Get-PidFile $s.PidFile
  if (Is-Running $pf) { Write-Host "already running, skip: $($s.Name)"; continue }
  if (-not $s.Cmd) {
    if ($s.Name -eq "openviking" -and $cloudOpenViking) {
      Write-Host "skip: openviking — 云版模式已配置（$($ovConf.url)），本地 server 无需启动"
    } else {
      Write-Warning "openviking-server not found (pip install --user openviking)"
    }
    continue
  }
  $logOut = Join-Path $logsDir $s.Log
  $proc = Start-Process -FilePath $s.Cmd -ArgumentList $s.Args -WorkingDirectory $s.WorkDir `
          -RedirectStandardOutput $logOut -RedirectStandardError "$logOut.err" `
          -WindowStyle Hidden -PassThru
  Set-Content $pf $proc.Id
  $started[$s.Name] = $proc.Id
  Write-Host "started: $($s.Name) (PID $($proc.Id), log $($s.Log))"
  Start-Sleep -Milliseconds 800
}

Write-Host ""
Write-Host "All services started."
# 汇总以进程实际存活状态为准（$started 只含本次新拉起；早已在运行被 skip 的不在其中）
$dashRun  = Is-Running (Get-PidFile "dashboard.pid")
$agentRun = Is-Running (Get-PidFile "agent.pid")
$ovRun    = Is-Running (Get-PidFile "openviking.pid")
if ($dashRun) {
  $note = if ($started.ContainsKey("dashboard")) { "进程已拉起；首次就绪需等云恢复/初始化，看 dashboard.log" } else { "已在运行" }
  Write-Host "  dashboard : running  http://localhost:8010  ($note)"
} else {
  Write-Host "  dashboard : 未启动（见 dashboard.log.err）"
}
if ($ovRun) {
  Write-Host "  openviking: running  http://127.0.0.1:1933"
} elseif ($cloudOpenViking) {
  Write-Host "  openviking: 云版模式（本地未启动）— $($ovConf.url)"
} else {
  Write-Host "  openviking: 未启动"
}
if ($agentRun) {
  $note = if ($started.ContainsKey("agent")) { "本次拉起 (python -m agent)" } else { "已在运行 (python -m agent)" }
  Write-Host "  agent     : running  $note"
} else {
  Write-Host "  agent     : 未启动"
}
Write-Host "  logs      : $logsDir"
Write-Host "  stop      : rerun with -Action stop"
