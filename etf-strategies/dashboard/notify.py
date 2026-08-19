"""企业微信信号触发通知 — 配置 / WeCom 客户端 / 信号解析 / Watcher.

架构：
- load_config(): 读 dashboard/data/notify_config.json（每次调用重读，改配置即生效）
- WeCom 客户端：get_access_token()（7200s 缓存，提前 300s 刷新）+ send_text() + send_test()
- 信号解析（纯函数，可测）：parse_trigger_records() 解析 每日信号.md 的 `## 信号触发记录` 表
- 去重 + 扫描：diff_new_triggers() / scan()，已推送 key 存 portfolio_meta（notify_sent_triggers）
- Watcher：daemon 线程每 poll_seconds 扫一次（照抄 scheduler.SchedulerEngine 模式）

检测点：auto_intraday_check.md 第 5.2 步强制"所有已触发信号（P0/P1/P2）必须
在 `## 信号触发记录` 表追加一行" —— 该表是"信号已触发"的权威事件日志，
watcher 直接解析它即可，无需改任何 prompt。
"""
import json
import threading
import time
from datetime import datetime, time as dtime
from pathlib import Path

import requests

from dashboard import db, scheduler

CONFIG_PATH = Path(__file__).resolve().parent / "data" / "notify_config.json"

DEFAULT_CONFIG = {
    "enabled": False,
    "corpid": "",          # 企业微信 企业ID（我的企业 → 企业ID）
    "agentid": 0,          # 自建应用的 AgentId
    "secret": "",          # 自建应用的 Secret
    "touser": "",          # 接收人 userid（通讯录账号，非微信号）；"@all"=全部可见成员
    "poll_seconds": 30,    # watcher 轮询间隔
    "only_trading_hours": True,  # 仅交易日 09:00-16:00 内推送
}

# 触发记录中可操作的当前状态（其余如 已废弃/已过期/已取消 不推送）
ACTIONABLE = {"已触发", "已升级", "触发"}

GETTOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
SEND_URL = "https://qyapi.weixin.qq.com/cgi-bin/message/send"
REQUEST_TIMEOUT = 10

# ── access_token 缓存（有效期 7200s，提前 300s 刷新）──
_token_cache: dict = {"token": None, "expires_at": 0.0}
_token_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════
# 配置加载
# ═══════════════════════════════════════════════════════════════

def load_config() -> dict:
    """读 notify_config.json；缺失/损坏返回默认（enabled=False）。每次调用重读。"""
    cfg = dict(DEFAULT_CONFIG)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        for k in cfg:
            if k in data:
                cfg[k] = data[k]
    except (OSError, json.JSONDecodeError):
        pass
    return cfg


def config_ready(cfg: dict) -> bool:
    """凭证是否齐备可推送。"""
    return bool(cfg.get("enabled") and cfg.get("corpid") and cfg.get("secret")
                and cfg.get("touser") and cfg.get("agentid"))


# ═══════════════════════════════════════════════════════════════
# WeCom 客户端（企业微信官方 API）
# ═══════════════════════════════════════════════════════════════

def get_access_token(cfg: dict) -> str:
    """取 access_token（模块级缓存，有效期 7200s，提前 300s 刷新）。"""
    now = time.time()
    with _token_lock:
        if _token_cache["token"] and now < _token_cache["expires_at"] - 300:
            return _token_cache["token"]
        resp = requests.get(
            GETTOKEN_URL,
            params={"corpid": cfg["corpid"], "corpsecret": cfg["secret"]},
            timeout=REQUEST_TIMEOUT,
        )
        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise RuntimeError(f"gettoken 失败: {data}")
        _token_cache["token"] = data["access_token"]
        _token_cache["expires_at"] = now + int(data.get("expires_in", 7200))
        return _token_cache["token"]


def _post_send(token: str, cfg: dict, content: str) -> dict:
    return requests.post(
        f"{SEND_URL}?access_token={token}",
        json={
            "touser": cfg["touser"],
            "msgtype": "text",
            "agentid": int(cfg["agentid"]),
            "text": {"content": content},
        },
        timeout=REQUEST_TIMEOUT,
    ).json()


