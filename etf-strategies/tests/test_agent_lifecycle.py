"""agent/core/lifecycle.py — 常驻主循环 / 健康探针 / RSS 节流。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime

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
