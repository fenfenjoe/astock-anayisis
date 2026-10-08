"""
条件单参数推导 — REQ-011

P0 执行通道结构化：早盘生成 P0 信号时，从信号总表【机械推导】可直接下单的条件单参数，
用户开盘 1 分钟内即可挂单，此后无需盘中盯盘。

纯计算函数，不读写磁盘，不调用外部 API。跨文件输入为 parse_signal_rows_all 的单条记录
（lib/signal_tracking.py），输出为条件单参数 dict / markdown 节文本。

与 REQ-007（P0 执行追踪）/ REQ-010（显式放弃交互）互补：
  - REQ-007 管"追踪与问责"
  - REQ-010 管"放弃通道"
  - 本模块（REQ-011）管"执行通道"——把条件单参数在早盘就机械确定，开盘即可挂单

约束（REQ-011）：
  - 条件单参数必须由早盘分析从信号表机械推导，不允许事后补造
  - 条件单仅为提示性输出，不实现真实下单接口（合规边界）
  - 不改变 P0 风控信号的"必须执行或显式放弃"定性
"""


# ============================================================
# 常量
# ============================================================

# 默认有效期（当日截止，REQ-011 期望结果 ④）
DEFAULT_EXPIRY = '14:45'

# 方向英文 → 中文
_DIRECTION_CN = {
    'sell': '卖出',
    'buy': '买入',
}

# 条件单清单节标题
_COND_ORDER_SECTION = '## 条件单清单（REQ-011）'

# 挂单状态初始值
_STATUS_NOT_HUNG = '待挂单'


# ============================================================
# 工具函数
# ============================================================

def _extract_ticker(标的: str) -> str:
    """从 '工商银行(601398)' 或 '银行ETF(512800)' 提取 6 位代码；失败返回空串。"""
    import re
    m = re.search(r'(\d{6})', 标的)
    return m.group(1) if m else ''


def parse_quantity(position: str) -> int:
    """从仓位文本解析份额（份）。

    '-1,100份（约-25%）' → 1100；'+200份' → 200；'500份' → 500；
    '900份(可用×1/3)' → 900；无份数（如 '1/4'）→ 0。
    """
    import re
    if not position:
        return 0
    m = re.search(r'([\d,]+)\s*份', position)
    return int(m.group(1).replace(',', '')) if m else 0


def _format_price(price) -> str:
    """触发价格式化为字符串，保留原精度（不截断）。

    输入为 float（如 8.05 / 8.055）或字符串（'8.05'）。float 用最长 3 位小数表示。
    """
    if price is None or price == '' or price == '—':
        return ''
    if isinstance(price, float):
        return f'{price:.3f}'.rstrip('0').rstrip('.') if price % 1 else f'{price:.0f}'
    return str(price).strip()


def _build_cancel_hint(signal: dict) -> str:
    """条件反转撤销提示：从触发条件提取"站回/收复/证伪"等关键字，否则用默认 REQ-010 提示。

    触发条件含"站回/收复" → 提示依据该防线；含"证伪" → 提示证伪线满足时撤销；
    其余 → 默认"条件反转（防线收复/证伪线满足）时按盘中 REQ-010 二选一，未回复不自动撤销"。
    """
    cond = (signal.get('trigger_condition') or '').strip()
    if '站回' in cond or '收复' in cond:
        return f'条件反转（触发条件中防线站回/收复）时撤销，按盘中 REQ-010 二选一确认'
    if '证伪' in cond:
        return '证伪线满足时撤销，按盘中 REQ-010 二选一确认'
    return '条件反转（防线收复/证伪线满足）时按盘中 REQ-010 二选一，未回复不自动撤销'


# ============================================================
# build_cond_order — 从单条 P0 信号机械推导条件单参数
# ============================================================

def build_cond_order(signal: dict) -> dict | None:
    """从单条 P0 信号机械推导条件单参数。

    输入 signal 为 parse_signal_rows_all 单条记录（含 signal_id/ticker/name/trade_type/
    direction/trade_price/position/trigger_condition 等键）。

    返回 None 的情形：
      - 非 P0 信号（priority != 'P0'）
      - 缺代码（ticker 空）
      - 缺触发价（trade_price 空/None）

    返回 dict：
    {
        'signal_id': 'SIG-20261008-01',
        'ticker': '601398',
        'name': '工商银行',
        'direction': '卖出',            # 中文方向
        'trigger_price': '8.05',        # 字符串保留原精度
        'quantity': 500,                # 份
        'expiry': '14:45',              # 默认当日 14:45
        'cancel_hint': '...',           # 条件反转撤销提示
        'status': '待挂单',             # 挂单状态（初始；收盘复盘统计用）
        'cond_order_line': '601398 触发价 8.05 卖出 500份 有效期至 14:45',  # 可直接照抄
    }
    """
    if signal.get('priority') != 'P0':
        return None
    ticker = (signal.get('ticker') or '').strip()
    price = _format_price(signal.get('trade_price'))
    if not ticker or not price:
        return None

    name = signal.get('name') or ''
    direction_cn = _DIRECTION_CN.get(signal.get('direction'), signal.get('direction') or '')
    quantity = parse_quantity(signal.get('position') or '')
    expiry = DEFAULT_EXPIRY

    if quantity > 0:
        qty_text = f'{quantity}份'
        line = f'{ticker} 触发价 {price} {direction_cn} {qty_text} 有效期至 {expiry}'
    else:
        qty_text = '份额—'
        line = f'{ticker} 触发价 {price} {direction_cn} {qty_text} 有效期至 {expiry}'

    return {
        'signal_id': signal.get('signal_id') or '',
        'ticker': ticker,
        'name': name,
        'direction': direction_cn,
        'trigger_price': price,
        'quantity': quantity,
        'expiry': expiry,
        'cancel_hint': _build_cancel_hint(signal),
        'status': _STATUS_NOT_HUNG,
        'cond_order_line': line,
    }


