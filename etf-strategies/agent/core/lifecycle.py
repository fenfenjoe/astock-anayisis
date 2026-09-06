"""lifecycle.py — 常驻进程生命周期：主循环 / 健康探针 / 行为状态机.

设计：
- tick() 可独立调用并返回状态 dict（便于测试与手动触发）
- AgentLoop.run() 死循环（常驻入口 `python -m agent` 使用）
- heartbeat 写 metadata['agent_heartbeat']，dashboard 状态接口据此判断存活
"""

import time
from datetime import datetime, timedelta

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
    "writing": "📝 写文章",
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

    # 2.5 遗留清理：阅读/写文章是动作事件，绝不该跨 tick 还"未结束"（老模型遗留行在此关闭）
    _stale = db.activity_open()
    if _stale and _stale["kind"] in ("reading", "writing"):
        db.activity_close_open(now.strftime("%Y-%m-%d %H:%M:%S"))

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
        # 统一流转：自动切换也会"关旧开新"记录进活动台账（做过的事）
        behavior.switch_state(decision, now=now, db=db, source="auto")

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

    # 阅读执行（动作事件模型）：状态为"阅读"且本段尚未真实读过 → 执行一次；
    # 完成后自动回到常驻随机状态（阅读是事件，不长期占状态）。
    state_cur = db.meta_get("xiaoman_current_state")
    seq = db.meta_get("xiaoman_state_seq") or ""
    done_seq = db.meta_get("xiaoman_read_done_seq") or ""
    if state_cur == "reading" and seq and seq != done_seq:
        try:
            result["read"] = behavior.execute_reading(db=db, llm_fn=llm_fn)
            db.meta_set("xiaoman_read_done_seq", seq)
        except Exception as e:
            result["read"] = {"error": str(e)}
        try:
            behavior.switch_state(behavior.pick_random_state(db=db, now=now),
                                  now=now, db=db, source="auto")
        except Exception as e:
            cur = result.get("read") or {}
            result["read"] = {**cur, "after_read_state_error": str(e)}

    # 4. 每日发文（写文章是动作事件：期间状态临时显示"正在写文章"，结束后恢复原常驻状态）
    _prev_state = db.meta_get("xiaoman_current_state")
    _prev_until = db.meta_get("xiaoman_state_until")
    db.meta_set("xiaoman_current_state", "writing")
    db.meta_set("xiaoman_state_until",
                (now + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S"))
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
    finally:
        if _prev_state:
            db.meta_set("xiaoman_current_state", _prev_state)
        if _prev_until:
            db.meta_set("xiaoman_state_until", _prev_until)

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
