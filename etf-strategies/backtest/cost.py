"""交易成本模型。A股ETF：佣金万2.5最低5元、免印花税、滑点万1。"""
from dataclasses import dataclass


@dataclass
class Cost:
    commission_rate: float = 2.5e-4   # 佣金费率（按成交额）
    min_commission: float = 5.0       # 单笔最低佣金（元）
    stamp_duty: float = 0.0           # 印花税（ETF免）
    slippage: float = 1e-4            # 滑点（单边）

    def one_way(self):
        """单边总成本率（不含最低佣金，按大额近似）。"""
        return self.commission_rate + self.stamp_duty + self.slippage
