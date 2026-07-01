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
