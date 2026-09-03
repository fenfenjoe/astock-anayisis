# ============================================================
# start_local.ps1 - Windows local startup for etf-dashboard
# ============================================================
# Starts the dashboard locally (python dashboard/app.py).
# SCHEDULING MODEL: the in-app scheduler engine runs WITH the
# web process (auto ON by default) — tasks start when web starts,
# stop when web stops. No system Scheduled Tasks needed.
#
# If leftover etf-trigger-* / dsh-trigger-* Scheduled Tasks exist,
# this script warns you to clean them up (idempotency keys are
# shared, so double-run is safe, but engine mode should be the
# single owner).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/start_local.ps1         # default: engine auto ON
#   powershell -ExecutionPolicy Bypass -File scripts/start_local.ps1 -NoAuto # force engine auto OFF (external cron)
#   powershell -ExecutionPolicy Bypass -File scripts/start_local.ps1 -DryRun # only print guidance
# ============================================================

param(
    [switch]$NoAuto,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path   # .../etf-strategies/scripts
$EtfDir    = Split-Path -Parent $ScriptDir
Set-Location $EtfDir

$PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $PythonExe) { $PythonExe = "D:\miniconda3\python.exe" }
if (-not (Test-Path $PythonExe)) { throw "python not found: $PythonExe" }

Write-Host "[etf] 目录    = $EtfDir"
Write-Host "[etf] Python  = $PythonExe"

# ---- Leftover Scheduled-Task detection (warning only) ----
# 引擎模式不需要系统计划任务；若残留 etf-trigger-* / dsh-trigger-* 则提示清理。
$etfTasks = @((cmd /c 'schtasks /query /tn "etf-trigger-*" /fo csv 2>nul') | Where-Object { $_ -match '"' })
$oldTasks = @((cmd /c 'schtasks /query /tn "dsh-trigger-*" /fo csv 2>nul') | Where-Object { $_ -match '"' })

if ($etfTasks.Count -gt 1 -or $oldTasks.Count -gt 1) {
    Write-Host ""
    Write-Host "[etf] 警告：检测到系统计划任务残留（etf-trigger-*/dsh-trigger-*）。"
    Write-Host "[etf]   当前模式 = 引擎随 Web 启停，无需系统计划任务。"
    Write-Host "[etf]   请以管理员运行 scripts\setup_etf_scheduled_tasks.ps1 -Cleanup 清理（幂等同 key，残留也安全但建议清理）。"
}

if ($DryRun) {
    Write-Host ""
    Write-Host "[etf] DryRun：未启动服务。实际启动命令："
    Write-Host "[etf]   $PythonExe dashboard/app.py"
    exit 0
}

# ---- Engine auto flag ----
if ($NoAuto) {
    # 显式关闭引擎 auto（外部 cron / scheduler_cli 精确触发场景）
    Remove-Item Env:DASHBOARD_SCHEDULER_ENABLED -ErrorAction SilentlyContinue
    Write-Host ""
    Write-Host "[etf] 引擎 auto = OFF（-NoAuto；若外部无 cron，任务将不会自动执行）"
} else {
    # 默认：引擎 auto ON，随 Web 进程启动/停止
    $env:DASHBOARD_SCHEDULER_ENABLED = "1"
    Write-Host ""
    Write-Host "[etf] 引擎 auto = ON（定时任务随 Web 启动而启动、随 Web 关闭而关闭；20s 轮询零 token）"
}

Write-Host "[etf] 启动 dashboard: python dashboard/app.py  (Ctrl+C 退出)"
Write-Host ""

& $PythonExe dashboard/app.py
