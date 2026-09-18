"""agent/db.py — 云库访问节流（进程内 TTL 缓存）测试。

背景（2026-09-17 成本优化）：agent 常驻每 300s tick 一次，每次 5-8 次云库往返，
导致 AIDAP workspace 永远无法进入「算力空闲自动挂起」（阈值 300s）→ 算力 24/7 计费。
节流方案：agent/db.py 的 meta_get/meta_get_many 加进程内 TTL 缓存（默认 600s，
> 挂起阈值 300s），meta_set 写穿透更新缓存 → 平时云库访问降到每 10 分钟 1 次冷读。

原则：数据 100% 在云（缓存仅进程内存，重启即清空，无本地持久化）。
仅影响 agent 进程（dashboard/db.py 独立模块，保持实时读）。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from agent import db as agent_db


@pytest.fixture()
def cloud_throttle(monkeypatch):
    """强制 agent.db 走云后端，并 mock cloud_db 层记录调用次数。"""
    monkeypatch.setattr(agent_db, "USE_CLOUD", True)
    calls = {"select_one": 0, "upsert": 0, "select": 0}

    class _FakeRows:
        def __init__(self, rows):
            self._rows = rows
        def __getitem__(self, i):
            return self._rows[i]
        def __len__(self):
            return len(self._rows)

    def fake_select_one(table, *, columns="*", filters=None, order=None):
        calls["select_one"] += 1
        if table == "agent_metadata":
            key = None
            for c, op, v in (filters or []):
                if c == "key":
                    key = v
            return {"key": key, "value": f"v-{key}"} if key else None
        if table == "agent_activities":
            return None
        return None

    def fake_select(table, *, columns="*", filters=None, order=None,
                    limit=None, offset=None):
        calls["select"] += 1
        if table == "agent_metadata":
            key = None
            for c, op, v in (filters or []):
                if c == "key" and op == "in":
                    key = v  # 形如 "(a,b)"
            keys = key.strip("()").split(",") if key else []
            return [{"key": k, "value": f"v-{k}"} for k in keys]
        return []

    def fake_upsert(table, row, *, on_conflict=None):
        calls["upsert"] += 1
        return dict(row)

    monkeypatch.setattr(agent_db, "_cd_select_one", fake_select_one)
    monkeypatch.setattr(agent_db, "_cd_select", fake_select)
    monkeypatch.setattr(agent_db, "_cd_upsert", fake_upsert)

    # 复位缓存（防测试间污染）
    agent_db._meta_cache.clear()
    yield calls
    agent_db._meta_cache.clear()


# ═══════════════════════════════════════════
# meta_get 缓存命中
# ═══════════════════════════════════════════

def test_meta_get_caches_after_first_read(cloud_throttle):
    calls = cloud_throttle
    v1 = agent_db.meta_get("xiaoman_online")
    assert v1 == "v-xiaoman_online"
    assert calls["select_one"] == 1
    # 第二次读命中缓存，不再云库往返
    v2 = agent_db.meta_get("xiaoman_online")
    assert v2 == "v-xiaoman_online"
    assert calls["select_one"] == 1


def test_meta_get_many_caches_all(cloud_throttle):
    calls = cloud_throttle
    r = agent_db.meta_get_many(["xiaoman_current_state", "xiaoman_state_until"])
    assert r["xiaoman_current_state"] == "v-xiaoman_current_state"
    assert r["xiaoman_state_until"] == "v-xiaoman_state_until"
    assert calls["select"] == 1
    # 命中缓存
    r2 = agent_db.meta_get_many(["xiaoman_current_state"])
    assert calls["select"] == 1


def test_meta_set_updates_cache(cloud_throttle):
    calls = cloud_throttle
    agent_db.meta_get("xiaoman_current_state")  # 冷读填缓存
    agent_db.meta_set("xiaoman_current_state", "reading")
    # 写后读 → 命中缓存（写穿透），不再云库读
    assert agent_db.meta_get("xiaoman_current_state") == "reading"
    assert calls["select_one"] == 1  # 仍是首次那次冷读
    assert calls["upsert"] == 1


def test_meta_set_does_not_break_other_keys(cloud_throttle):
    calls = cloud_throttle
    agent_db.meta_set("xiaoman_online", "1")
    assert calls["upsert"] == 1
    # 不同 key 冷读触发云库
    assert agent_db.meta_get("published_on") == "v-published_on"
    assert calls["select_one"] == 1


# ═══════════════════════════════════════════
# 缓存过期后重读
# ═══════════════════════════════════════════

def test_meta_get_reloads_after_ttl(cloud_throttle, monkeypatch):
    calls = cloud_throttle
    monkeypatch.setattr(agent_db, "_META_TTL", 0)  # 立刻过期
    agent_db.meta_get("xiaoman_online")
    agent_db.meta_get("xiaoman_online")
    assert calls["select_one"] == 2  # 每次都是冷读


# ═══════════════════════════════════════════
# heartbeat 节流
# ═══════════════════════════════════════════

def test_heartbeat_throttled(cloud_throttle, monkeypatch):
    calls = cloud_throttle
    from agent.core import lifecycle
    now = time.time()
    monkeypatch.setattr(agent_db, "_HEARTBEAT_INTERVAL", 600)
    monkeypatch.setattr(agent_db, "time", time)
    monkeypatch.setattr(time, "time", lambda: now)
    lifecycle.heartbeat()
    assert calls["upsert"] == 1
    # 600s 内第二次 → 不写
    monkeypatch.setattr(time, "time", lambda: now + 300)
    lifecycle.heartbeat()
    assert calls["upsert"] == 1
    # 超过 600s → 再写
    monkeypatch.setattr(time, "time", lambda: now + 601)
    lifecycle.heartbeat()
    assert calls["upsert"] == 2


# ═══════════════════════════════════════════
# activity_open 缓存
# ═══════════════════════════════════════════

def test_activity_open_cached(cloud_throttle):
    calls = cloud_throttle
    agent_db.activity_open()
    agent_db.activity_open()
    assert calls["select_one"] == 1  # 两次读只 1 次云库往返
