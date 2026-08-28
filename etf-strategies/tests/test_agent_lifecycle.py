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
