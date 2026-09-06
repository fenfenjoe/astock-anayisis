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


def test_reading_task_text_within_cmdline_limit(tmp_db, tmp_path, monkeypatch):
    """回归：未读清单过长曾把任务文本撑到 >32K，触发 Windows [WinError 206]。

    上下文外置为资料包文件后，任务文本只留骨架（与未读数量无关的恒定短文本），
    100 条长摘要文章全部写入 unread.md 供 LLM 用文件工具读取。
    """
    monkeypatch.setattr(behavior, "_READING_CTX_DIR", tmp_path / "reading")
    for i in range(100):
        agent_db.knowledge_upsert(
            "rss", f"文章标题比较长一些{i}", f"https://example.com/a/{i}",
            summary="很长的摘要" * 40, published_at=f"2026-09-06 08:{i:02d}:00")
    captured = {}

    def _fake_llm(task):
        captured["len"] = len(task)
        captured["task"] = task
        return '{}'

    res = behavior.execute_reading(db=agent_db, llm_fn=_fake_llm)
    # 骨架任务文本恒定短小，且指向资料包文件
    assert captured["len"] < 5000
    assert "unread.md" in captured["task"]
    # 资料包：100 条全量写入，无预算截断
    ctx_dirs = [d for d in (tmp_path / "reading").iterdir() if d.is_dir()]
    assert len(ctx_dirs) == 1
    body = (ctx_dirs[0] / "unread.md").read_text(encoding="utf-8")
    assert "文章标题比较长一些0" in body and "文章标题比较长一些99" in body
    assert (ctx_dirs[0] / "memories.md").read_text(encoding="utf-8")
    assert res["error"] is None  # 正常解析，不产生异常备注


def test_reading_ctx_fallback_to_inline(tmp_db, tmp_path, monkeypatch):
    """资料包写失败（目录不可创建）→ 降级内联注入，任务文本仍受 32K 约束。"""
    blocker = tmp_path / "blocker"
    blocker.write_text("", encoding="utf-8")  # 占位文件，其下无法建目录
    monkeypatch.setattr(behavior, "_READING_CTX_DIR", blocker / "sub")
    for i in range(100):
        agent_db.knowledge_upsert(
            "rss", f"文章标题比较长一些{i}", f"https://example.com/a/{i}",
            summary="很长的摘要" * 40, published_at=f"2026-09-06 08:{i:02d}:00")
    captured = {}

    def _fake_llm(task):
        captured["task"] = task
        return '{}'

    res = behavior.execute_reading(db=agent_db, llm_fn=_fake_llm)
    assert len(captured["task"]) < 32000
    assert "1. [rss]" in captured["task"]  # 内联清单存在（预算内保新弃旧）
    assert res["error"] is None


def test_manual_slack_and_reading_pickers(tmp_db):
    r = behavior.pick_manual_reading(now=datetime(2026, 9, 6, 10, 0, 0))
    assert r["id"] == "reading" and r["label"] == "📖 阅读"
    s = behavior.pick_manual_slack(now=datetime(2026, 9, 6, 10, 0, 0))
    assert s["id"] not in behavior._PRODUCTIVE_IDS and s["id"] != "sleep"
