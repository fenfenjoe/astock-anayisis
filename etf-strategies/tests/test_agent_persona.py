"""agent/core/persona.py — 人设卡加载 / system prompt 注入 / 合规与观点自洽校验。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from agent import db as agent_db
from agent.core import persona


def test_load_persona_xiaoman():
    p = persona.load_persona("xiaoman")
    assert p["id"] == "xiaoman"
    assert "小满" in p["name"]
    assert "小满" in p["content"]


def test_load_persona_missing_raises():
    with pytest.raises(FileNotFoundError):
        persona.load_persona("no_such_persona")


def test_build_system_prompt_contains_boundaries():
    prompt = persona.build_system_prompt("xiaoman")
    assert "不构成投资建议" in prompt
    assert "事实" in prompt and "观点" in prompt
    assert "数据" in prompt  # 数据纪律（来源标注）


def test_append_disclaimer():
    out = persona.append_disclaimer("今天聊聊白酒。")
    assert "不构成投资建议" in out


def test_append_disclaimer_idempotent():
    text = "聊聊宏观。\n\n以上仅为小满的个人学习笔记与观点，不构成投资建议。"
    assert persona.append_disclaimer(text).count("不构成投资建议") == 1


def test_sanitize_flags_forbidden_verbs():
    bad = persona.sanitize_output("我觉得可以买入腾讯")
    assert bad["ok"] is False
    assert "买入" in bad["violations"]


def test_sanitize_pass_clean_text():
    ok = persona.sanitize_output("我觉得腾讯值得研究，护城河在社交。")
    assert ok["ok"] is True


def test_check_consistency_returns_history(tmp_path):
    agent_db.init_db(tmp_path / "agent.db")
    try:
        agent_db.opinion_add("白酒", "茅台护城河在品牌")
        history = persona.check_consistency("白酒", "高端酒消费人群在变")
        assert len(history) == 1
        assert history[0]["opinion"] == "茅台护城河在品牌"
        assert persona.check_consistency("新话题", "x") == []
    finally:
        agent_db.init_db(None)


def test_check_conflict_detection():
    hist = [{"topic": "白酒", "opinion": "我看好白酒长期"}]
    assert persona.check_conflict("白酒", "我不看好白酒长期", hist) is True
    assert persona.check_conflict(
        "白酒", "白酒估值需要消化，但长期逻辑还在", hist) is False
