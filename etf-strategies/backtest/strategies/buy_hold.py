import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
from .base import Strategy


class BuyHold(Strategy):
    """S1 买入持有：恒满仓，不调仓。作基准 benchmark。"""
    name = "S1_买入持有"

    def __init__(self, code="510300"):
        self.code = code
        self.assets = [code]

    def generate(self, prices):
        return pd.DataFrame(1.0, index=prices.index, columns=self.assets)
