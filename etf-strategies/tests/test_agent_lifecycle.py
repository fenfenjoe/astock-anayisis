"""agent/core/lifecycle.py — 常驻主循环 / 健康探针 / RSS 节流。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, timedelta

import pytest

from agent import db as agent_db
from agent.core import lifecycle


def test_heartbeat_and_age(tmp_path):
    agent_db.init_db(tmp_path / "agent.db")
    try:
        assert lifecycle.heartbeat_age_seconds() is None
        lifecycle.heartbeat()
        assert lifecycle.heartbeat_age_seconds() is not None
    finally:
        agent_db.init_db(None)


def test_tick_writes_heartbeat_and_rss_throttle(tmp_path, monkeypatch):
    agent_db.init_db(tmp_path / "agent.db")
    try:
        # BUG-024 (2026-09-07) 修复: 3bcc9d0 新增"上线/下线闸门"，
        # xiaoman_online != "1" → tick 只写 heartbeat 即返回。按新契约设置在线标志。
        agent_db.meta_set("xiaoman_online", "1")
        calls = {"rss": 0}

        def fake_fetch_and_store(db=None, instances=None):
            calls["rss"] += 1
            return {"feeds": 0, "added": 0, "errors": []}

        monkeypatch.setattr(lifecycle.knowledge, "fetch_and_store",
                            fake_fetch_and_store)
        now = datetime(2026, 8, 27, 18, 0)
        r1 = lifecycle.tick(now=now, llm_fn=lambda m: "x")
        assert r1["rss"] is not None
        assert calls["rss"] == 1
        # 紧接第二次：RSS 未到期（节流），不再拉
        r2 = lifecycle.tick(now=now, llm_fn=lambda m: "x")
        assert r2["rss"] is None
        assert calls["rss"] == 1
        assert agent_db.meta_get("agent_heartbeat") is not None
        # 素材不足 → 不发文（reason 明确）
        assert r1["publish"]["published"] is False
        assert r1["publish"]["reason"] == "material_insufficient"
    finally:
        agent_db.init_db(None)


def test_tick_offline_writes_only_heartbeat(tmp_path, monkeypatch):
    """BUG-024 (2026-09-07): 3bcc9d0 上线/下线闸门 — 下线时 tick 只写 heartbeat，
    RSS/自定义采集/发文全部跳过（不执行任何高成本动作）。"""
    agent_db.init_db(tmp_path / "agent.db")
    try:
        calls = {"rss": 0}

        def fake_fetch_and_store(db=None, instances=None):
            calls["rss"] += 1
            return {"feeds": 0, "added": 0, "errors": []}

        monkeypatch.setattr(lifecycle.knowledge, "fetch_and_store",
                            fake_fetch_and_store)
        now = datetime(2026, 8, 27, 18, 0)
        # 未设置 xiaoman_online（≠ "1"）→ 下线态
        r = lifecycle.tick(now=now, llm_fn=lambda m: "x")
        assert r["online"] is False
        assert r["rss"] is None
        assert calls["rss"] == 0
        assert r["publish"] is None
        assert agent_db.meta_get("agent_heartbeat") is not None  # heartbeat 仍写入
    finally:
        agent_db.init_db(None)


def test_tick_browse_state_executes_and_falls_back(tmp_path, monkeypatch):
    """方案 v1.10 §9.4：tick 进入"逛微博"状态 → execute_browse 执行 → 回退常驻状态。"""
    agent_db.init_db(tmp_path / "agent.db")
    try:
        agent_db.meta_set("xiaoman_online", "1")
        # 手工把状态置为 weibo_browse（seq 未消费），模拟状态机选中逛状态
        agent_db.meta_set("xiaoman_current_state", "weibo_browse")
        agent_db.meta_set("xiaoman_state_until",
                          (datetime(2026, 9, 8, 14, 5)).strftime("%Y-%m-%d %H:%M:%S"))
        agent_db.meta_set("xiaoman_state_seq", "5")
        # 防网络挂起：mock RSS/自定义采集（tick 内 fetch_and_store 会真实 HTTP）
        monkeypatch.setattr(lifecycle.knowledge, "fetch_and_store",
                            lambda db=None, instances=None: {"feeds": 0, "added": 0, "errors": []})
        monkeypatch.setattr(lifecycle.knowledge, "collect_custom_sources",
                            lambda db=None, llm_fn=None: {"added": 0})
        calls = {"browse": 0}

        def fake_browse(platform_id, db=None, llm_fn=None):
            calls["browse"] += 1
            assert platform_id == "weibo"
            return {"platform_id": platform_id, "ok": True, "collected": 1,
                    "added": 1, "read_count": 0, "posted_count": 0}

        monkeypatch.setattr(lifecycle.behavior, "execute_browse", fake_browse)
        # 强制回到非逛状态（避免又被选中——逛需要 Cookie 才会被选）
        monkeypatch.setattr(lifecycle.behavior, "pick_random_state",
                            lambda db=None, now=None: {
                                "id": "daydream", "label": "🌙 发呆",
                                "duration_minutes": 10,
                                "until_iso": (datetime(2026, 9, 8, 14, 15)).isoformat(),
                            })
        now = datetime(2026, 9, 8, 14, 0)
        r = lifecycle.tick(now=now, llm_fn=lambda m: "x")
        assert calls["browse"] == 1
        assert r["browse"]["ok"] is True
        # 逛完成后回到 daydream
        assert agent_db.meta_get("xiaoman_current_state") == "daydream"
        # browse_done_seq 已消费，二次 tick 不再重复逛
        r2 = lifecycle.tick(now=now, llm_fn=lambda m: "x")
        assert calls["browse"] == 1
    finally:
        agent_db.init_db(None)


def test_tick_browse_no_cookie_fallback(tmp_path, monkeypatch):
    """方案 v1.10 §9.4：无 Cookie 进入逛状态 → 采集失败 → 回退 + 不阻塞状态机。"""
    agent_db.init_db(tmp_path / "agent.db")
    try:
        agent_db.meta_set("xiaoman_online", "1")
        agent_db.meta_set("xiaoman_current_state", "xhs_browse")
        agent_db.meta_set("xiaoman_state_until",
                          (datetime(2026, 9, 8, 14, 5)).strftime("%Y-%m-%d %H:%M:%S"))
        agent_db.meta_set("xiaoman_state_seq", "5")
        monkeypatch.setattr(lifecycle.knowledge, "fetch_and_store",
                            lambda db=None, instances=None: {"feeds": 0, "added": 0, "errors": []})
        monkeypatch.setattr(lifecycle.knowledge, "collect_custom_sources",
                            lambda db=None, llm_fn=None: {"added": 0})

        def fake_browse(platform_id, db=None, llm_fn=None):
            assert platform_id == "xhs"
            return {"platform_id": platform_id, "ok": False, "collected": 0,
                    "read_count": 0, "posted_count": 0, "error": "需要用户提供 Cookie"}

        monkeypatch.setattr(lifecycle.behavior, "execute_browse", fake_browse)
        monkeypatch.setattr(lifecycle.behavior, "pick_random_state",
                            lambda db=None, now=None: {
                                "id": "tea", "label": "☕ 喝奶茶",
                                "duration_minutes": 10,
                                "until_iso": (datetime(2026, 9, 8, 14, 15)).isoformat(),
                            })
        now = datetime(2026, 9, 8, 14, 0)
        r = lifecycle.tick(now=now, llm_fn=lambda m: "x")
        assert r["browse"]["ok"] is False
        # 回退到常驻状态（tea）
        assert agent_db.meta_get("xiaoman_current_state") == "tea"
    finally:
        agent_db.init_db(None)


def test_tick_zhihu_xueqiu_browse_dispatch(tmp_path, monkeypatch):
    """逛状态泛化（2026-09-09）：知乎/雪球逛状态同样 dispatch 到对应平台采集。"""
    agent_db.init_db(tmp_path / "agent.db")
    try:
        agent_db.meta_set("xiaoman_online", "1")
        monkeypatch.setattr(lifecycle.knowledge, "fetch_and_store",
                            lambda db=None, instances=None: {"feeds": 0, "added": 0, "errors": []})
        monkeypatch.setattr(lifecycle.knowledge, "collect_custom_sources",
                            lambda db=None, llm_fn=None: {"added": 0})
        seen = []

        def fake_browse(platform_id, db=None, llm_fn=None):
            seen.append(platform_id)
            return {"platform_id": platform_id, "ok": True, "collected": 1,
                    "added": 1, "read_count": 0, "posted_count": 0}

        monkeypatch.setattr(lifecycle.behavior, "execute_browse", fake_browse)
        monkeypatch.setattr(lifecycle.behavior, "pick_random_state",
                            lambda db=None, now=None: {
                                "id": "daydream", "label": "🌙 发呆",
                                "duration_minutes": 10,
                                "until_iso": (datetime(2026, 9, 8, 14, 15)).isoformat(),
                                "until_display": "14:15",
                            })
        now = datetime(2026, 9, 8, 14, 0)
        for state, expect in (("zhihu_browse", "zhihu"), ("xueqiu_browse", "xueqiu")):
            agent_db.meta_set("xiaoman_current_state", state)
            agent_db.meta_set("xiaoman_state_until",
                              (now + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"))
            agent_db.meta_set("xiaoman_state_seq", str(int(
                agent_db.meta_get("xiaoman_state_seq") or "0") + 1))
            agent_db.meta_set("xiaoman_browse_done_seq", "")  # 重置已逛标记
            r = lifecycle.tick(now=now, llm_fn=lambda m: "x")
            assert r["browse"]["ok"] is True, f"{state}: {r.get('browse')}"
            assert seen[-1] == expect
    finally:
        agent_db.init_db(None)
