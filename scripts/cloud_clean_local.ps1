# ===========================================
# cloud_clean_local.ps1 - clean recoverable local data
# ===========================================
# Deletes local data that is safe to remove because it is backed up in
# cloud (TOS). Config/secrets/credentials/holdings md are KEPT by default.
#
# IMPORTANT: run `python scripts/cloud_sync.py` (upload) FIRST so the
# cloud has the latest data, then verify with --download --dry-run.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/cloud_clean_local.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/cloud_clean_local.ps1 -IncludeHoldings
#     (-IncludeHoldings also deletes 持仓.md / 每日调仓.md - restored from TOS on next start)
# ===========================================
param([switch]$IncludeHoldings)

$ErrorActionPreference = "Continue"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot   = Split-Path -Parent $scriptRoot
$etfDir     = Join-Path $repoRoot "etf-strategies"
$daily      = Join-Path $repoRoot "my_doc\每日复盘"

Write-Host "=================================================="
Write-Host "本地数据清理（TOS 已兜底，删除可恢复数据）"
Write-Host "  - 删除：报告 / 日志 / SQLite 工作库 / OpenViking data / 快照"
Write-Host "  - 保留：cloud.json/.env/.secret_key/notify_config.json/持仓 md"
Write-Host "  - 请先确认已执行 python scripts/cloud_sync.py 上传最新"
Write-Host "=================================================="
$ans = Read-Host "确认删除？（输入 yes 继续）"
if ($ans -ne "yes") { Write-Host "已取消"; exit 0 }

$targets = @(
  @{ P = (Join-Path $etfDir "report");                     D = "回测报告 report/" },
  @{ P = (Join-Path $etfDir "automation\logs");            D = "ETF 自动化日志" },
  @{ P = (Join-Path $daily "harness\automation\logs");     D = "复盘 harness 日志" },
  @{ P = (Join-Path $etfDir "dashboard\data\cache.db");    D = "dashboard 工作库 cache.db" },
  @{ P = (Join-Path $etfDir "agent\data\agent.db");        D = "agent 工作库 agent.db" },
  @{ P = (Join-Path $repoRoot "data");                     D = "OpenViking 数据 data/" },
  @{ P = (Join-Path $scriptRoot ".snapshots");             D = "云同步本地快照" },
  @{ P = (Join-Path $daily "reports");                     D = "每日复盘报告 reports/" }
)
if ($IncludeHoldings) {
  $targets += @{ P = (Join-Path $daily "每日调仓.md");        D = "每日调仓.md（TOS 恢复）" }
  $targets += @{ P = (Join-Path $daily "harness\config\持仓.md"); D = "持仓.md（TOS 恢复）" }
}

foreach ($t in $targets) {
  if (Test-Path $t.P) {
    Remove-Item $t.P -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host ("已删除: {0,-28} {1}" -f $t.D, $t.P)
  } else {
    Write-Host ("跳过(不存在): {0}" -f $t.D)
  }
}

Write-Host ""
Write-Host "完成。下次启动 dashboard/agent 时设置 CLOUD_RESTORE_ON_START=1 会从 TOS 自动恢复；"
Write-Host "或手动: python scripts/cloud_sync.py --download"
