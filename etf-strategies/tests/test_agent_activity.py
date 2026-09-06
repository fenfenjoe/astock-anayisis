"""活动台账（动作事件模型）：阅读/写文章是"事件"，随真实执行开/关；
常驻状态（摸鱼/发呆/打游戏…）是"状态段"，切换开/关。

覆盖：behavior.switch_state + db.activity_* 助手 + execute_reading 事件化。
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from agent import db as agent_db
from agent.core import behavior


@pytest.fixture()
def tmp_db(tmp_path):
    agent_db.init_db(tmp_path / "agent.db")
    yield agent_db
    agent_db.init_db(None)


def _target(sid, label, minutes=30):
    until = (datetime.now() + timedelta(minutes=minutes)).isoformat()
    return {"id": sid, "label": label, "until_iso": until}


def test_event_kind_switch_skips_ambient_segment(tmp_db):
    """阅读/写文章是动作事件：切换只改 meta/seq，不占常驻状态段。"""
    now = datetime(2026, 9, 6, 10, 0, 0)
    sw = behavior.switch_state(_target("reading", "📖 阅读"), now=now, source="manual")
    assert sw["changed"] is True and sw["event"] is True
    assert tmp_db.meta_get("xiaoman_current_state") == "reading"
    assert tmp_db.meta_get("xiaoman_state_seq") == "1"
    assert tmp_db.activity_open() is None  # 没有常驻段，等真实执行器开事件


def test_ambient_switch_closes_previous_and_opens_new(tmp_db):
    now = datetime(2026, 9, 6, 10, 0, 0)
    sw1 = behavior.switch_state(_target("tea", "☕ 喝奶茶"), now=now, source="manual")
    assert sw1["event"] is False and sw1["changed"] is True
    open1 = tmp_db.activity_open()
    assert open1["kind"] == "tea" and open1["ended_at"] is None

    now2 = now + timedelta(minutes=30)
    sw2 = behavior.switch_state(_target("gaming", "🎮 打游戏"), now=now2, source="auto")
    assert sw2["changed"] is True
    rows = tmp_db.activity_list(limit=10)
    closed = next(r for r in rows if r["kind"] == "tea")
    assert closed["ended_at"] == now2.strftime("%Y-%m-%d %H:%M:%S")
    assert closed["tokens"] is None  # 真实 usage 未接入 → 未计量
    open2 = tmp_db.activity_open()
    assert open2["kind"] == "gaming" and open2["source"] == "auto"


def test_same_ambient_no_reopen(tmp_db):
    now = datetime(2026, 9, 6, 10, 0, 0)
    behavior.switch_state(_target("tea", "☕ 喝奶茶"), now=now)
    sw2 = behavior.switch_state(
        _target("tea", "☕ 喝奶茶", minutes=60), now=now + timedelta(minutes=1))
    assert sw2["changed"] is False
    rows = tmp_db.activity_list(limit=10)
    assert len([r for r in rows if r["kind"] == "tea"]) == 1


def test_reading_event_open_close(tmp_db, monkeypatch):
    """真实执行阅读：开一条"阅读"事件并关闭，备注读了 N 篇。"""
    agent_db.knowledge_upsert("雪球", "一篇财经文", "https://example.com/r/1",
                              summary="摘要", published_at="2026-09-06 08:00:00")
    out = '{"read_count": 1, "articles": [{"title": "一篇财经文", "url": "https://example.com/r/1", "viewpoint": "观点", "emotion": "curious", "memory": "感受"}], "posts": []}'

    def _fake_llm(task):
        return out

    res = behavior.execute_reading(db=agent_db, llm_fn=_fake_llm)
    assert res["read_count"] == 1
    rows = agent_db.activity_list(limit=10)
    reading = next(r for r in rows if r["kind"] == "reading")
    assert reading["ended_at"] is not None          # 读完即关（绝不是"进行中"）
    assert "读了 1 篇" in (reading["note"] or "")


def test_manual_slack_and_reading_pickers(tmp_db):
    r = behavior.pick_manual_reading(now=datetime(2026, 9, 6, 10, 0, 0))
    assert r["id"] == "reading" and r["label"] == "📖 阅读"
    s = behavior.pick_manual_slack(now=datetime(2026, 9, 6, 10, 0, 0))
    assert s["id"] not in behavior._PRODUCTIVE_IDS and s["id"] != "sleep"
