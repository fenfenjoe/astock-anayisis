# ============================================================
# start_local.ps1 - Windows local startup for the quant dashboard
# ============================================================
# Starts the pure-quant Dashboard locally (python dashboard/app.py, :8010).
#
# 2026-10-15 解耦改造后：
# - Dashboard 为纯量化展示 + API（策略/持仓/信号/报告/回测/工单），不含 agent 运行时
# - agent 运行时与定时任务自动化已迁移至 ~/.dsh/workspace/xiaoman/
#   （agent :8020 由 ~/.dsh/workspace/xiaoman/scripts/start_all.ps1 启动）
# - 本脚本只负责启动量化 Dashboard
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/start_local.ps1         # 启动 Dashboard
#   powershell -ExecutionPolicy Bypass -File scripts/start_local.ps1 -DryRun # 只打印启动命令
#   powershell -ExecutionPolicy Bypass -File scripts/start_local.ps1 -Port 8010
# ============================================================

param(
    [switch]$DryRun,
    [int]$Port = 8010
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

if ($DryRun) {
    Write-Host ""
    Write-Host "[etf] DryRun：未启动服务。实际启动命令："
    Write-Host "[etf]   $PythonExe dashboard/app.py"
    Write-Host "[etf] 访问   = http://localhost:$Port"
    exit 0
}

Write-Host "[etf] 启动量化 Dashboard: python dashboard/app.py  (Ctrl+C 退出)"
Write-Host "[etf] 访问   = http://localhost:$Port"
Write-Host ""

$env:DASHBOARD_PORT = "$Port"
& $PythonExe dashboard/app.py
