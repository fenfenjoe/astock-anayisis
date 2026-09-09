"""agent Phase 3.7 — 认识小满页/社交平台（方案 v1.10 §9.4）测试。

覆盖：
- db：platform_cookie / reachability 存取（本地 + 云 mock）
- db：title_similar 标题相似度去重（difflib 0.85）
- behavior：逛状态权重（无 Cookie → 权重 0；有 Cookie → 加成）+ 逛冷却（独立于 reading）
- reachability：RSSHub / Cookie 探测（mock requests）
- playwright_collector：入库去重（url 精确 + 标题相似）、失败回写 reachability
- behavior.execute_browse：采集 → 复用阅读管道 → 动态直接发（mock collector + llm）

无网络：所有 HTTP 用 monkeypatch mock；db 用 tmp_path 本地。
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from agent import config, db as agent_db
from agent.core import behavior, playwright_collector, reachability


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    """每个测试独立临时 agent.db（避免污染真实数据）。"""
    agent_db.init_db(tmp_path / "agent.db")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "agent.db")
    yield
    agent_db.init_db(None)


# ═══════════════════════════════════════════
# Phase 3.8：聊天引入经验（仅财经话题）
# ═══════════════════════════════════════════


class TestChatExperienceDirective:
    def test_chat_task_has_experience_directive(self, tmp_path, monkeypatch):
        """聊天 directive 含"经验引用（仅财经话题）"规则（方案 v1.10 §7.4）。"""
        from agent.channels import web

        task, _ = web.chat_task(1, "聊聊今天大盘", db=agent_db)
        assert "经验引用" in task
        assert "财经" in task
        assert "闲聊" in task
        assert "不要" in task or "别" in task  # 强调非财经不引用


# ═══════════════════════════════════════════
# db：平台 Cookie / 可访问性
# ═══════════════════════════════════════════


class TestPlatformCookie:
    def test_get_none_when_missing(self):
        assert agent_db.platform_cookie_get("weibo") is None

    def test_set_and_get(self):
        agent_db.platform_cookie_set("weibo", "SUB=abc; XSRF=xyz")
        assert agent_db.platform_cookie_get("weibo") == "SUB=abc; XSRF=xyz"

    def test_update_overwrites(self):
        agent_db.platform_cookie_set("weibo", "old")
        agent_db.platform_cookie_set("weibo", "new")
        assert agent_db.platform_cookie_get("weibo") == "new"


class TestReachability:
    def test_get_none_when_missing(self):
        assert agent_db.reachability_get("xhs") is None

    def test_set_and_get(self):
        agent_db.reachability_set("weibo", True, "Cookie 探测通过")
        r = agent_db.reachability_get("weibo")
        assert r["reachable"] is True
        assert r["reason"] == "Cookie 探测通过"

    def test_update(self):
        agent_db.reachability_set("weibo", False, "无 Cookie")
        agent_db.reachability_set("weibo", True, "采集成功")
        assert agent_db.reachability_get("weibo")["reachable"] is True

    def test_all(self):
        agent_db.reachability_set("weibo", True)
        agent_db.reachability_set("xhs", False, "Cookie 失效")
        all_r = agent_db.reachability_all()
        assert all_r["weibo"]["reachable"] is True
        assert all_r["xhs"]["reachable"] is False
        assert all_r["xhs"]["reason"] == "Cookie 失效"


# ═══════════════════════════════════════════
# db：标题相似度去重（difflib 0.85）
# ═══════════════════════════════════════════


class TestTitleSimilar:
    def test_no_hits_when_empty(self):
        assert agent_db.title_similar("随便一个标题") == []

    def test_identical_title_hit(self):
        agent_db.knowledge_upsert("weibo", "A股大涨", "https://a/1", "摘要")
        hits = agent_db.title_similar("A股大涨")
        assert len(hits) == 1
        assert hits[0][1] == "A股大涨"

    def test_near_duplicate_title_hit(self):
        agent_db.knowledge_upsert("weibo", "今日A股三大指数集体收涨", "https://a/1")
        # 高度相似（同一话题相似表述）
        hits = agent_db.title_similar("A股三大指数集体收涨！")
        assert len(hits) == 1

    def test_unrelated_title_no_hit(self):
        agent_db.knowledge_upsert("weibo", "半导体板块异动分析", "https://a/1")
        assert agent_db.title_similar("今天天气不错") == []

    def test_threshold_respected(self):
        agent_db.knowledge_upsert("weibo", "今日A股三大指数集体收涨", "https://a/1")
        # 更高阈值下低相似不命中
        assert agent_db.title_similar("A股收涨", threshold=0.99) == []


# ═══════════════════════════════════════════
# behavior：逛状态权重 + 冷却
# ═══════════════════════════════════════════


class TestBrowseStateWeights:
    def _pick_with_cookie(self, has_cookie):
        if has_cookie:
            agent_db.platform_cookie_set("weibo", "SUB=abc")
            agent_db.platform_cookie_set("xhs", "a=1")
        # 固定时间避免 sleep 权重影响；去掉历史，反复选看权重是否可到 0
        pool = behavior.load_behaviors()
        weibo = next(b for b in pool["behaviors"] if b["id"] == "weibo_browse")
        assert weibo["weight"] > 0  # 权重与摸鱼态相同（8）

    def test_browse_weight_present(self):
        self._pick_with_cookie(has_cookie=True)

    def test_pick_browse_state(self):
        """有 Cookie + 冷却外 → pick_random_state 可能选中逛状态（权重>0 且可达）。"""
        agent_db.platform_cookie_set("weibo", "SUB=abc")
        agent_db.platform_cookie_set("xhs", "a=1")
        # 手动把 reading 权重清零上下文不影响：直接检查权重函数不抛错
        dec = behavior.pick_random_state(now=datetime(2026, 9, 8, 14, 0))
        assert dec["id"]  # 至少能选出一个状态

    def test_pick_manual_slack_excludes_browse(self):
        """用户手动"摸鱼"不含逛社交（逛状态由状态机自动触发采集）。"""
        dec = behavior.pick_manual_slack(now=datetime(2026, 9, 8, 14, 0))
        assert dec["id"] not in ("weibo_browse", "xhs_browse")

    def test_browse_event_kind(self):
        """逛状态是动作事件型（不占常驻状态段）。"""
        assert "weibo_browse" in behavior._EVENT_KINDS
        assert "xhs_browse" in behavior._EVENT_KINDS

    def test_browse_not_productive(self):
        """逛状态是纯摸鱼态（不在 _PRODUCTIVE_IDS）。"""
        assert "weibo_browse" not in behavior._PRODUCTIVE_IDS
        assert "xhs_browse" not in behavior._PRODUCTIVE_IDS


class TestBrowseCooldown:
    def test_cooldown_independent_from_reading(self):
        """逛冷却与 reading 冷却独立：刚逛完仍可进 reading。"""
        # 刚逛完（last_browse_at 最近）→ 逛权重应被冷却压 0
        agent_db.platform_cookie_set("weibo", "SUB=abc")
        agent_db.meta_set(
            "xiaoman_last_browse_at",
            (datetime.now() - timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S"),
        )
        # 冷却内不应选中 weibo_browse（权重被压 0）
        # 直接验证权重计算：模拟 pick 多次无 weibo_browse
        states = [
            behavior.pick_random_state(now=datetime(2026, 9, 8, 14, 0))["id"]
            for _ in range(50)
        ]
        assert "weibo_browse" not in states

    def test_no_cookie_zero_weight(self):
        """无 Cookie → 逛状态权重为 0（pick 不会选中）。"""
        states = [
            behavior.pick_random_state(now=datetime(2026, 9, 8, 14, 0))["id"]
            for _ in range(100)
        ]
        assert "weibo_browse" not in states
        assert "xhs_browse" not in states


# ═══════════════════════════════════════════
# reachability：探测逻辑（mock 网络）
# ═══════════════════════════════════════════


class FakeResp:
    def __init__(self, status=200, headers=None):
        self.status_code = status
        self.headers = headers or {"Content-Type": "application/json"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class TestReachabilityProbe:
    def test_x_fixed_unreachable(self):
        x = next(p for p in config.SOCIAL_PLATFORMS if p["id"] == "x")
        ok, reason = reachability.probe_platform(x)
        assert ok is False
        assert "未实施" in reason

    def test_cookie_missing(self):
        weibo = next(p for p in config.SOCIAL_PLATFORMS if p["id"] == "weibo")
        ok, reason = reachability.probe_platform(weibo)
        assert ok is False
        assert "Cookie" in reason
        # 提示用户需要哪个 key（配置里 cookie_keys 的 SUB）
        assert "SUB" in reason
        assert "key" in reason

    def test_cookie_probe_ok(self, monkeypatch):
        agent_db.platform_cookie_set("weibo", "SUB=abc")
        weibo = next(p for p in config.SOCIAL_PLATFORMS if p["id"] == "weibo")

        class FakeGet:
            def __init__(self, *a, **kw):
                pass

            def __call__(self, *a, **kw):
                return FakeResp(200)

        monkeypatch.setattr("requests.get", FakeGet())
        ok, _ = reachability.probe_platform(weibo)
        assert ok is True

    def test_cookie_probe_403(self, monkeypatch):
        agent_db.platform_cookie_set("weibo", "SUB=bad")
        weibo = next(p for p in config.SOCIAL_PLATFORMS if p["id"] == "weibo")

        class FakeGet:
            def __call__(self, *a, **kw):
                return FakeResp(403)

        monkeypatch.setattr("requests.get", FakeGet())
        ok, _ = reachability.probe_platform(weibo)
        assert ok is False

    def test_rss_source_reachable(self, monkeypatch):
        """RSS 源（财联社/华尔街见闻）：任一 RSSHub 实例拉到条目 → 可达。"""
        monkeypatch.setattr(
            reachability.knowledge, "fetch_feed",
            lambda feed, instance=None, timeout=None: [{"title": "条目"}],
        )
        for pid in ("cls", "wallstreetcn"):
            p = next(x for x in config.SOCIAL_PLATFORMS if x["id"] == pid)
            ok, reason = reachability.probe_platform(p)
            assert ok is True, f"{pid}: {reason}"
            assert "RSSHub" in reason

    def test_rss_source_unreachable(self, monkeypatch):
        """RSS 源所有实例都拉不到条目 → 不可达。"""
        monkeypatch.setattr(
            reachability.knowledge, "fetch_feed",
            lambda feed, instance=None, timeout=None: [],
        )
        p = next(x for x in config.SOCIAL_PLATFORMS if x["id"] == "cls")
        ok, reason = reachability.probe_platform(p)
        assert ok is False
        assert "RSSHub" in reason

    def test_rss_probe_tries_all_instances(self, monkeypatch):
        """多实例 fallback：第一实例失败、第二实例成功 → 可达（2026-09-09 修复）。"""
        calls = []

        def fake_fetch(feed, instance=None, timeout=None):
            calls.append(instance)
            return [] if instance == config.RSSHUB_INSTANCES[0] else [{"title": "条目"}]

        monkeypatch.setattr(reachability.knowledge, "fetch_feed", fake_fetch)
        p = next(x for x in config.SOCIAL_PLATFORMS if x["id"] == "cls")
        ok, reason = reachability.probe_platform(p)
        assert ok is True
        assert len(calls) >= 2  # 至少试了两个实例
        assert calls[0] == config.RSSHUB_INSTANCES[0]

    def test_rsshub_instances_exclude_dead_app(self):
        """rsshub.app 官方实例在大陆不可达，已从配置移除，避免探测白等超时。"""
        assert not any("rsshub.app" in i for i in config.RSSHUB_INSTANCES)

    def test_zhihu_xueqiu_cookie_missing(self):
        """知乎/雪球已改为 Cookie 类：无 Cookie → 不可达且提示关键 key。"""
        for pid, key in (("zhihu", "z_c0"), ("xueqiu", "xq_a_token")):
            p = next(x for x in config.SOCIAL_PLATFORMS if x["id"] == pid)
            ok, reason = reachability.probe_platform(p)
            assert ok is False
            assert "Cookie" in reason
            assert key in reason  # 提示需要哪个 key

    def test_zhihu_cookie_probe_ok(self, monkeypatch):
        agent_db.platform_cookie_set("zhihu", "z_c0=abc; d_c0=def")
        zhihu = next(p for p in config.SOCIAL_PLATFORMS if p["id"] == "zhihu")
        monkeypatch.setattr("requests.get", lambda *a, **kw: FakeResp(200))
        ok, _ = reachability.probe_platform(zhihu)
        assert ok is True

    def test_zhihu_cookie_probe_401(self, monkeypatch):
        agent_db.platform_cookie_set("zhihu", "z_c0=bad")
        zhihu = next(p for p in config.SOCIAL_PLATFORMS if p["id"] == "zhihu")
        monkeypatch.setattr("requests.get", lambda *a, **kw: FakeResp(401))
        ok, _ = reachability.probe_platform(zhihu)
        assert ok is False

    def test_xueqiu_cookie_probe_needs_json(self, monkeypatch):
        """雪球探测要求 JSON Content-Type（未登录返回 WAF text/html → 不可达）。"""
        agent_db.platform_cookie_set("xueqiu", "xq_a_token=abc")
        xueqiu = next(p for p in config.SOCIAL_PLATFORMS if p["id"] == "xueqiu")

        class HtmlResp:
            status_code = 200
            headers = {"Content-Type": "text/html"}

        class JsonResp:
            status_code = 200
            headers = {"Content-Type": "application/json"}

        monkeypatch.setattr("requests.get", lambda *a, **kw: HtmlResp())
        ok, _ = reachability.probe_platform(xueqiu)
        assert ok is False  # WAF 页 → 不可达
        monkeypatch.setattr("requests.get", lambda *a, **kw: JsonResp())
        ok, _ = reachability.probe_platform(xueqiu)
        assert ok is True

    def test_social_platforms_has_7_places(self):
        """合并后「爱逛的地方」= 5 社交 + 财联社 + 华尔街见闻，共 7 个。"""
        ids = {p["id"] for p in config.SOCIAL_PLATFORMS}
        assert ids == {
            "weibo", "xhs", "x", "zhihu", "xueqiu", "cls", "wallstreetcn",
        }
        # kind 分类正确（知乎/雪球 2026-09-09 由 rss 改 cookie）
        kinds = {p["id"]: p["kind"] for p in config.SOCIAL_PLATFORMS}
        assert kinds["cls"] == "rss" and kinds["wallstreetcn"] == "rss"
        assert kinds["weibo"] == "cookie" and kinds["xhs"] == "cookie"
        assert kinds["zhihu"] == "cookie" and kinds["xueqiu"] == "cookie"
        assert kinds["x"] == "none"
        # cookie 平台带关键 key 提示（提示用户取哪个 key-value）
        keys = {p["id"]: p.get("cookie_keys") for p in config.SOCIAL_PLATFORMS}
        assert "SUB" in keys["weibo"]
        assert "web_session" in keys["xhs"]
        assert "z_c0" in keys["zhihu"]
        assert "xq_a_token" in keys["xueqiu"]
        # playable：4 个 cookie 平台可逛（逛状态素材源），X/RSS 源不可逛
        playable = {p["id"] for p in config.SOCIAL_PLATFORMS if p.get("playable")}
        assert playable == {"weibo", "xhs", "zhihu", "xueqiu"}

    def test_browse_state_mapping(self):
        """逛状态 id ↔ 平台映射（含新增知乎/雪球）。"""
        assert config.browse_state_to_platform("weibo_browse") == "weibo"
        assert config.browse_state_to_platform("zhihu_browse") == "zhihu"
        assert config.browse_state_to_platform("xueqiu_browse") == "xueqiu"
        assert config.browse_state_to_platform("reading") is None
        assert "zhihu_browse" in config.browse_state_ids()
        assert "xueqiu_browse" in config.browse_state_ids()

    def test_ensure_writes_cache(self, monkeypatch):
        """首次启动全量判定写缓存（X 固定 false，Cookie 缺失 false，RSS 探测）。"""
        monkeypatch.setattr("requests.get", lambda *a, **kw: FakeResp(200))
        monkeypatch.setattr(
            reachability.knowledge, "fetch_feed",
            lambda feed, instance=None, timeout=None: [{"title": "条目"}],
        )
        agent_db.platform_cookie_set("weibo", "SUB=abc")
        agent_db.platform_cookie_set("xhs", "a=1")
        agent_db.platform_cookie_set("zhihu", "z_c0=abc")
        agent_db.platform_cookie_set("xueqiu", "xq_a_token=abc")
        cache = reachability.ensure_reachability()
        assert "weibo" in cache
        assert "xhs" in cache
        assert "x" in cache
        # RSS 源可达（mock 拉到条目）
        assert cache["cls"]["reachable"] is True
        assert cache["wallstreetcn"]["reachable"] is True
        # Cookie 平台有 Cookie → 可达（mock 200）
        assert cache["zhihu"]["reachable"] is True
        assert cache["xueqiu"]["reachable"] is True
        # 无缓存的平台读 get_reachability 返回保守 false
        cache2 = reachability.get_reachability()
        for p in config.SOCIAL_PLATFORMS:
            assert p["id"] in cache2
            assert "reachable" in cache2[p["id"]]


# ═══════════════════════════════════════════
# playwright_collector：入库去重 + 失败回写
# ═══════════════════════════════════════════


class TestPlaywrightCollector:
    def test_store_items_url_dedup(self):
        """url 精确去重：同 url 二次插入 → dup。"""
        items = [
            {"title": "热搜一", "url": "https://m.weibo.cn/status/1", "summary": "a"}
        ]
        st = playwright_collector._store_items("weibo", items)
        assert st["added"] == 1
        st2 = playwright_collector._store_items("weibo", items)
        assert st2["dup"] == 1

    def test_store_items_title_similar(self):
        """标题相似去重：URL 不同但标题高度相似 → 跳过（added 0）。"""
        playwright_collector._store_items(
            "weibo",
            [{"title": "今日A股三大指数集体收涨", "url": "https://m.weibo.cn/status/1", "summary": ""}],
        )
        st = playwright_collector._store_items(
            "weibo",
            [{"title": "A股三大指数集体收涨！", "url": "https://m.weibo.cn/status/2", "summary": ""}],
        )
        assert st["added"] == 0
        assert st["dup"] >= 1

    def test_collect_missing_cookie(self):
        """无 Cookie → ok=False + 回写 reachability=false。"""
        result = playwright_collector.collect_platform("weibo")
        assert result["ok"] is False
        assert "Cookie" in result["error"]
        assert agent_db.reachability_get("weibo")["reachable"] is False

    def test_collect_success(self, monkeypatch):
        """采集成功 → 入库 + 回写 reachability=true。"""
        agent_db.platform_cookie_set("weibo", "SUB=abc")
        monkeypatch.setattr(
            playwright_collector,
            "_weibo_hot_items",
            lambda cookie, limit: [
                {"title": f"热搜{i}", "url": f"https://m.weibo.cn/status/{i}", "summary": ""}
                for i in range(3)
            ],
        )
        result = playwright_collector.collect_platform("weibo")
        assert result["ok"] is True
        assert result["added"] == 3
        assert agent_db.reachability_get("weibo")["reachable"] is True

    def test_collect_failure_writes_unreachable(self, monkeypatch):
        """采集异常 → ok=False + 回写 reachability=false。"""
        agent_db.platform_cookie_set("weibo", "SUB=abc")

        def boom(cookie, limit):
            raise RuntimeError("反爬")

        monkeypatch.setattr(playwright_collector, "_weibo_hot_items", boom)
        result = playwright_collector.collect_platform("weibo")
        assert result["ok"] is False
        assert agent_db.reachability_get("weibo")["reachable"] is False


# ═══════════════════════════════════════════
# behavior.execute_browse：采集→浏览→动态直接发
# ═══════════════════════════════════════════


class TestExecuteBrowse:
    def test_browse_no_cookie(self):
        """无 Cookie → 逛行为失败返回，不崩。"""
        result = behavior.execute_browse("weibo")
        assert result["ok"] is False
        assert "Cookie" in result["error"]

    def test_browse_success_posts_direct(self, monkeypatch):
        """采集成功 + 阅读产出动态 → 直接发（kind=post）。"""
        agent_db.platform_cookie_set("weibo", "SUB=abc")
        # 先真实入库 2 条 weibo 素材（模拟采集结果）
        for i in range(2):
            agent_db.knowledge_upsert(
                "weibo", f"微博热点{i}", f"https://m.weibo.cn/status/{i}", "摘要"
            )
        # mock 采集成功（但 execute_browse 从库中读未读浏览）
        monkeypatch.setattr(
            playwright_collector,
            "collect_platform",
            lambda pid, db=None: {
                "platform_id": pid, "ok": True, "collected": 2,
                "added": 2, "dup": 0,
            },
        )
        # mock llm：返回带动态的 JSON
        def fake_llm(task):
            return json.dumps({
                "viewpoint": "热点观点",
                "emotion": "excited",
                "memory": "有点意思",
                "post_content": "今天看到个有意思的热点，记一下。",
                "worth_post": True,
            }, ensure_ascii=False)

        result = behavior.execute_browse("weibo", llm_fn=fake_llm)
        assert result["ok"] is True
        assert result["read_count"] >= 1
        assert result["posted_count"] >= 1
        # 动态确实入库（kind=post）
        posts = [a for a in agent_db.article_list(limit=20) if a["kind"] == "post"]
        assert len(posts) >= 1
        # 逛冷却时间戳已写
        assert agent_db.meta_get("xiaoman_last_browse_at") is not None

    def test_browse_no_touch_no_post(self, monkeypatch):
        """没触动 → 不产出动态（worth_post=false）。"""
        agent_db.platform_cookie_set("weibo", "SUB=abc")
        agent_db.knowledge_upsert(
            "weibo", "微博热点", "https://m.weibo.cn/status/1", "摘要"
        )
        monkeypatch.setattr(
            playwright_collector,
            "collect_platform",
            lambda pid, db=None: {"platform_id": pid, "ok": True, "collected": 1, "added": 1, "dup": 0},
        )

        def fake_llm(task):
            return json.dumps({
                "viewpoint": "", "emotion": "calm", "memory": "",
                "post_content": "", "worth_post": False,
            }, ensure_ascii=False)

        result = behavior.execute_browse("weibo", llm_fn=fake_llm)
        assert result["ok"] is True
        assert result["posted_count"] == 0
