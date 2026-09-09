"""
信号追踪 · 云库读写层（记忆体系 Phase 3 · 方案 v1.10 §9.2）

signal_tracking.py 保持纯计算不变（有测试）；本模块负责把「信号记录」读写到云库
`signal_tracking` 表（PostgREST Data API），本地 signal_tracking.json 过渡期仅作
只读缓存兜底（云库不可达时回退 JSON，保证既有消费方不中断）。

云表 schema（scripts/cloud_schema_signal_tracking.sql）：
    signal_id TEXT PK + 12 列信号表 + 复盘回填 + 追踪结算全量字段。

用法：
    from lib.signal_tracking_cloud import cloud_load_signals, cloud_upsert_signals
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

# 复用 etf-strategies/cloud_db.py（同库同表；.env 在 etf-strategies/.env）
_HERE = Path(__file__).resolve()
_AUTOMATION = _HERE.parent.parent          # harness/automation
_REPO = _AUTOMATION.parent.parent.parent.parent  # 仓库根
_ETF = _REPO / "etf-strategies"
for p in (_ETF,):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

LOCAL_TRACKING = _AUTOMATION / "config" / "signal_tracking.json"


def _load_env():
    env_path = _ETF / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()
import cloud_db  # noqa: E402

# JSON 字段 → 云表列（trigger_date → signal_date）
_COLUMN_MAP = {
    "signal_id": "signal_id",
    "trigger_date": "signal_date",
    "priority": "priority",
    "ticker": "ticker",
    "name": "name",
    "trade_type": "trade_type",
    "direction": "direction",
    "urgency": "urgency",
    "expected_trigger_rate": "expected_trigger_rate",
    "target_price": "target_price",
    "stop_price": "stop_price",
    "target_pct": "target_pct",
    "stop_pct": "stop_pct",
    "expected_return_date": "expected_return_date",
    "entry_price": "entry_price",
    "shares": "shares",
    "status": "status",
    "status_history": "status_history",
    "avoided_loss": "avoided_loss",
    "settle_date": "settle_date",
    "exit_date": "exit_date",
    "settle_price": "settle_price",
    "pnl": "pnl",
    "holding_days": "holding_days",
    "outcome": "outcome",
    "cost_basis": "cost_basis",
    "sell_price": "sell_price",
}
_EXTRA_COLUMNS = [
    "trigger_condition", "valid_window", "position", "source",
    "eval_decision_quality", "eval_execution_quality",
]
# 云表全部列（固定集合，保证批量 upsert 各行键一致）
_ALL_COLUMNS = list(_COLUMN_MAP.values()) + _EXTRA_COLUMNS + ["created_at", "updated_at"]
# 云表 → JSON 反向（signal_date → trigger_date）
_INVERSE = {v: k for k, v in _COLUMN_MAP.items()}


def cloud_enabled() -> bool:
    try:
        return cloud_db.enabled()
    except Exception:
        return False


def to_row(sig: dict) -> dict:
    """JSON 信号 → 云表行（固定列集合，None 补齐）。"""
    row = {c: None for c in _ALL_COLUMNS}
    for jkey, ckey in _COLUMN_MAP.items():
        val = sig.get(jkey)
        if val is not None:
            row[ckey] = val
    now = date.today().isoformat()
    if row["created_at"] is None:
        row["created_at"] = now
    row["updated_at"] = now
    return row


def from_row(row: dict) -> dict:
    """云表行 → JSON 信号 dict（去掉空列）。"""
    sig = {}
    for ckey, val in row.items():
        if val is None:
            continue
        jkey = _INVERSE.get(ckey, ckey)
        sig[jkey] = val
    if "signal_date" in row and "trigger_date" not in sig:
        sig["trigger_date"] = row["signal_date"]
    return sig


def cloud_load_signals() -> list[dict]:
    """从云库读取全部信号（按 signal_id 排序）。云库不可用 → 返回 []。"""
    if not cloud_enabled():
        return []
    try:
        rows = cloud_db.select("signal_tracking", order="signal_id")
        return [from_row(r) for r in rows]
    except Exception:
        return []


def cloud_load_by_date(signal_date: str) -> list[dict]:
    """按信号日期读取。signal_date: 'YYYY-MM-DD'。"""
    if not cloud_enabled():
        return []
    try:
        rows = cloud_db.select(
            "signal_tracking", filters=[("signal_date", "eq", signal_date)], order="signal_id"
        )
        return [from_row(r) for r in rows]
    except Exception:
        return []


def cloud_upsert_signals(records: list[dict]) -> int:
    """把信号记录 upsert 到云库（on_conflict=signal_id，幂等）。返回成功条数。"""
    if not records:
        return 0
    if not cloud_enabled():
        return 0
    rows = [to_row(r) for r in records]
    try:
        return cloud_db.upsert_many("signal_tracking", rows, on_conflict="signal_id")
    except Exception:
        return 0


def cloud_update_fields(signal_id: str, fields: dict) -> bool:
    """更新单条信号的部分字段（如复盘回填评价列）。"""
    if not cloud_enabled():
        return False
    allowed = {c: v for c, v in fields.items() if c in _ALL_COLUMNS}
    if not allowed:
        return False
    allowed["updated_at"] = date.today().isoformat()
    try:
        rows = cloud_db.update(
            "signal_tracking", allowed, filters=[("signal_id", "eq", signal_id)]
        )
        return len(rows) > 0
    except Exception:
        return False


def local_load_signals() -> list[dict]:
    """读本地 signal_tracking.json（过渡期只读缓存兜底）。"""
    if not LOCAL_TRACKING.exists():
        return []
    try:
        data = json.loads(LOCAL_TRACKING.read_text(encoding="utf-8"))
        return data.get("signals", [])
    except (json.JSONDecodeError, OSError):
        return []


def load_signals() -> list[dict]:
    """权威读：云库优先，云库不可用/为空 → 本地 JSON 兜底。"""
    rows = cloud_load_signals()
    if rows:
        return rows
    return local_load_signals()


def upsert_signals(records: list[dict], *, mirror_local: bool = True) -> int:
    """权威写：写入云库；mirror_local=True 时同时镜像写本地 JSON（过渡期）。"""
    ok = cloud_upsert_signals(records)
    if mirror_local:
        _mirror_local(records)
    return ok


def _mirror_local(records: list[dict]) -> None:
    """镜像写本地 signal_tracking.json（合并去重后写回，过渡期供文件消费方/云降级兜底）。

    决策 47：迁移后旧 JSON 已改名 signal_tracking.json.bak（保留一周作历史快照）。
    此处镜像写的是**重建的过渡缓存**（不是历史快照）：文件缺失时重建，.bak 保持不动。
    """
    try:
        data = json.loads(LOCAL_TRACKING.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}
    signals = data.setdefault("signals", [])
    by_id = {s.get("signal_id"): s for s in signals}
    for rec in records:
        by_id[rec.get("signal_id")] = rec
    data["signals"] = sorted(by_id.values(), key=lambda s: s.get("signal_id", ""))
    data["_updated"] = date.today().isoformat()
    try:
        LOCAL_TRACKING.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass
