"""
data_source_probe 测试 — 覆盖 get_data_paths 纯逻辑（不依赖网络）。

网络探测本身（_probe_* 函数）不做单测（真实网络不可控），
只测确定性的 fallback 路径生成逻辑。
"""
import json
import sys
from pathlib import Path

import pytest

# 确保 lib 可导入
LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from data_source_probe import get_data_paths


def _status(**overrides):
    """构造默认全 ok 的状态 dict，可按需覆盖"""
    base = {
        "push2": "ok",
        "push2his": "ok",
        "tencent": "ok",
        "ths": "ok",
        "push2ex": "ok",
        "mootdx": "ok",
        "datacenter": "ok",
    }
    base.update(overrides)
    return base


class TestAllOk:
    """全部数据源可达 — 所有 primary 使用主数据源"""

    def test_industry_ranking_uses_push2(self):
        paths = get_data_paths(_status())
        assert paths["industry_ranking"]["primary"].startswith("东财 push2")
        assert paths["industry_ranking"]["note"] == ""

    def test_northbound_uses_push2(self):
        paths = get_data_paths(_status())
        assert paths["northbound"]["primary"].startswith("东财 push2")
        assert paths["northbound"]["note"] == ""

    def test_fund_flow_uses_push2his(self):
        paths = get_data_paths(_status())
        assert "push2his" in paths["fund_flow"]["primary"]
        assert paths["fund_flow"]["note"] == ""

    def test_margin_uses_datacenter(self):
        paths = get_data_paths(_status())
        assert "datacenter" in paths["margin"]["primary"]
        assert paths["margin"]["note"] == ""

    def test_limit_up_uses_push2ex(self):
        paths = get_data_paths(_status())
        assert "push2ex" in paths["limit_up"]["primary"]
        assert paths["limit_up"]["note"] == ""

    def test_kline_uses_mootdx(self):
        paths = get_data_paths(_status())
        assert paths["kline"]["primary"] == "mootdx TCP"
        assert paths["kline"]["note"] == ""


class TestPush2Down:
    """push2 不可达 — 行业排名/北向走 fallback；push2his 独立不受影响"""

    def test_industry_ranking_fallback(self):
        paths = get_data_paths(_status(push2="fail"))
        assert "腾讯" in paths["industry_ranking"]["primary"]
        assert "push2 不可达" in paths["industry_ranking"]["note"]

    def test_northbound_fallback(self):
        paths = get_data_paths(_status(push2="fail"))
        assert "同花顺" in paths["northbound"]["primary"]
        assert "push2 不可达" in paths["northbound"]["note"]

    def test_fund_flow_unaffected_by_push2(self):
        """push2his 独立子域名：push2 失败不影响 fund_flow 主源"""
        paths = get_data_paths(_status(push2="fail"))
        assert "push2his" in paths["fund_flow"]["primary"]
        assert paths["fund_flow"]["note"] == ""

    def test_hot_themes_unaffected(self):
        """题材热度走同花顺，不受 push2 影响"""
        paths = get_data_paths(_status(push2="fail"))
        assert "同花顺" in paths["hot_themes"]["primary"]
        assert paths["hot_themes"]["note"] == ""

    def test_margin_unaffected(self):
        """融资融券走 datacenter 子域名，push2 失败时仍可用"""
        paths = get_data_paths(_status(push2="fail"))
        assert "datacenter" in paths["margin"]["primary"]
        assert paths["margin"]["note"] == ""


class TestPush2hisDown:
    """push2his 不可达 — 仅 fund_flow 走 fallback，push2 其他数据不受影响"""

    def test_fund_flow_fallback_when_push2his_down(self):
        paths = get_data_paths(_status(push2his="fail"))
        assert "mootdx" in paths["fund_flow"]["primary"]
        assert "push2his 不可达" in paths["fund_flow"]["note"]

    def test_industry_ranking_unaffected_by_push2his(self):
        """push2（行业排名）与 push2his 独立，push2his 失败不影响行业排名"""
        paths = get_data_paths(_status(push2his="fail"))
        assert "push2" in paths["industry_ranking"]["primary"]
        assert paths["industry_ranking"]["note"] == ""

    def test_northbound_unaffected_by_push2his(self):
        paths = get_data_paths(_status(push2his="fail"))
        assert "push2" in paths["northbound"]["primary"]
        assert paths["northbound"]["note"] == ""


class TestMultiSourceDown:
    """多数据源同时不可达 — 极端场景"""

    def test_push2ex_and_ths_down(self):
        paths = get_data_paths(_status(push2ex="fail", ths="fail"))
        assert "数据缺失" in paths["limit_up"]["primary"]
        assert "涨停板数据缺失" in paths["limit_up"]["note"]

    def test_push2ex_down_ths_up(self):
        paths = get_data_paths(_status(push2ex="fail", ths="ok"))
        assert "同花顺" in paths["limit_up"]["primary"]
        assert "push2ex 不可达" in paths["limit_up"]["note"]

    def test_mootdx_down(self):
        paths = get_data_paths(_status(mootdx="fail"))
        assert "腾讯" in paths["kline"]["primary"]
        assert "mootdx TCP 不可达" in paths["kline"]["note"]

    def test_margin_datacenter_down(self):
        paths = get_data_paths(_status(datacenter="fail"))
        assert "数据缺失" in paths["margin"]["primary"]
        assert "datacenter 不可达" in paths["margin"]["note"]

    def test_tencent_down_overseas_webserach(self):
        paths = get_data_paths(_status(tencent="fail"))
        assert "WebSearch" in paths["overseas"]["primary"]
        assert "腾讯财经海外指数不可达" in paths["overseas"]["note"]


class TestOutputStructure:
    """输出结构完整性"""

    def test_all_data_types_present(self):
        """8 类数据路径全部输出"""
        paths = get_data_paths(_status())
        expected = {
            "industry_ranking", "northbound", "fund_flow", "margin",
            "limit_up", "hot_themes", "overseas", "kline",
        }
        assert expected == set(paths.keys())

    def test_each_path_has_three_fields(self):
        paths = get_data_paths(_status())
        for key, p in paths.items():
            assert "primary" in p, f"{key} 缺 primary"
            assert "fallback" in p, f"{key} 缺 fallback"
            assert "note" in p, f"{key} 缺 note"
            assert p["primary"], f"{key} primary 为空"
