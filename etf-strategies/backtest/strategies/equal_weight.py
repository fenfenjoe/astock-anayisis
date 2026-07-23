"""S5 等权组合：多资产等权重，定期再平衡。

原理：对组合中每个ETF赋予相同权重，定期再平衡恢复目标权重。
再平衡操作自带"逆向再平衡 alpha"：卖出超涨品种、买入超跌品种。
策略极简、分散、可作为多资产组合的朴素基准。

季末再平衡。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
from .base import Strategy


class EqualWeight(Strategy):
    """S5 等权组合：多资产等权重，季末再平衡。"""

    name = "S5_等权组合"

    def __init__(self, assets=None):
        if assets is None:
            assets = ["510300", "510500", "159915", "511260"]
        self.assets = assets

    def generate(self, prices):
        n = len(self.assets)
        if n == 0:
            return pd.DataFrame(index=prices.index)
        weights = pd.DataFrame(1.0 / n, index=prices.index, columns=self.assets)
        # 季末再平衡：取每季度最后交易日信号，向前填充
        quarterly = weights.resample("QE").last()
        weights = quarterly.reindex(prices.index, method="ffill").bfill().fillna(1.0 / n)
        return weights
