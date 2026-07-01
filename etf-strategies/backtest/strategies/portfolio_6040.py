import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
from .base import Strategy


class Portfolio6040(Strategy):
    """S6 60/40 股债平衡。
    目标权重恒定 60%股+40%债。季末再平衡（恢复目标）。
    简化：目标权重恒定，引擎每日按目标持有，等效日日维持（spec 注明简化）。
    首版不模拟季内漂移，仅按季调仓频率扣成本由换手率反映。"""
    name = "S6_60-40股债平衡"

    def __init__(self, stock="510300", bond="511260", w_stock=0.6, w_bond=0.4):
        self.stock, self.bond = stock, bond
        self.w_stock, self.w_bond = w_stock, w_bond
        self.assets = [stock, bond]

    def generate(self, prices):
        weights = pd.DataFrame(0.0, index=prices.index, columns=self.assets)
        weights[self.stock] = self.w_stock
        weights[self.bond] = self.w_bond
        # 季末再平衡信号：每行目标恒为60-40，季末触发（权重不变）
        quarterly = weights.resample("QE").last()
        weights = quarterly.reindex(prices.index, method="ffill").bfill().fillna(0.0)
        return weights
