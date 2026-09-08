"""
P0 信号执行追踪核心逻辑 — REQ-007

解决 P0 信号触发后执行缺失连续重演（9/2 黄金 + 9/7 工行）的机制层：
  1. 触发即显性化 — 盘中检查把 P0 触发写入 每日信号.md 的 `## P0 执行追踪` 节
  2. 持续追踪 — 每个检查点追加响应状态，直至 已执行 / 放弃 / 错过 / 过期
  3. 复盘问责 — 收盘复盘零容忍统计 P0 执行率（已执行 P0 / 已触发 P0）
  4. 告警 — P0 执行率连续 2 日 <100% → P1 级告警

纯计算函数，不读写磁盘，不调用外部 API。
跨日状态存于 config/p0_tracking.json（daily: {date: {triggered, executed, rate, unexecuted_ids}}）。

与 REQ-006（信号质量统计区分已执行/未执行样本）解耦：
本模块只管 P0 执行保障与执行率，不触碰 signal_tracking.py / signal_quality.py。
"""


# ============================================================
# 常量
# ============================================================

_P0_SECTION = '## P0 执行追踪'

# 用户操作列取值（与 auto_morning_analysis.md §5.2 触发记录规范一致）
_EXECUTED_ACTIONS = {'已执行', '部分执行'}
_ABANDONED_ACTIONS = {'放弃'}

# 已执行终态（最终结果列取值）
_EXECUTED_FINAL = '已执行'

# 最终结果列的占位值（= 未填）
_PLACEHOLDER = '—'


def _strip_md(cell: str) -> str:
    """剥离单元格中的 markdown 加粗标记（**已执行** → 已执行）。"""
    return cell.replace('**', '').strip()


