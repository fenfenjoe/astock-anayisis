"""lifecycle.py — 常驻进程生命周期：主循环 / 健康探针 / RSS 节流.

设计：
- tick() 可独立调用并返回状态 dict（便于测试与手动触发）
- AgentLoop.run() 死循环（常驻入口 `python -m agent` 使用）
- heartbeat 写 metadata['agent_heartbeat']，dashboard 状态接口据此判断存活
"""
import time
from datetime import datetime

from agent import config, db as agent_db
from agent.core import behavior, knowledge


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


def tick(now=None, db=None, llm_fn=None):
    """一轮例行工作：heartbeat + RSS 增量（节流）+ 自定义源采集 + 发文调度。

    返回状态 dict：{"today", "rss", "custom", "publish"}；异常不抛出，记入返回。
    """
    now = now or datetime.now()
    db = db or agent_db
    today = now.strftime("%Y-%m-%d")
    heartbeat(db)

    result = {"today": today, "rss": None, "custom": None, "publish": None,
              "post": None}

    if _rss_due(db, now):
        try:
            result["rss"] = knowledge.fetch_and_store(db=db)
            db.meta_set("last_rss_fetch_at", now.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception as e:
            result["rss"] = {"error": str(e)}

    if _custom_due(db, now):
        try:
            result["custom"] = knowledge.collect_custom_sources(
                db=db, llm_fn=llm_fn)
            db.meta_set("last_custom_fetch_at", now.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception as e:
            result["custom"] = {"error": str(e)}

    # 发动态（③：微博式短文本，活跃时段 + 节流由 run_post_pipeline 判断）
    try:
        result["post"] = behavior.run_post_pipeline(
            now=now, llm_fn=llm_fn, db=db)
    except Exception as e:
        result["post"] = {"posted": False, "reason": f"error: {e}",
                          "post_id": None}

    try:
        result["publish"] = behavior.run_publish_pipeline(
            today, now=(now.hour, now.minute), llm_fn=llm_fn, db=db)
    except Exception as e:
        result["publish"] = {"published": False, "reason": f"error: {e}",
                             "article_id": None}
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
        except Exception as e:  # 兜底：单轮异常不杀进程
            self.last_error = str(e)
        return self.last_status

    def run(self):
        while not self._stop:
            self.run_once()
            time.sleep(self.tick_seconds)
