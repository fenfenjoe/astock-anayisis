"""agent/core/knowledge.py — RSS 拉取/解析/去重入库/素材检索。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from agent import config, db as agent_db
from agent.core import knowledge

FIXTURE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>财联社电报</title>
<item><title>【快讯】央行开展5000亿MLF操作</title>
<link>https://www.cls.cn/detail/123456</link>
<pubDate>Wed, 27 Aug 2026 10:00:00 GMT</pubDate>
<description>央行今日开展5000亿元MLF操作。</description></item>
<item><title>【快讯】北向资金净流入50亿</title>
<link>https://www.cls.cn/detail/123457</link>
<pubDate>Wed, 27 Aug 2026 10:05:00 GMT</pubDate>
<description>北向资金今日净流入约50亿元。</description></item>
</channel></rss>"""


def test_parse_rss_basic():
    items = knowledge.parse_rss(FIXTURE_RSS)
    assert len(items) == 2
    assert items[0]["title"].startswith("【快讯】")
    assert items[0]["url"] == "https://www.cls.cn/detail/123456"
    assert "MLF" in items[0]["summary"]
    assert items[0]["published_at"].startswith("2026-08-27")


def test_parse_rss_empty_and_broken():
    assert knowledge.parse_rss("<rss></rss>") == []
    assert knowledge.parse_rss("") == []
    assert knowledge.parse_rss("not xml at all") == []


def test_parse_rss_missing_fields_tolerant():
    xml = """<rss version="2.0"><channel>
    <item><title>只有标题</title></item>
    </channel></rss>"""
    items = knowledge.parse_rss(xml)
    assert len(items) == 1
    assert items[0]["url"] == ""
    assert items[0]["summary"] == ""


def test_feed_url():
    url = knowledge.feed_url(config.RSS_FEEDS[0], "https://rsshub.app")
    assert url == "https://rsshub.app/cls/telegraph"


def test_fetch_feed_with_mock(monkeypatch):
    class FakeResp:
        text = FIXTURE_RSS

        def raise_for_status(self):
            return None

    def fake_get(url, timeout=10):
        assert "rsshub" in url
        return FakeResp()

    monkeypatch.setattr(knowledge.requests, "get", fake_get)
    items = knowledge.fetch_feed(config.RSS_FEEDS[0], "https://rsshub.app")
    assert len(items) == 2


def test_fetch_feed_network_error_tolerant(monkeypatch):
    def boom(url, timeout=10):
        raise knowledge.requests.RequestException("boom")

    monkeypatch.setattr(knowledge.requests, "get", boom)
    assert knowledge.fetch_feed(config.RSS_FEEDS[0], "https://rsshub.app") == []


def test_sync_feed_stores_and_dedups(tmp_path):
    agent_db.init_db(tmp_path / "agent.db")
    try:
        items = knowledge.parse_rss(FIXTURE_RSS)
        r1 = knowledge.sync_feed("cls", items)
        assert r1["added"] == 2
        r2 = knowledge.sync_feed("cls", items)  # 重复同步 → 全去重
        assert r2["added"] == 0
        assert len(agent_db.knowledge_unconsumed()) == 2
    finally:
        agent_db.init_db(None)


def test_pick_material_respects_consumed(tmp_path):
    agent_db.init_db(tmp_path / "agent.db")
    try:
        agent_db.knowledge_upsert("cls", "旧", "http://u/1", "s1", None, "2026-08-26 09:00")
        agent_db.knowledge_upsert("cls", "新", "http://u/2", "s2", None, "2026-08-27 10:00")
        rows = agent_db.knowledge_unconsumed(limit=10)
        assert len(rows) == 2
        agent_db.knowledge_mark_consumed(rows[0]["id"])
        rest = agent_db.knowledge_unconsumed(limit=10)
        assert len(rest) == 1
        assert rest[0]["id"] != rows[0]["id"]
    finally:
        agent_db.init_db(None)


GATHER_JSON = (
    '[{"title": "央行MLF操作点评", "url": "https://wsc.cn/a/1", '
    '"summary": "流动性预期稳中偏松", "source": "华尔街见闻"}, '
    '{"title": "美联储纪要解读", "url": "https://wsc.cn/a/2", '
    '"summary": "加息路径存分歧", "source": "华尔街见闻"}]'
)


def test_parse_gather_output_plain_json():
    items = knowledge.parse_gather_output(GATHER_JSON)
    assert len(items) == 2
    assert items[0]["title"] == "央行MLF操作点评"
    assert items[0]["url"] == "https://wsc.cn/a/1"


def test_parse_gather_output_with_fence():
    text = "好的，以下是找到的文章：\n```json\n" + GATHER_JSON + "\n```\n"
    items = knowledge.parse_gather_output(text)
    assert len(items) == 2


def test_parse_gather_output_broken():
    assert knowledge.parse_gather_output("不是 JSON") == []
    assert knowledge.parse_gather_output("") == []
    # 缺 url 的条目被丢弃
    bad = '[{"title": "x", "url": ""}, {"title": "y", "url": "http://ok"}]'
    items = knowledge.parse_gather_output(bad)
    assert len(items) == 1
    assert items[0]["url"] == "http://ok"


def test_collect_custom_sources_stores(tmp_path):
    agent_db.init_db(tmp_path / "agent.db")
    try:
        agent_db.source_add("华尔街见闻", "https://wallstreetcn.com/live",
                            kind="website", note="宏观")
        res = knowledge.collect_custom_sources(
            llm_fn=lambda task: GATHER_JSON)
        assert res["sites"] == 1
        assert res["added"] == 2
        rows = agent_db.knowledge_unconsumed()
        assert len(rows) == 2
        assert rows[0]["source"] == "华尔街见闻"
    finally:
        agent_db.init_db(None)


def test_collect_custom_sources_no_sites(tmp_path):
    agent_db.init_db(tmp_path / "agent.db")
    try:
        res = knowledge.collect_custom_sources(llm_fn=lambda task: "[]")
        assert res == {"sites": 0, "added": 0, "errors": []}
    finally:
        agent_db.init_db(None)
