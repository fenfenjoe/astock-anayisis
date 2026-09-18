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

# heartbeat 节流：上一次真正写入云库的时间戳（见 heartbeat()）
_last_heartbeat_ts: float = 0.0

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
    "weibo_browse": "📱 逛微博",
    "xhs_browse": "📕 逛小红书",
    "zhihu_browse": "🔵 逛知乎",
    "xueqiu_browse": "🟡 逛雪球",
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
    """写 agent_heartbeat（云库）。

    2026-09-17 节流：cloud 模式下 heartbeat 每 tick（300s）都会被调用，若每次都写
    云库，workspace 永远无法进入「算力空闲自动挂起」。改为每 _HEARTBEAT_INTERVAL
    （600s）才真正写一次云库。dashboard 仅展示 heartbeat_age_seconds（无硬性死亡
    判定），节流到 10 分钟安全。file 模式不节流（保持每 tick 写，测试语义不变）。
    """
    global _last_heartbeat_ts
    db = db or agent_db
    if getattr(agent_db, "USE_CLOUD", False):
        now_ts = time.time()
        if now_ts - _last_heartbeat_ts < agent_db._HEARTBEAT_INTERVAL:
            return  # 节流：尚未到写入窗口
        _last_heartbeat_ts = now_ts
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
        "scheduler": None,
    }

    # 0. 上线/下线闸门
    online = db.meta_get("xiaoman_online")
    if online != "1":
        result["online"] = False
        return result

    result["online"] = True

    # 0.5 定时任务调度：Agent 进程自己检查到点任务并执行（写云库 scheduler_runs）
    try:
        from agent.core import scheduler_agent

        result["scheduler"] = scheduler_agent.tick(now=now)
    except Exception as e:
        result["scheduler"] = {"error": str(e)}

    # 1. RSS 入库（服务端自动执行，不入 Prompt；小满"阅读"时从库中选）
    if _rss_due(db, now):
        try:
            rss_result = knowledge.fetch_and_store(db=db)
            result["rss"] = rss_result
            # BUG-FIX(2026-09-07)：仅当"配置了源且全部拉取失败"才不推进 last_rss_fetch_at ——
            # 原先所有源失败时 fetch_and_store 返回 errors 列表而不抛异常，这里仍无条件
            # 更新时间戳 → RSSHub 长期挂掉时看板显示"健康"实则零新素材（假健康盲区）。
            # feeds==0（未配置源）不属于"全部失败"，照常推进以保持节流语义。
            n_feeds = (rss_result or {}).get("feeds", 0)
            n_errors = len((rss_result or {}).get("errors") or [])
            if not (n_feeds > 0 and n_errors >= n_feeds):
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

    # 2.5 遗留清理：阅读/写文章/逛社交是动作事件，绝不该跨 tick 还"未结束"（老模型遗留行在此关闭）
    _stale = db.activity_open()
    if _stale:
        _kind = _stale["kind"]
        _browse_kind = (
            config.browse_state_to_platform(_kind) is not None  # 状态 id 形（weibo_browse）
            or _kind.startswith("browse_")                      # 活动 kind 形（browse_weibo）
        )
        if _kind in {"reading", "writing"} or _browse_kind:
            db.activity_close_open(now.strftime("%Y-%m-%d %H:%M:%S"))

    # 3. 状态机
    # 2026-09-17 节流优化：一次 meta_get_many 预取全部状态 key（冷读 1 次往返
    # 填满进程内 TTL 缓存），后续 meta_get 全命中缓存；switch_state 写穿透
    # 更新缓存 → 同 tick 后续读仍是新值。
    _prefetch = db.meta_get_many([
        "xiaoman_current_state", "xiaoman_state_until",
        "xiaoman_state_seq", "xiaoman_read_done_seq",
        "xiaoman_browse_done_seq", "published_on",
    ])
    state_current = _prefetch.get("xiaoman_current_state")
    state_until = _prefetch.get("xiaoman_state_until")
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

    # 逛社交执行（动作事件模型，方案 v1.10 §9.4）：
    # 状态为"逛微博/逛小红书/逛知乎/逛雪球"且本段尚未逛过 → Playwright 采集 + 复用阅读管道浏览
    # + 动态直接发；完成后回到常驻随机状态。一次只逛一个平台（当前状态的平台，同轮串行）。
    browse_done_seq = db.meta_get("xiaoman_browse_done_seq") or ""
    _browse_platform = config.browse_state_to_platform(state_cur)
    if _browse_platform and seq and seq != browse_done_seq:
        platform_id = _browse_platform
        try:
            result["browse"] = behavior.execute_browse(
                platform_id, db=db, llm_fn=llm_fn
            )
            db.meta_set("xiaoman_browse_done_seq", seq)
        except Exception as e:
            result["browse"] = {"error": str(e)}
        try:
            behavior.switch_state(behavior.pick_random_state(db=db, now=now),
                                  now=now, db=db, source="auto")
        except Exception as e:
            cur = result.get("browse") or {}
            result["browse"] = {**cur, "after_browse_state_error": str(e)}

    # 4. 每日发文（写文章是动作事件：期间状态临时显示"正在写文章"，结束后恢复原常驻状态）
    # 2026-09-17 节流修复：先 should_publish 门控，不该发文就不碰云库——
    # 原实现无条件先写 current_state=writing + state_until（+ 结束恢复 2 次）共 4 次
    # 云库写/每 tick → 阻止 workspace 进入「算力空闲自动挂起」（访问间隔恒 300s）。
    # run_publish_pipeline 内部仍会二次门控（幂等），此处只省掉不该发文时的空写。
    _published_on = _prefetch.get("published_on")
    _publish_gate = behavior.should_publish(
        today, _published_on, hour=now.hour, minute=now.minute
    )
    if _publish_gate["publish"]:
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
    else:
        result["publish"] = {"published": False, "reason": _publish_gate["reason"]}

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