# ============================================================
# build_cond_order_table — 生成 `## 条件单清单（REQ-011）` markdown 节
# ============================================================

def build_cond_order_table(p0_signals: list[dict]) -> str:
    """从 P0 信号记录列表生成 `## 条件单清单（REQ-011）` markdown 节。

    仅含 P0 信号（内部过滤）。无 P0 → 返回空字符串（早盘不生成空节）。
    生成表：
    | 信号ID | 标的 | 代码 | 方向 | 触发价 | 数量(份) | 有效期 | 挂单状态 | 条件单指令（可直接照抄） |
    """
    rows = []
    for sig in p0_signals:
        co = build_cond_order(sig)
        if co is None:
            continue
        qty = str(co['quantity']) if co['quantity'] > 0 else '—'
        rows.append(
            f"| {co['signal_id']} | {co['name']} | {co['ticker']} | {co['direction']} | "
            f"{co['trigger_price']} | {qty} | {co['expiry']} | {co['status']} | {co['cond_order_line']} |"
        )
    if not rows:
        return ''

    header = (
        f"{_COND_ORDER_SECTION}\n\n"
        "> 早盘生成：从 P0 信号机械推导，用户开盘 1 分钟内即可挂单，此后无需盘中盯盘。\n"
        "> 条件单仅为提示性输出（不实现真实下单接口）；条件反转撤销见盘中 REQ-010 二选一。\n"
        "> 挂单状态由盘中检查/收盘复盘更新（待挂单 → 已挂单）。\n\n"
        "| 信号ID | 标的 | 代码 | 方向 | 触发价 | 数量(份) | 有效期 | 挂单状态 | 条件单指令（可直接照抄） |\n"
        "|--------|------|------|:---:|:---:|:---:|:---:|:---:|--------------------------|\n"
    )
    return header + '\n'.join(rows) + '\n'


# ============================================================
# parse_cond_order_table — 从 md 解析回条件单参数（盘中复用 + 收盘统计）
# ============================================================

def _strip_md(cell: str) -> str:
    """剥离单元格中的 markdown 加粗标记。"""
    return cell.replace('**', '').strip()


def _col(header: list[str], *names: str) -> int:
    """在表头中定位列索引；找不到返回 -1。"""
    for i, h in enumerate(header):
        if any(name in h for name in names):
            return i
    return -1


def _parse_table_rows(md_text: str, section: str) -> tuple[list[str], list[list[str]]]:
    """从 markdown 中解析某节标题下的表格（同 lib/p0_tracking.py 的实现）。

    返回 (header, rows)：header 为表头列名列表，rows 为数据行（已去分隔线）。
    """
    lines = md_text.splitlines()
    collecting = False
    raw_rows = []
    for line in lines:
        if line.startswith('##') and line.strip() != section:
            if collecting:
                break
        if line.strip() == section:
            collecting = True
            continue
        if collecting and line.strip().startswith('|'):
            raw_rows.append([_strip_md(c) for c in line.strip().strip('|').split('|')])

    header: list[str] = []
    rows: list[list[str]] = []
    for row in raw_rows:
        if row and all(c.replace(':', '').replace('-', '').strip() == '' for c in row):
            continue
        if not header and row and any('信号ID' in c for c in row):
            header = row
            continue
        if row and any(c for c in row):
            rows.append(row)
    return header, rows


def parse_cond_order_table(md_text: str) -> list[dict]:
    """从每日信号.md 解析 `## 条件单清单（REQ-011）` 节，返回条件单参数 dict 列表。

    节不存在/空 → []。每条含 build_cond_order 的全部键 + 'status'（挂单状态）。
    供盘中检查复用（不再重新推导，REQ-011 期望结果③）与收盘复盘统计挂单率（期望结果④）。
    """
    header, rows = _parse_table_rows(md_text, _COND_ORDER_SECTION)
    if not header:
        return []

    c_id = _col(header, '信号ID')
    c_name = _col(header, '标的')
    c_ticker = _col(header, '代码')
    c_dir = _col(header, '方向')
    c_price = _col(header, '触发价')
    c_qty = _col(header, '数量')
    c_expiry = _col(header, '有效期')
    c_status = _col(header, '挂单状态')
    c_line = _col(header, '条件单指令')

    result = []
    for row in rows:
        def g(idx):
            return row[idx] if 0 <= idx < len(row) else ''

        signal_id = g(c_id)
        if not signal_id.startswith('SIG-'):
            continue
        qty_raw = g(c_qty)
        result.append({
            'signal_id': signal_id,
            'name': g(c_name),
            'ticker': g(c_ticker),
            'direction': g(c_dir),
            'trigger_price': g(c_price),
            'quantity': int(qty_raw.replace(',', '')) if qty_raw and qty_raw != '—' else 0,
            'expiry': g(c_expiry) or DEFAULT_EXPIRY,
            'status': g(c_status) or _STATUS_NOT_HUNG,
            'cond_order_line': g(c_line),
        })
    return result
