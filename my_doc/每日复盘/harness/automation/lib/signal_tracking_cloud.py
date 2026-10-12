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
    "trade_price": "trade_price",
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
    "trigger_price", "trigger_time", "entry_time",
]
# 云表全部列（固定集合，保证批量 upsert 各行键一致）
_ALL_COLUMNS = list(_COLUMN_MAP.values()) + _EXTRA_COLUMNS + ["created_at", "updated_at"]
# 云表 → JSON 反向（signal_date → trigger_date）
_INVERSE = {v: k for k, v in _COLUMN_MAP.items()}

# 状态终态等级（2026-09-21 BUG-FIX）：等级越高越"终态"，越不可被盘中检查回退。
# 背景：盘中检查 §5.3 用 parse_signal_rows_all 重新解析 markdown 后整体 upsert，
# 会把用户已在 Dashboard 一键执行（云库 executed）的信号覆盖成 expired/triggered。
# 等级：open(未触发) < triggered(已触发) < expired(已过期) < executed(已执行)=partial(部分执行) < settled(已结算)
_STATUS_FINALITY = {
    "open": 0,
    "triggered": 1,
    "expired": 2,
    "executed": 3,
    "partial_executed": 3,
    "settled": 4,
}

# 枚举约束复用 lib/signal_tracking.py 的权威定义（docs/signal-enums.md 同口径），避免双份漂移
from lib.signal_tracking import assert_valid_signal_record  # noqa: E402


def _validate_row(row: dict) -> dict:
    """写入/更新前逐字段枚举/数值校验（复用权威 assert_valid_signal_record）。"""
    return assert_valid_signal_record(row)


def cloud_enabled() -> bool:
    try:
        return cloud_db.enabled()
    except Exception:
        return False


def to_row(sig: dict) -> dict:
    """JSON 信号 → 云表行（写前枚举/数值校验）。

    2026-09-14 任务4 关键改动：**跳过值为 None 的列**（不再全列填充 None）。
    原因：upsert 是 merge-duplicates，只更新 payload 中出现的列；盘中已写的
    trigger_price/trigger_time 与复盘已写的 entry_price/entry_time 若在这里以 None
    出现，会把云库既有值覆盖清空。跳过 None 列 → 各阶段写入互补、互不清空。
    """
    row = {}
    for jkey, ckey in _COLUMN_MAP.items():
        val = sig.get(jkey)
        if val is not None:
            row[ckey] = val
    for c in _EXTRA_COLUMNS:
        if sig.get(c) is not None:
            row[c] = sig.get(c)
    _validate_row(row)
    now = date.today().isoformat()
    row.setdefault("created_at", now)
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


def protect_terminal_status(records: list[dict], existing_status: dict) -> list[dict]:
    """保护已执行/已结算信号的终态状态不被回退（纯函数，可测）。

    existing_status: {signal_id: status} — 云库当前状态。
    对每条记录：若云库既有状态终态等级 ≥ 新记录状态等级，则保留云库既有状态
    （防止盘中检查把 executed/partial_executed/settled 降级成 expired/triggered/open）。
    新信号（云库无既有状态）或升级流转（triggered→executed 等）不受影响。
    返回新列表，不改入参。
    """
    out = []
    for rec in records:
        r = dict(rec)
        sid = r.get("signal_id")
        cur = existing_status.get(sid)
        new = r.get("status")
        if cur and new and _STATUS_FINALITY.get(cur, 0) >= _STATUS_FINALITY.get(new, 0):
            r["status"] = cur
        out.append(r)
    return out


def _protect_existing_terminal(records: list[dict]) -> list[dict]:
    """查询云库既有状态，应用终态状态保护（查询失败不阻塞，按原记录 upsert）。"""
    ids = [r.get("signal_id") for r in records if r.get("signal_id")]
    if not ids:
        return records
    existing = {}
    try:
        rows = cloud_db.select(
            "signal_tracking",
            columns="signal_id,status",
            filters=[("signal_id", "in", f"({','.join(ids)})")],
        )
        existing = {r.get("signal_id"): r.get("status") for r in rows if r.get("signal_id")}
    except Exception:
        return records
    return protect_terminal_status(records, existing)


def cloud_upsert_signals(records: list[dict]) -> int:
    """把信号记录 upsert 到云库（on_conflict=signal_id，幂等）。返回成功条数。

    写入前逐条做枚举/数值校验：非法值抛 ValueError，由调用方决定中断或跳过。
    2026-09-21 BUG-FIX：upsert 前查询云库既有状态并应用终态保护，
    防止盘中检查把已执行/已结算信号的状态覆盖回退。
    """
    if not records:
        return 0
    if not cloud_enabled():
        return 0
    records = _protect_existing_terminal(records)
    rows = [to_row(r) for r in records]
    try:
        return cloud_db.upsert_many("signal_tracking", rows, on_conflict="signal_id")
    except Exception:
        return 0


def cloud_update_fields(signal_id: str, fields: dict) -> bool:
    """更新单条信号的部分字段（如盘中触发价/复盘回填评价列）。含枚举/数值校验。

    2026-09-21 BUG-FIX：若 fields 含 status，先查云库既有状态并应用终态保护，
    防止已执行/已结算信号被降级回退（与 cloud_upsert_signals 同一规则）。
    """
    if not cloud_enabled():
        return False
    _validate_row(fields)
    allowed = {c: v for c, v in fields.items() if c in _ALL_COLUMNS}
    if not allowed:
        return False
    # 终态保护：status 变更需先取既有状态
    if "status" in allowed:
        try:
            rows = cloud_db.select(
                "signal_tracking",
                columns="signal_id,status",
                filters=[("signal_id", "eq", signal_id)],
                limit=1,
            )
        except Exception:
            rows = []
        if rows:
            cur = rows[0].get("status")
            new = allowed["status"]
            if cur and new and _STATUS_FINALITY.get(cur, 0) >= _STATUS_FINALITY.get(new, 0):
                allowed["status"] = cur
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


