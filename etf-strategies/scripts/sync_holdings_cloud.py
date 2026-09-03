"""sync_holdings_cloud.py — 拉取云端(TOS)持仓/调仓到本地（每日复盘读取前置步骤）.

背景（2026-08-31 BUG）：
- Dashboard「持仓/资产」页面在 TOS 模式（严格零本地，scripts/config/cloud.json 已配置）
  下，录入的调仓只写云端 `holdings/每日调仓.md` + `holdings/持仓.md`，本地文件不更新；
- 而每日复盘/早盘/盘中/周报 prompt 读取的是本地 `my_doc/每日复盘/每日调仓.md` 与
  `harness/config/持仓.md`，导致复盘读到过期数据（"今日调仓：无"、信号执行缺失）。

本脚本在复盘类任务执行前把云端两文件拉回本地，保证复盘与 dashboard「持仓/资产」
页面同源。未配置云端（无 cloud.json/凭据/无对象）→ SKIP（本地模式无需同步）。

用法：
    python etf-strategies/scripts/sync_holdings_cloud.py

输出约定（prompt 依赖此约定判断）：
    PULLED: holdings/每日调仓.md -> my_doc/每日复盘/每日调仓.md (N bytes)
    PULLED: holdings/持仓.md -> my_doc/每日复盘/harness/config/持仓.md (N bytes)
    SKIP:   ...（未配置云端 / 云端无对象 / 云端存储不可用）

退出码：0 = 成功（含 SKIP）；1 = 云端可读但本地写入失败（调用方应中止并人工排查）。
"""
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
_ETF = _REPO / "etf-strategies"
if str(_ETF) not in sys.path:
    sys.path.insert(0, str(_ETF))

_LOCAL_PATHS = {
    "holdings/每日调仓.md": _REPO / "my_doc" / "每日复盘" / "每日调仓.md",
    "holdings/持仓.md": _REPO / "my_doc" / "每日复盘" / "harness" / "config" / "持仓.md",
}

try:
    from dashboard.portfolio import pull_holdings_to_local
except Exception as exc:  # boto3/cloud_store 不可用 → 本地模式
    print(f"SKIP: 云端存储不可用（{type(exc).__name__}: {exc}），本地模式无需同步")
    sys.exit(0)

result = pull_holdings_to_local()

for key in result.get("pulled", []):
    local = _LOCAL_PATHS.get(key)
    size = -1
    if local is not None:
        try:
            size = local.stat().st_size
        except OSError:
            pass
    rel = local.relative_to(_REPO) if local is not None else key
    print(f"PULLED: {key} -> {rel} ({size} bytes)")

for key in result.get("skipped", []):
    print(f"SKIP: {key}（云端无对象或不可读）")

if not result.get("pulled") and not result.get("skipped"):
    print("SKIP: 未配置云端存储（cloud.json 缺失/无凭据），本地模式无需同步")

sys.exit(0)
