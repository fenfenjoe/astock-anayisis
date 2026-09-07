"""agent/core/behavior.py — 发文调度/素材选择/草稿管线（纯函数 + 依赖注入可测）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from agent import db as agent_db
from agent.core import behavior

FAKE_LLM_TEXT = (
    "标题：今天学到的三件事\n\n"
    "1. 央行开展5000亿MLF操作，利率不变。\n"
    "2. 北向资金净流入。\n"
    "3. 我觉得流动性预期稳中偏松，值得持续跟踪。\n"
)


def test_should_publish_before_time_returns_false():
    res = behavior.should_publish("2026-08-27", published_on=None,
                                  hour=9, minute=0)
    assert res["publish"] is False


def test_should_publish_after_time_true():
    res = behavior.should_publish("2026-08-27", published_on=None,
                                  hour=17, minute=31)
    assert res["publish"] is True


def test_should_publish_already_done_false():
    res = behavior.should_publish("2026-08-27", published_on="2026-08-27",
                                  hour=18, minute=0)
    assert res["publish"] is False


def test_pick_material_insufficient():
    items = [{"id": 1}, {"id": 2}]
    res = behavior.pick_material(items, min_items=3)
    assert res["ready"] is False


def test_pick_material_enough():
    items = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]
    res = behavior.pick_material(items, min_items=3)
    assert res["ready"] is True
    assert len(res["items"]) == 4


def test_validate_article_ok():
    text = "我觉得今天的市场值得关注。" * 5
    res = behavior.validate_article(text)
    assert res["ok"] is True


def test_validate_article_rejects_forbidden_verb():
    res = behavior.validate_article("我觉得应该买入白酒")
    assert res["ok"] is False


def test_validate_article_rejects_too_short():
    res = behavior.validate_article("短")
    assert res["ok"] is False


def test_compose_article_parses_title():
    def fake_llm(messages):
        return FAKE_LLM_TEXT

    art = behavior.compose_article(materials=[], llm_fn=fake_llm)
    assert art["title"] == "今天学到的三件事"
    assert "央行" in art["content"]


def test_compose_article_fallback_title():
    def fake_llm(messages):
        return "没有标题，直接正文内容。" * 3

    art = behavior.compose_article(materials=[], llm_fn=fake_llm)
    assert art["title"]


def test_run_publish_pipeline_full(tmp_path):
    agent_db.init_db(tmp_path / "agent.db")
    try:
        for i in range(3):
            agent_db.knowledge_upsert("cls", f"素材{i}", f"http://u/{i}",
                                      f"摘要{i}", None, "2026-08-27 10:00")
        res = behavior.run_publish_pipeline(
            today="2026-08-27", now=(17, 31), llm_fn=lambda m: FAKE_LLM_TEXT)
        assert res["published"] is True
        assert agent_db.meta_get("published_on") == "2026-08-27"
        # 当日已发 → 不重复
        res2 = behavior.run_publish_pipeline(
            today="2026-08-27", now=(18, 0), llm_fn=lambda m: FAKE_LLM_TEXT)
        assert res2["published"] is False
        # 素材已消费
        assert agent_db.knowledge_unconsumed() == []
    finally:
        agent_db.init_db(None)


def test_run_publish_pipeline_material_insufficient(tmp_path):
    agent_db.init_db(tmp_path / "agent.db")
    try:
        agent_db.knowledge_upsert("cls", "只有一条", "http://u/1",
                                  "摘要", None, "2026-08-27 10:00")
        res = behavior.run_publish_pipeline(
            today="2026-08-27", now=(17, 31), llm_fn=lambda m: FAKE_LLM_TEXT)
        assert res["published"] is False
        assert res["reason"] == "material_insufficient"
    finally:
        agent_db.init_db(None)


# BUG-023 (2026-09-07) 修复: 3 个 test_run_post_pipeline_* 引用已删除函数
# `run_post_pipeline`（5c6fc61 重构移除，发动态已并入 execute_reading 的 kind="post" 路径）。
# 删除过时测试；新路径由 test_agent_activity.py 的 execute_reading 测试覆盖。
