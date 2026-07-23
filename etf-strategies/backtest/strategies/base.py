"""策略基类。策略只产目标权重，不管交易/成本。"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd


class Strategy:
    name: str = "base"
    assets: list = []

    def generate(self, prices: pd.DataFrame) -> pd.DataFrame:
        """prices: 日期×资产 收盘价. 返回: 日期×资产 目标权重(0~1, 每行和≈1)"""
        raise NotImplementedError

    def get_diagnostics(self, prices: pd.DataFrame) -> dict:
        """Return strategy-specific internal state for the most recent trading days.
        Override in subclasses to expose indicators like canary scores, momentum values, etc.
        Returns: {parameters: {...}, scores: {...}, holdings: {...}}"""
        w = self.generate(prices)
        latest = w.iloc[-1]
        holdings = {str(c): round(float(latest.get(c, 0)), 4)
                    for c in self.assets if latest.get(c, 0) > 0.001}
        return {
            "strategy_id": self.__class__.__name__,
            "latest_date": str(w.index[-1].date()),
            "parameters": {},
            "scores": {},
            "holdings": holdings,
        }
