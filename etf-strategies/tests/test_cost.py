import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from backtest.cost import Cost


def test_default_cost():
    """A股ETF默认成本：佣金万2.5、最低5元、免印花税、滑点万1"""
    c = Cost()
    assert c.commission_rate == 2.5e-4
    assert c.min_commission == 5.0
    assert c.stamp_duty == 0.0  # ETF 免印花税
    assert c.slippage == 1e-4


def test_one_way_total():
    """单边总成本 = 佣金 + 印花税 + 滑点 = 万3.5"""
    c = Cost()
    assert abs(c.one_way() - 3.5e-4) < 1e-10


def test_custom_cost():
    c = Cost(commission_rate=3e-4, slippage=2e-4)
    assert abs(c.one_way() - 5e-4) < 1e-10