# ── 信号触发记录（2026-09-21 新增：盘中触发记录明细落库）────────────
# 表 signal_trigger_records：一行 = 一次信号触发事件，signal_id 关联 signal_tracking。
# 由盘中检查 §5.2 写入，Dashboard「每日信号」页点击信号展开展示。

_TRIGGER_RECORD_COLUMNS = [
    "signal_id", "trigger_date", "trigger_time", "priority", "ticker", "name",
    "action_type", "condition", "status", "suggest", "result",
]


def to_trigger_row(rec: dict) -> dict:
    """触发记录 dict → 云表行（跳过 None 列，upsert 互补不覆盖）。"""
    row = {}
    for c in _TRIGGER_RECORD_COLUMNS:
        val = rec.get(c)
        if val is not None:
            row[c] = val
    if not row.get("signal_id") or not row.get("trigger_time"):
        return {}
    row.setdefault("created_at", date.today().isoformat())
    row["updated_at"] = date.today().isoformat()
    return row


def cloud_upsert_trigger_records(records: list[dict]) -> int:
    """把盘中生成的信号触发记录 upsert 到云库 signal_trigger_records 表。

    幂等键：signal_id + trigger_time（同信号同触发时间只一条，同检查点重跑不重复）。
    返回成功条数；云库不可用/异常返回 0（不抛错，调用方降级记录日志）。
    """
    if not records:
        return 0
    if not cloud_enabled():
        return 0
    rows = [to_trigger_row(r) for r in records]
    rows = [r for r in rows if r]
    if not rows:
        return 0
    try:
        return cloud_db.upsert_many(
            "signal_trigger_records", rows, on_conflict="signal_id,trigger_time"
        )
    except Exception:
        return 0


def cloud_load_trigger_records(signal_id: str | None = None,
                               trigger_date: str | None = None,
                               limit: int = 100) -> list[dict]:
    """读云库 signal_trigger_records（可按 signal_id / 触发日期过滤，时间倒序）。

    云库不可用返回 []（不抛错）。
    """
    if not cloud_enabled():
        return []
    filters = []
    if signal_id:
        filters.append(("signal_id", "eq", signal_id))
    if trigger_date:
        filters.append(("trigger_date", "eq", trigger_date))
    try:
        return cloud_db.select(
            "signal_trigger_records",
            filters=filters,
            order="trigger_date.desc,trigger_time.desc",
            limit=limit,
        )
    except Exception:
        return []


# ── 盘中检查记录（2026-09-24 新增：每次盘中检查对每条信号的检查结果落库）────────
# 表 signal_check_records：一行 = 一条信号 × 一个检查点（check_time）。
# 与 signal_trigger_records 的区别：触发记录只记"已触发"事件；本表记**每次检查**的
# 完整结果（现价 vs 交易价、触发判定、状态流转、检查摘要），供 Dashboard「今日信号」
# 页点击信号行展开查看盘中检查轨迹。由盘中检查 prompt 写入（§5.2b）。

_CHECK_RECORD_COLUMNS = [
    "signal_id", "check_date", "check_time", "check_point", "ticker", "name",
    "price", "trade_price", "condition_met", "status_before", "status_after", "note",
]


def to_check_row(rec: dict) -> dict:
    """检查记录 dict → 云表行（跳过 None 列，upsert 互补不覆盖）。"""
    row = {}
    for c in _CHECK_RECORD_COLUMNS:
        val = rec.get(c)
        if val is not None:
            row[c] = val
    if not row.get("signal_id") or not row.get("check_time"):
        return {}
    row.setdefault("created_at", date.today().isoformat())
    row["updated_at"] = date.today().isoformat()
    return row


def cloud_upsert_check_records(records: list[dict]) -> int:
    """把盘中每次检查的记录 upsert 到云库 signal_check_records 表。

    幂等键：signal_id + check_date + check_time（同信号同检查点只一条，同检查点重跑不重复）。
    返回成功条数；云库不可用/异常返回 0（不抛错，调用方降级记录日志）。
    """
    if not records:
        return 0
    if not cloud_enabled():
        return 0
    rows = [to_check_row(r) for r in records]
    rows = [r for r in rows if r]
    if not rows:
        return 0
    try:
        return cloud_db.upsert_many(
            "signal_check_records", rows, on_conflict="signal_id,check_date,check_time"
        )
    except Exception:
        return 0


def cloud_load_check_records(signal_id: str | None = None,
                             check_date: str | None = None,
                             limit: int = 200) -> list[dict]:
    """读云库 signal_check_records（可按 signal_id / 检查日期过滤，时间倒序）。

    云库不可用返回 []（不抛错）。
    """
    if not cloud_enabled():
        return []
    filters = []
    if signal_id:
        filters.append(("signal_id", "eq", signal_id))
    if check_date:
        filters.append(("check_date", "eq", check_date))
    try:
        return cloud_db.select(
            "signal_check_records",
            filters=filters,
            order="check_date.desc,check_time.desc",
            limit=limit,
        )
    except Exception:
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
