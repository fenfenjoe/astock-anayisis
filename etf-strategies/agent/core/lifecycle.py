"""lifecycle.py — 常驻进程生命周期：主循环 / 健康探针 / 行为状态机.

设计：
- tick() 可独立调用并返回状态 dict（便于测试与手动触发）
- AgentLoop.run() 死循环（常驻入口 `python -m agent` 使用）
- heartbeat 写 metadata['agent_heartbeat']，dashboard 状态接口据此判断存活
"""

import time
from datetime import datetime

from agent import config, db as agent_db
from agent.core import behavior, knowledge

_STATE_LABELS = {
    "reading": "📖 阅读",
    "gaming": "🎮 打游戏",
    "drama": "🎬 煲剧",
    "shopping": "🛍️ 逛淘宝",
    "music": "🎧 听歌",
    "cooking": "🍳 煮泡面",
    "cat": "🐱 撸猫",
    "yoga": "🧘 做瑜伽",
    "tea": "☕ 喝奶茶",
    "drawing": "🎨 画画",
    "social": "📱 刷朋友圈",
    "cleaning": "🧹 收拾房间",
    "takeout": "🍜 叫外卖",
    "nap": "💤 补觉",
    "daydream": "🌙 发呆",
    "sleep": "😴 睡觉",
    "emo": "🌧️ emo",
    "writing": "📝 写日记",
    "thinking": "💡 思考",
}


def heartbeat(db=None):
    db = db or agent_db
    db.meta_set("agent_heartbeat", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def heartbeat_age_seconds(db=None, now=None):
    """heartbeat 距今秒数；无 heartbeat/格式异常返回 None。"""
    db = db or agent_db
    raw = db.meta_get("agent_heartbeat")
    if not raw:
        return None
    try:
        hb = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    now = now or datetime.now()
    return (now - hb).total_seconds()


def _rss_due(db, now):
    last = db.meta_get("last_rss_fetch_at")
    if not last:
        return True
    try:
        prev = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return True
    return (now - prev).total_seconds() >= config.RSS_FETCH_INTERVAL_SECONDS


def _custom_due(db, now):
    last = db.meta_get("last_custom_fetch_at")
    if not last:
        return True
    try:
        prev = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return True
    return (now - prev).total_seconds() >= config.CUSTOM_SOURCE_FETCH_INTERVAL_SECONDS


def _state_label(state_id):
    return _STATE_LABELS.get(state_id, "🌙 发呆")


def tick(now=None, db=None, llm_fn=None):
    """一轮例行工作。

    1. heartbeat
    2. 上线/下线闸门：xiaoman_online != "1" → 只写 heartbeat，其余全跳过
    3. RSS 入库（服务端自动拉取，不进 Prompt）
    4. 自定义源采集（节流，高成本 6h 间隔）
    5. 状态机：检查过期 → 硬编码权重选状态 → 选中"阅读"时执行阅读 Prompt
    6. 每日发文调度
    7. cloud backup
    """
    now = now or datetime.now()
    db = db or agent_db
    today = now.strftime("%Y-%m-%d")
    heartbeat(db)

    result = {
        "today": today,
        "online": False,
        "rss": None,
        "custom": None,
        "state": None,
        "read": None,
        "publish": None,
    }

    # 0. 上线/下线闸门
    online = db.meta_get("xiaoman_online")
    if online != "1":
        result["online"] = False
        return result

    result["online"] = True

    # 1. RSS 入库（服务端自动执行，不入 Prompt；小满"阅读"时从库中选）
    if _rss_due(db, now):
        try:
            rss_result = knowledge.fetch_and_store(db=db)
            result["rss"] = rss_result
            db.meta_set("last_rss_fetch_at", now.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception as e:
            result["rss"] = {"error": str(e)}

    # 2. 自定义源采集（节流，LLM 调用）
    if _custom_due(db, now):
        try:
            result["custom"] = knowledge.collect_custom_sources(db=db, llm_fn=llm_fn)
            db.meta_set("last_custom_fetch_at", now.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception as e:
            result["custom"] = {"error": str(e)}

    # 3. 状态机
    state_current = db.meta_get("xiaoman_current_state")
    state_until = db.meta_get("xiaoman_state_until")
    state_expired = True
    if state_until:
        try:
            if datetime.strptime(state_until, "%Y-%m-%d %H:%M:%S") > now:
                state_expired = False
        except ValueError:
            pass

    if state_expired:
        decision = behavior.pick_random_state(db=db, now=now)
        until_dt = datetime.fromisoformat(decision["until_iso"])
        db.meta_set("xiaoman_current_state", decision["id"])
        db.meta_set("xiaoman_state_until", until_dt.strftime("%Y-%m-%d %H:%M:%S"))

        if decision["require_llm"] and decision["id"] == "reading":
            try:
                result["read"] = behavior.execute_reading(db=db, llm_fn=llm_fn)
            except Exception as e:
                result["read"] = {"error": str(e)}

        result["state"] = {
            "id": decision["id"],
            "label": decision["label"],
            "duration_minutes": decision["duration_minutes"],
            "until": decision["until_display"],
        }
    else:
        result["state"] = {
            "id": state_current or "daydream",
            "label": _state_label(state_current or "daydream"),
            "active": True,
        }

    # 4. 每日发文
    try:
        result["publish"] = behavior.run_publish_pipeline(
            today, now=(now.hour, now.minute), llm_fn=llm_fn, db=db
        )
    except Exception as e:
        result["publish"] = {
            "published": False,
            "reason": f"error: {e}",
            "article_id": None,
        }

    # 5. cloud backup
    try:
        result["backup"] = agent_db.cloud_backup()
    except Exception as e:
        result["backup"] = {"error": str(e)}
    return result


class AgentLoop:
    """常驻主循环：每 TICK_SECONDS 跑一次 tick（daemon 线程友好）。"""

    def __init__(self, tick_seconds=None, db=None):
        self.tick_seconds = tick_seconds or config.TICK_SECONDS
        self.db = db or agent_db
        self._stop = False
        self.last_status = None
        self.last_error = None

    def stop(self):
        self._stop = True

    def run_once(self):
        try:
            self.last_status = tick(db=self.db)
            self.last_error = None
        except Exception as e:
            self.last_error = str(e)
        return self.last_status

    def run(self):
        while not self._stop:
            self.run_once()
            time.sleep(self.tick_seconds)
