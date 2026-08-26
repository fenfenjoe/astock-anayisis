"""
可用金额/建仓份额核心逻辑 — 2026-08-26 可用金额引入
(spec: docs/superpowers/specs/2026-08-26-available-cash-design.md)

纯计算函数，不读写磁盘，不调用外部 API。
  1. parse_available_cash  — 从每日调仓.md 解析可用金额
  2. verify_cash_change    — 与当日调仓交叉验证（漏记/未更新告警）
  3. calc_position_shares  — 建仓信号份额 = 可用金额 × 分级比例 ÷ 价格
"""

import re

# 建仓份额分级比例（信号置信度越高仓位越大）
POSITION_RATIOS = {
    'open_high': 1 / 3,   # P1 直接建仓（高置信）
    'upgrade': 1 / 4,     # 观察→升级建仓（盘中）
    'probe': 1 / 5,       # 试探/低置信
}


def parse_available_cash(md_text: str) -> int | None:
    """解析每日调仓.md 的 `## 0. 可用金额` → int；缺失/非数字 → None。"""
    m = re.search(r'##\s*0\.\s*可用金额\s*\n\s*\n\s*([\d,]+)', md_text)
    if not m:
        return None
    return int(m.group(1).replace(',', ''))


def verify_cash_change(old_cash: float, new_cash: float,
                       trades: list, tolerance: float = 1.0) -> list:
    """交叉验证：期望新可用金额 = 旧值 + Σ卖出额 - Σ买入额。
    实际与期望偏差 > tolerance → 返回告警（不抛异常）。
    trades: [{'direction': '买入'|'卖出', 'qty': int, 'price': float}]"""
    warnings = []
    net = 0.0
    for t in trades:
        qty = float(t.get('qty', 0))
        price = float(t.get('price', 0.0))
        amount = qty * price
        if t.get('direction') == '卖出':
            net += amount
        else:  # 买入
            net -= amount
    expected = old_cash + net
    deviation = abs(new_cash - expected)
    if deviation > tolerance:
        warnings.append(
            f'可用金额偏差 {deviation:.2f} 元：期望 {expected:.2f}'
            f'（旧值 {old_cash:.2f} + 调仓净额 {net:.2f}），实际 {new_cash:.2f}'
            f'——可能漏记交易或可用金额未更新'
        )
    return warnings


def calc_position_shares(available_cash: float, price: float, ratio: float) -> int:
    """建仓份额 = floor(可用金额×比例/价格/100)×100（ETF 100份整数）。
    价格≤0 / 可用金额≤0 / 比例≤0 / 不足100份 → 0。"""
    if price <= 0 or available_cash <= 0 or ratio <= 0:
        return 0
    raw = available_cash * ratio / price
    return int(raw // 100) * 100
