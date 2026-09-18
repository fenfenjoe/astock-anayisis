"""节流目标验证：模拟 agent 常驻 1 小时，断言云库访问间隔 > 挂起阈值 300s。

背景（2026-09-17 成本优化核心目标）：只有云库访问间隔 >「算力空闲自动挂起」
阈值（300s），workspace 才能真正休眠、算力归零。本测试用 mock 云库模拟
agent 每 300s tick 一次、运行 1 小时，统计每次真实云库访问的时间戳，
断言最大连续空闲间隔 > 300s。

注意：本测试不连真实云库（_cd_* 全 mock），只验证节流逻辑产生的访问模式。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from agent import db as agent_db
from agent.core import lifecycle


@pytest.fixture()
def cloud_throttle(monkeypatch):
    """mock 云库层，记录每次访问时间戳（模拟云库）。"""
    monkeypatch.setattr(agent_db, "USE_CLOUD", True)
    access_times = []  # 每次云库往返的模拟时间戳

    class _R:
        def __getitem__(self, i):
            return None if i >= len(self._r) else self._r[i]
        def __init__(self, r): self._r = r

    def fake_select_one(table, *, columns="*", filters=None, order=None):
        access_times.append(agent_db.time.time())
        if table == "agent_metadata":
            key = None
            for c, op, v in (filters or []):
                if c == "key":
                    key = v
            if key == "xiaoman_online":
                return {"key": key, "value": "1"}
            if key in ("xiaoman_state_seq", "xiaoman_read_done_seq",
                       "xiaoman_browse_done_seq"):
                return {"key": key, "value": "1"}  # seq 已消费 → 不触发阅读/逛
            if key == "xiaoman_current_state":
                return {"key": key, "value": "daydream"}  # 常驻状态
            if key == "xiaoman_state_until":
                return {"key": key, "value": "2099-12-31 23:59:59"}  # 未过期
            if key in ("last_rss_fetch_at", "last_custom_fetch_at"):
                # 模拟刚拉取过（RSS 1h / 自定义 6h 间隔内）→ 不触发到期重拉写库
                return {"key": key, "value": "2026-09-17 08:00:00"}
            if key == "published_on":
                return {"key": key, "value": "2026-09-17"}  # 今日已发 → 发文门控不通过
            return {"key": key, "value": "v"} if key else None
        if table == "agent_activities":
            return None
        return None

    def fake_select(table, *, columns="*", filters=None, order=None,
                    limit=None, offset=None):
        access_times.append(agent_db.time.time())
        if table == "agent_metadata":
            key = None
            for c, op, v in (filters or []):
                if c == "key" and op == "in":
                    key = v  # "(k1,k2,...)"
            keys = key.strip("()").split(",") if key else []
            vals = {
                "xiaoman_current_state": "daydream",
                "xiaoman_state_until": "2099-12-31 23:59:59",
                "xiaoman_state_seq": "1",
                "xiaoman_read_done_seq": "1",
                "xiaoman_browse_done_seq": "1",
                "published_on": "2026-09-17",
                "last_rss_fetch_at": "2026-09-17 08:00:00",
                "last_custom_fetch_at": "2026-09-17 08:00:00",
            }
            return [{"key": k, "value": vals.get(k)} for k in keys]
        return []

    def fake_upsert(table, row, *, on_conflict=None):
        access_times.append(agent_db.time.time())
        return dict(row)

    monkeypatch.setattr(agent_db, "_cd_select_one", fake_select_one)
    monkeypatch.setattr(agent_db, "_cd_select", fake_select)
    monkeypatch.setattr(agent_db, "_cd_upsert", fake_upsert)
    # 固定 TTL，避免环境变量干扰
    monkeypatch.setattr(agent_db, "_META_TTL", 600)
    monkeypatch.setattr(agent_db, "_HEARTBEAT_INTERVAL", 600)
    agent_db._meta_cache.clear()
    yield access_times
    agent_db._meta_cache.clear()


def test_agent_idle_one_hour_access_interval_exceeds_suspend_threshold(cloud_throttle, monkeypatch):
    """核心目标：1 小时（12 tick × 300s）模拟，最大访问间隔 > 300s 挂起阈值。"""
    access_times = cloud_throttle
    base = 1_000_000.0
    now = [base]

    # mock time.time（模块级引用 agent_db.time）
    monkeypatch.setattr(agent_db, "time", time)
    monkeypatch.setattr(time, "time", lambda: now[0])
    # 复位 heartbeat 节流状态
    monkeypatch.setattr(lifecycle, "_last_heartbeat_ts", 0.0)
    # mock 高成本/网络路径，避免真实调用（RSS/自定义源/调度器）
    monkeypatch.setattr(lifecycle.knowledge, "fetch_and_store",
                        lambda db=None, instances=None: {"feeds": 0, "added": 0, "errors": []})
    monkeypatch.setattr(lifecycle.knowledge, "collect_custom_sources",
                        lambda db=None, llm_fn=None: {"added": 0})
    from agent.core import scheduler_agent as _sa
    monkeypatch.setattr(_sa, "tick", lambda now=None: {"started": [], "checked_at": "x"})

    from datetime import datetime, timedelta

    fake_now = datetime(2026, 9, 17, 8, 0, 0)
    for i in range(12):  # 12 个 tick = 1 小时
        lifecycle.tick(now=fake_now)
        fake_now += timedelta(seconds=300)
        now[0] += 300

    assert len(access_times) > 0, "应至少有一次真实云库访问（首次冷读）"
    # 计算最大连续空闲间隔
    gaps = [b - a for a, b in zip(access_times, access_times[1:])]
    max_gap = max(gaps)
    total_calls = len(access_times)
    print(f"\n1 小时内云库访问次数: {total_calls} 次（原方案 12 tick × 6 次 = 72 次）")
    print(f"最大连续空闲间隔: {max_gap:.0f}s（挂起阈值 300s）")
    assert max_gap > 300, f"最大访问间隔 {max_gap:.0f}s 未超过挂起阈值 300s，算力无法归零！"
    # 节流效率：调用次数应显著低于原始 72 次
    assert total_calls < 72, f"节流后仍 {total_calls} 次访问，节流失效"


def test_agent_active_state_change_still_writes(cloud_throttle, monkeypatch):
    """状态变化必须写云库（不被缓存吞掉）——写穿透保证。"""
    access_times = cloud_throttle
    monkeypatch.setattr(agent_db, "_META_TTL", 600)
    # 模拟状态切换：meta_set 必须触发云库写
    before = len(access_times)
    agent_db.meta_set("xiaoman_current_state", "reading")
    after = len(access_times)
    assert after == before + 1, "meta_set 写穿透失败，状态变化未落云库"
    # 且写后本进程读立即最新（写穿透缓存）
    assert agent_db.meta_get("xiaoman_current_state") == "reading"


def test_publish_gate_skips_writes_when_not_due(cloud_throttle, monkeypatch):
    """今日已发过文 → tick 不应触发"临时置 writing"的 4 次云库写。

    根因（2026-09-17 发现）：lifecycle.tick 每日发文块无条件先写
    current_state=writing + state_until（L251/252）+ 恢复（L266/268），
    即使 should_publish 门控不通过也写 → 每 tick 4 次云库写，阻止挂起。
    修复后：外层先 should_publish 门控，不该发文 → 0 次发文相关写。
    """
    access_times = cloud_throttle
    base = 1_000_000.0
    now = [base]
    monkeypatch.setattr(agent_db, "time", time)
    monkeypatch.setattr(time, "time", lambda: now[0])
    monkeypatch.setattr(lifecycle, "_last_heartbeat_ts", 0.0)
    monkeypatch.setattr(lifecycle.knowledge, "fetch_and_store",
                        lambda db=None, instances=None: {"feeds": 0, "added": 0, "errors": []})
    monkeypatch.setattr(lifecycle.knowledge, "collect_custom_sources",
                        lambda db=None, llm_fn=None: {"added": 0})
    from agent.core import scheduler_agent as _sa
    monkeypatch.setattr(_sa, "tick", lambda now=None: {"started": [], "checked_at": "x"})

    from datetime import datetime, timedelta

    # 关键：fake 返回 published_on=今天 → should_publish 门控不通过
    fake_now = datetime(2026, 9, 17, 8, 0, 0)
    # 预热缓存（首个 tick 冷读）
    lifecycle.tick(now=fake_now)
    access_times.clear()  # 只统计第二个 tick
    fake_now += timedelta(seconds=300)
    now[0] += 300

    before = len(access_times)
    lifecycle.tick(now=fake_now)
    after = len(access_times)
    # 第二个 tick（缓存全命中 + 发文门控不通过）→ 不应有发文相关写
    # （允许 heartbeat 写：600s 节流内不发 → 应为 0 次写）
    print(f"\n第二个 tick 云库访问次数: {after - before}")
    assert after == before, f"发文门控失效：tick 仍触发 {after - before} 次云库写"