def send_text(content: str) -> dict:
    """发一条 text 消息给 touser。成功 {"ok": True}；失败 {"ok": False, "error": ...}。"""
    cfg = load_config()
    if not config_ready(cfg):
        return {"ok": False, "error": "notify_config.json 未配置或未启用"}
    try:
        data = _post_send(get_access_token(cfg), cfg, content)
        if data.get("errcode", 0) == 0:
            return {"ok": True}
        # 40014/42001 = token 失效/过期 → 清缓存重试一次
        if data.get("errcode") in (40014, 42001):
            with _token_lock:
                _token_cache["token"] = None
            data = _post_send(get_access_token(cfg), cfg, content)
        return {"ok": data.get("errcode", 0) == 0, "error": data}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def send_test() -> dict:
    """发一条固定测试消息，验证凭证链路。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return send_text(f"【信号通知·测试】\n配置链路正常 ✅\n发送时间：{now}")


# ═══════════════════════════════════════════════════════════════
# 信号解析（纯函数，可测）
# ═══════════════════════════════════════════════════════════════

def parse_trigger_records(markdown: str) -> list[dict]:
    """解析 每日信号.md 的 `## 信号触发记录` 表。

    返回 [{trigger_time, signal_id, priority, ticker, action_type,
          condition, status, suggest}, ...]。表头缺失列容错，跳过分隔/空行。
    """
    if not markdown:
        return []
    records = []
    in_section = False
    header_cols: dict | None = None
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped.startswith("## 信号触发记录")
            header_cols = None
            continue
        if not in_section or not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if header_cols is None:
            # 表头行：列名 → 索引 映射（兼容列名差异）
            header_cols = {name: i for i, name in enumerate(cells) if name}
            continue
        # 分隔行 |---|---| 与占位行（暂无）
        if all(not c or set(c) <= {"-", ":"} for c in cells):
            continue
        if not any(cells) or "暂无" in stripped:
            continue

        def _col(*names: str) -> str:
            for n in names:
                if n in header_cols and header_cols[n] < len(cells):
                    return cells[header_cols[n]]
            return ""

        rec = {
            "trigger_time": _col("触发时间", "时间"),
            "signal_id": _col("信号ID"),
            "priority": _col("优先级"),
            "ticker": _col("标的"),
            "action_type": _col("操作类型"),
            "condition": _col("触发条件摘要", "触发条件"),
            "status": _col("当前状态", "状态"),
            "suggest": _col("建议操作"),
        }
        if rec["signal_id"]:
            records.append(rec)
    return records


def build_message(rec: dict) -> str:
    """组装推送正文（纯文本）。"""
    head = f"⚠️ 信号触发 {rec.get('trigger_time') or ''}".strip()
    body = f"{rec.get('signal_id')} | {rec.get('priority') or ''} " \
           f"{rec.get('ticker') or ''} {rec.get('action_type') or ''}".strip()
    lines = [head, body]
    cond = (rec.get("condition") or "").strip()
    if cond:
        lines.append(f"条件: {cond}")
    sugg = (rec.get("suggest") or "").strip()
    if sugg:
        lines.append(f"建议: {sugg}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 去重 + 扫描
# ═══════════════════════════════════════════════════════════════

def _key_of(rec: dict) -> str:
    """去重 key：信号ID + 触发时间（同一信号同日只推一次）。"""
    return f"{rec.get('signal_id')}|{rec.get('trigger_time')}"


def _sent_keys() -> set:
    raw = db.meta_get("notify_sent_triggers")
    if not raw:
        return set()
    try:
        return set(json.loads(raw))
    except (json.JSONDecodeError, TypeError):
        return set()


def _save_sent_keys(keys: set) -> None:
    db.meta_set("notify_sent_triggers", json.dumps(sorted(keys), ensure_ascii=False))


def diff_new_triggers(records: list[dict], sent_keys: set) -> list[dict]:
    """过滤出 ACTIONABLE 且 key 不在已推送集合中的记录（纯逻辑，可测）。"""
    return [r for r in records
            if (r.get("status") or "") in ACTIONABLE and _key_of(r) not in sent_keys]


def scan() -> dict:
    """扫描今日 每日信号.md 的触发记录，推送新触发并持久化去重。

    返回 {sent, new:[signal_id], skipped, reason?}。
    发送失败的 key 不写入 sent，下轮重试；单条失败不中断其余。
    """
    cfg = load_config()
    if not config_ready(cfg):
        return {"sent": 0, "new": [], "skipped": 0, "reason": "not_configured"}
    today = datetime.now().strftime("%Y%m%d")
    report = db.report_get(today, "每日信号")
    if report is None:
        return {"sent": 0, "new": [], "skipped": 0, "reason": "no_report"}

    records = parse_trigger_records(report["markdown"])
    new = diff_new_triggers(records, _sent_keys())
    if not new:
        return {"sent": 0, "new": [], "skipped": 0, "reason": "no_new"}

    pushed, keys_added, errors = 0, [], []
    for rec in new:
        res = send_text(build_message(rec))
        if res.get("ok"):
            pushed += 1
            keys_added.append(_key_of(rec))
        else:
            errors.append({_key_of(rec): res.get("error")})

    if keys_added:
        _save_sent_keys(_sent_keys() | set(keys_added))

    result = {
        "sent": pushed,
        "new": [rec["signal_id"] for rec in new],
        "skipped": len(new) - pushed,
    }
    if errors:
        result["errors"] = errors
    return result


# ═══════════════════════════════════════════════════════════════
# Watcher：daemon 线程每 poll_seconds 扫一次（照抄 SchedulerEngine）
# ═══════════════════════════════════════════════════════════════

class NotifyWatcher:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.last_scan: str | None = None
        self.last_result: dict | None = None
        self.last_error: str | None = None

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        with self._lock:
            if self.running():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name="notify-watcher")
            self._thread.start()
            print("[notify] watcher started")

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                self.last_error = str(e)
            cfg = load_config()
            interval = max(10, int(cfg.get("poll_seconds", 30)))
            self._stop.wait(interval)

    def _tick(self):
        cfg = load_config()
        if not config_ready(cfg):
            return  # 未配置：静默跳过
        if cfg.get("only_trading_hours", True):
            now = datetime.now()
            if not scheduler.is_trading_day(now.date()):
                return
            if not (dtime(9, 0) <= now.time() <= dtime(16, 0)):
                return
        try:
            self.last_result = scan()
            self.last_scan = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            self.last_error = str(e)

    def status(self) -> dict:
        cfg = load_config()
        return {
            "running": self.running(),
            "enabled": bool(cfg.get("enabled")),
            "configured": config_ready(cfg),
            "poll_seconds": cfg.get("poll_seconds"),
            "last_scan": self.last_scan,
            "last_result": self.last_result,
            "last_error": self.last_error,
        }


watcher = NotifyWatcher()


def start() -> None:
    """app lifespan 调用：启动 watcher（幂等）。"""
    watcher.start()
