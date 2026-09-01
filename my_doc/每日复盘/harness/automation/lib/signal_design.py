"""
信号设计质量核心逻辑 — REQ-002

从 早盘分析-模板.md 规则1-4 + 盘中分析-模板.md 过期逻辑提取。
纯计算函数，不读写磁盘，不调用外部 API。
"""

from datetime import date, datetime, timedelta
from typing import Union


# ============================================================
# 时间窗口计算
# ============================================================

def calc_window_milestones(start: datetime, end: datetime) -> dict:
    """计算信号时间窗口的 50% 和 75% 里程碑。

    Returns:
        {"pct50": datetime, "pct75": datetime, "total_minutes": int}
    """
    total_seconds = (end - start).total_seconds()
    total_minutes = int(total_seconds / 60)
    pct50 = start + timedelta(seconds=total_seconds * 0.5)
    pct75 = start + timedelta(seconds=total_seconds * 0.75)

    return {
        'pct50': pct50,
        'pct75': pct75,
        'total_minutes': total_minutes,
    }


# ============================================================
# 50% 窗口自检
# ============================================================

def is_price_reachable(
    current: float,
    target: float,
    remaining_minutes: int,
    daily_volatility_pct: float = 3.0,
) -> bool:
    """判断当前价格距触发条件在剩余时间内是否可达。

    基于日均波动率，估算剩余时间内价格能波动的最大幅度。

    Args:
        current: 当前价格
        target: 触发条件所需价格
        remaining_minutes: 剩余交易分钟数
        daily_volatility_pct: 日均波动率百分比（默认3%）

    Returns:
        True 如果剩余时间内的预期最大波动 >= 所需变动
    """
    if current == target:
        return True

    full_day_minutes = 240.0
    time_ratio = remaining_minutes / full_day_minutes
    max_move_pct = daily_volatility_pct * (time_ratio ** 0.5)
    required_move_pct = abs((target - current) / current) * 100.0

    return max_move_pct >= required_move_pct


# ============================================================
# 75% 强制过期
# ============================================================

def should_expire(signal: dict, current_time: datetime) -> bool:
    """判断信号是否应在 75% 窗口处强制过期。

    P0 信号豁免强制过期。
    非 P0 信号在 current_time >= window_pct75 时触发过期。
    """
    priority = signal.get('priority', 'P2')

    if priority == 'P0':
        return False

    window_start = signal.get('window_start')
    window_end = signal.get('window_end')

    if window_start is None or window_end is None:
        return False

    if isinstance(window_start, str):
        window_start = datetime.fromisoformat(window_start)
    if isinstance(window_end, str):
        window_end = datetime.fromisoformat(window_end)

    milestones = calc_window_milestones(window_start, window_end)
    return current_time >= milestones['pct75']


# ============================================================
# 紧急度排序
# ============================================================

_URGENCY_PRIORITY_ORDER = {
    ('high', 'P0'): 0,
    ('high', 'P1'): 1,
    ('low',  'P1'): 2,
    ('high', 'P2'): 3,
    ('low',  'P2'): 4,
}


def sort_by_urgency(signals: list[dict]) -> list[dict]:
    """按紧急度排序: 高+P0 > 高+P1 > 低+P1 > 高+P2 > 低+P2。
    返回新列表，不修改原列表。排序稳定（同权重保持原顺序）。
    """
    def sort_key(sig: dict) -> int:
        urgency = sig.get('urgency', 'low')
        priority = sig.get('priority', 'P2')
        return _URGENCY_PRIORITY_ORDER.get((urgency, priority), 99)

    return sorted(signals, key=sort_key)


# ============================================================
# 规则存在性检查
# ============================================================

def check_main_backup_paths(signal: dict) -> tuple:
    """检查信号是否有主路径和备选路径。

    Returns:
        (has_backup: bool, reason: str)
    """
    main_condition = signal.get('main_condition', '')
    backup_condition = signal.get('backup_condition', '')

    if not main_condition:
        return (False, '缺少主触发条件 (main_condition)')

    if not backup_condition:
        return (False, '缺少备选路径 (backup_condition)，规则1要求P1信号必须有备选')

    return (True, '')


def generate_graded_thresholds(strict: dict) -> dict:
    """从严格版阈值生成分级触发阈值（严格版 + 宽松版）。

    规则2: 价格放宽到97%，成交量放宽到70%。
    """
    loose = dict(strict)

    if 'price' in strict:
        loose['price'] = round(strict['price'] * 0.97, 2)
    if 'volume' in strict:
        loose['volume'] = int(strict['volume'] * 0.7)

    return {'strict': strict, 'loose': loose}


# ============================================================
# REQ-003: 财报窗口 / 主线联防 / 证伪阈值距离
# ============================================================

# 财报披露截止日（月, 日）— 中报/年报/三季报
EARNINGS_DEADLINES = [
    (4, 30),    # 年报 + 一季报截止
    (8, 31),    # 中报截止
    (10, 31),   # 三季报截止
]

# 财报窗口天数：截止日前 N 天（含截止日）视为披露窗口
EARNINGS_WINDOW_DAYS = 14


def is_earnings_window(date_input, window_days: int = EARNINGS_WINDOW_DAYS) -> bool:
    """判断日期是否处于财报披露窗口。

    财报披露窗口 = 各截止日（4/30 年报、8/31 中报、10/31 三季报）前
    `window_days` 天（含截止日当天）。

    Args:
        date_input: datetime.date 或 ISO 格式字符串（"YYYY-MM-DD"）
        window_days: 窗口天数（默认 14）

    Returns:
        True 如果日期落在任一财报披露窗口内
    """
    if isinstance(date_input, str):
        d = date.fromisoformat(date_input)
    else:
        d = date_input

    for month, day in EARNINGS_DEADLINES:
        deadline = date(d.year, month, day)
        window_start = deadline - timedelta(days=window_days - 1)
        if window_start <= d <= deadline:
            return True
    return False


def check_mainline_guard(mainline_change_pct: float, threshold: float = 1.0) -> tuple:
    """涨停潮建仓信号的"主线不弱化"联防检查（REQ-003 第 2 项）。

    所属大主线指数回落幅度 >= threshold%（默认 1%）时，建仓信号降级为观察。

    Args:
        mainline_change_pct: 所属大主线指数涨跌幅（%，负值=回落）
        threshold: 回落降级阈值（%，默认 1.0）

    Returns:
        (ok: bool, reason: str)
        ok=True 表示主线未弱化，建仓信号可保持；
        ok=False 表示主线回落超阈值，应降级为观察。
    """
    if mainline_change_pct <= -threshold:
        return (False, f'所属主线回落 {abs(mainline_change_pct):.2f}% >= {threshold}%，降级为观察')
    return (True, '')


def check_falsify_distance(
    trigger_price: float,
    falsify_price: float,
    min_distance_pct: float = 0.5,
) -> tuple:
    """证伪阈值与触发价距离校验（REQ-003 第 3 项）。

    证伪阈值应与触发价拉开 >= min_distance_pct% 距离，防止盘中轻微下探
    触发假证伪。

    Args:
        trigger_price: 信号触发价（>0）
        falsify_price: 证伪阈值价
        min_distance_pct: 最小距离百分比（默认 0.5）

    Returns:
        (ok: bool, actual_pct: float | None)
        ok=True 表示距离达标；actual_pct 为实际距离百分比；
        trigger_price<=0 时返回 (False, None)（非法输入）。
    """
    if trigger_price <= 0:
        return (False, None)

    actual_pct = abs(falsify_price - trigger_price) / trigger_price * 100.0
    return (actual_pct >= min_distance_pct, actual_pct)