def _parse_table_rows(md_text: str, section: str) -> tuple[list[str], list[list[str]]]:
    """从 markdown 中解析某节标题下的表格。

    返回 (header, rows)：header 为表头列名列表，rows 为数据行（已去分隔线）。
    单元格自动剥离 markdown 加粗标记。
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
        # 分隔线 |:---:| → 跳过
        if row and all(c.replace(':', '').replace('-', '').strip() == '' for c in row):
            continue
        # 首行含表头关键字 → 记为 header
        if not header and row and any(k in c for c in row for k in ('信号ID', '触发时间')):
            header = row
            continue
        if row and any(c for c in row):
            rows.append(row)
    return header, rows


def _col(header: list[str], *names: str) -> int:
    """在表头中定位列索引；找不到返回 -1。"""
    for i, h in enumerate(header):
        if any(name in h for name in names):
            return i
    return -1


# ============================================================
# 解析 `## P0 执行追踪` 节
# ============================================================

def parse_p0_signals(md_text: str, today: str = '') -> list[dict]:
    """解析 每日信号.md 的 `## P0 执行追踪` 节，按 signal_id 分组为 P0 记录。

    返回列表，每条记录形如：
    {
        'signal_id': 'SIG-20260907-02',
        'name': '工商银行(601398)',
        'op_type': '减仓（1/3锁利）',
        'trigger_time': '11:05',
        'checkpoints': [
            {'checkpoint': '触发时点', 'status': '🚨已触发', 'user_action': '待填', 'final_result': ''},
            ...
        ],
        'final_result': '',   # 未 finalize 前为空；盘中已填终态（如 已过期）则保留
    }
    节不存在或空 → 返回 []。
    """
    header, rows = _parse_table_rows(md_text, _P0_SECTION)
    if not header:
        return []

    c_id = _col(header, '信号ID')
    c_name = _col(header, '标的')
    c_op = _col(header, '操作类型')
    c_trigger = _col(header, '触发时间')
    c_ckpt = _col(header, '检查点')
    c_status = _col(header, '响应状态')
    c_action = _col(header, '用户操作')
    c_final = _col(header, '最终结果')

    if c_id < 0:
        return []

    by_id: dict[str, dict] = {}
    for row in rows:
        def g(idx):
            return row[idx] if 0 <= idx < len(row) else ''

        signal_id = g(c_id)
        if not signal_id.startswith('SIG-'):
            continue

        rec = by_id.setdefault(signal_id, {
            'signal_id': signal_id,
            'name': g(c_name),
            'op_type': g(c_op),
            'trigger_time': g(c_trigger),
            'checkpoints': [],
            'final_result': '',
        })
        # 首次出现时填充名称/操作/触发时间（后续行保持一致）
        if not rec['name']:
            rec['name'] = g(c_name)
        if not rec['op_type']:
            rec['op_type'] = g(c_op)
        if not rec['trigger_time']:
            rec['trigger_time'] = g(c_trigger)
        # 盘中已直接填真实终态（非占位 '—'）→ 记录到 rec.final_result
        cell_final = g(c_final)
        if cell_final and cell_final != _PLACEHOLDER:
            rec['final_result'] = cell_final

        rec['checkpoints'].append({
            'checkpoint': g(c_ckpt) or f'检查点{len(rec["checkpoints"]) + 1}',
            'status': g(c_status),
            'user_action': g(c_action),
            'final_result': '' if cell_final == _PLACEHOLDER else cell_final,
        })

    return list(by_id.values())


# ============================================================
# 最终结果判定（零容忍，不做结果论豁免）
# ============================================================

def finalize_p0_result(p0_signals: list[dict]) -> list[dict]:
    """为每条 P0 记录确定最终结果（不变更原对象，返回新列表）。

    判定规则（优先级从上到下，任一满足即止）：
      1. 已存在最终结果（如盘中标 '已过期'）→ 保留
      2. 任一检查点 用户操作 ∈ {已执行, 部分执行} → '已执行'
      3. 任一检查点 用户操作 == '放弃' → '未执行（放弃）'（显式放弃为合法终态）
      4. 其余（含全程 待填 / 错过）→ '未执行（错过）'（触发必须执行或显式放弃，否则问责）
    """
    import copy
    result = copy.deepcopy(p0_signals)
    for rec in result:
        # 已定真实终态（盘中已填 已过期 等，占位 '—' 不算）→ 保留
        if rec.get('final_result') and rec.get('final_result') != _PLACEHOLDER:
            continue

        actions = {cp.get('user_action', '').strip() for cp in rec.get('checkpoints', [])}
        if actions & _EXECUTED_ACTIONS:
            rec['final_result'] = _EXECUTED_FINAL
        elif actions & _ABANDONED_ACTIONS:
            rec['final_result'] = '未执行（放弃）'
        else:
            rec['final_result'] = '未执行（错过）'
    return result


# ============================================================
# P0 执行率
# ============================================================

def calc_p0_execution_rate(p0_signals: list[dict]) -> dict:
    """P0 执行率 = 已执行 P0 / 已触发 P0（百分比，保留 1 位小数）。

    返回:
        {'triggered': int, 'executed': int, 'rate': float|None, 'unexecuted_ids': [str]}
    - triggered = 已触发 P0 数（本模块只追踪已触发 P0，故 = len(p0_signals)）
    - executed  = 最终结果为 '已执行' 的 P0 数
    - rate      = executed/triggered*100；triggered==0 → None
    """
    finalized = finalize_p0_result(p0_signals)
    triggered = len(finalized)
    executed = sum(1 for r in finalized if r.get('final_result') == _EXECUTED_FINAL)
    unexecuted = [r['signal_id'] for r in finalized if r.get('final_result') != _EXECUTED_FINAL]
    rate = round(executed / triggered * 100, 1) if triggered else None
    return {
        'triggered': triggered,
        'executed': executed,
        'rate': rate,
        'unexecuted_ids': unexecuted,
    }


# ============================================================
# 跨日 store 合并（幂等）
# ============================================================

def merge_p0_daily(store: dict, date: str, summary: dict) -> dict:
    """将当日 P0 执行摘要并入跨日 store（store['daily'][date] = summary）。

    幂等：同日重复写入覆盖而非累积。返回更新后的 store（不写磁盘）。
    """
    store.setdefault('daily', {})
    store['daily'][date] = dict(summary)
    store['_updated'] = date
    return store


# ============================================================
# 连续 2 日 <100% → P1 级告警
# ============================================================

def check_p0_alert(store: dict) -> dict:
    """P0 执行率连续 2 日 <100% → P1 级告警。

    只看 daily 中 rate 非 None 的条目（有 P0 触发的交易日），按日期升序扫描连续 <100% 的 run。
    - rate >= 100 或 rate=None（当日无 P0 触发）中断该 run。
    - 返回 {'alert': bool, 'streak': int, 'message': str}
      streak = 最近连续 <100% 的天数（全局最大 run，告警用最近一段即可：取末尾 run）。
    """
    daily = store.get('daily', {})
    entries = sorted(
        ((d, s.get('rate')) for d, s in daily.items() if s.get('rate') is not None),
        key=lambda x: x[0],
    )

    streak = 0
    max_streak = 0
    for _date, rate in entries:
        if rate < 100:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    # 末尾 run 才是"最近连续"（从最后一天往前连续 <100% 的天数）
    trailing_streak = 0
    for _date, rate in reversed(entries):
        if rate < 100:
            trailing_streak += 1
        else:
            break

    alert = trailing_streak >= 2
    if alert:
        message = (
            f"🚨 P1 告警：P0 执行率连续 {trailing_streak} 日 <100%（零容忍，不做结果论豁免）"
            f"——请人工确认 P0 执行缺失根因并强化执行纪律"
        )
    elif trailing_streak == 1:
        message = "⚠️ P0 执行率 <100%（1 日），连续 2 日将触发 P1 告警"
    else:
        message = "✅ P0 执行率 100%（或当日无 P0 触发）"

    return {'alert': alert, 'streak': trailing_streak, 'max_streak': max_streak, 'message': message}
