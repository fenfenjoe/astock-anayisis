/**
 * astock-trade-entry — ledger 核心模块（纯函数，无 IO）
 *
 * 唯一权威数据源：`my_doc/每日复盘/每日调仓.md`
 *   - §0 可用金额
 *   - §1 当前持仓（表）
 *   - §2 调仓记录（表）
 * 同步快照：`my_doc/每日复盘/harness/config/持仓.md`
 *
 * 所有"录入交易 → 更新持仓/可用金额"的计算与序列化都收敛在本模块，
 * 保证界面录入与每日复盘（任务 4.5 同步）读取的是同一份、同一口径的数据。
 *
 * 口径（与券商软件一致）：
 *   - 买入加仓：新成本 = (旧量×旧成本 + 新量×成交价) / 新量（移动平均成本）
 *   - 卖出：数量减少、成本价不变；清仓则移除该行
 *   - 可用金额：买入扣减、卖出回补；当日 T+0 做T 按顺序逐腿结算
 *   - T+1：A股/场内权益 ETF 当日买入份额当日不可卖出（跨境/债券 ETF 除外，见 isT0）
 */

export const DAILY_LEDGER_REL = ['my_doc', '每日复盘', '每日调仓.md'];
export const POSITIONS_REL = ['my_doc', '每日复盘', 'harness', 'config', '持仓.md'];

/** 当日买入的份额是否可当日卖出（T+0 品种白名单，A股/场内权益 ETF 默认 T+1） */
export function isT0(code) {
  // 跨境 ETF 与债券 ETF 支持 T+0：513/159 跨境、511 债券、501/502 债基等
  const c = String(code);
  return /^51[13]/.test(c) || /^159/.test(c) || /^511/.test(c) || /^501/.test(c) || /^502/.test(c);
}

/** 数字解析：去掉千分位/空格/元等，返回数字；空串/非数字返回 NaN */
export function parseNumber(raw) {
  if (typeof raw === 'number') return raw;
  const text = String(raw ?? '').replace(/[,，\s元%]/g, '').trim();
  if (!text) return NaN;
  const n = Number(text);
  return Number.isFinite(n) ? n : NaN;
}

/** 千分位格式化整数（1,400） */
export function formatQty(qty) {
  return String(Math.round(qty)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

/** 价格格式化：最多 3 位小数、去尾零（1.684 / 2.731 / 9.05 / 33.563） */
export function formatPrice(price) {
  const n = Math.round(Number(price) * 1000) / 1000;
  return String(n);
}

/** 可用金额格式化：保留 2 位小数、去尾零 */
export function formatCash(cash) {
  const n = Math.round((Number(cash) + Number.EPSILON) * 100) / 100;
  return String(n);
}

/** 解析每日调仓.md → { cash, positions: Map<code,{name,code,qty,cost}>, trades: [] } */
export function parseDailyLedger(text) {
  const lines = String(text).replace(/\r\n/g, '\n').split('\n');
  let section = null;
  let cash = NaN;
  const positions = new Map();
  const trades = [];
  for (const raw of lines) {
    const line = raw.trim();
    if (/^##\s+0\./.test(line)) { section = 'cash'; continue; }
    if (/^##\s+1\./.test(line)) { section = 'positions'; continue; }
    if (/^##\s+2\./.test(line)) { section = 'trades'; continue; }
    if (section === 'cash') {
      if (cash === null || Number.isNaN(cash)) {
        const n = parseNumber(line);
        if (Number.isFinite(n)) cash = n;
      }
      continue;
    }
    if (section === 'positions') {
      const parts = line.split('|').map((p) => p.trim());
      // | 股票名称 | 代码 | 持仓量（份） | 成本价（元） |
      // split 后：['', 名称, 代码, 数量, 成本, '']
      if (parts.length >= 5 && /^\d{6}$/.test(parts[2]) && parts[2].length === 6) {
        const qty = parseNumber(parts[3]);
        const cost = parseNumber(parts[4]);
        if (Number.isFinite(qty) && Number.isFinite(cost)) {
          positions.set(parts[2], { name: parts[1], code: parts[2], qty, cost });
        }
      }
      continue;
    }
    if (section === 'trades') {
      const parts = line.split('|').map((p) => p.trim());
      // | 日期 | 股票名称 | 股票代码 | 交易数量 | 交易价格 | 买入/卖出 | 备注 |
      // split 后：['', 日期, 名称, 代码, 数量, 价格, 方向, 备注, '']
      if (parts.length >= 8 && /^\d{4}-\d{2}-\d{2}$/.test(parts[1]) && /^\d{6}$/.test(parts[3])) {
        const qty = parseNumber(parts[4]);
        const price = parseNumber(parts[5]);
        if (Number.isFinite(qty) && Number.isFinite(price)) {
          trades.push({
            date: parts[1], name: parts[2], code: parts[3], qty, price,
            side: parts[6] === '卖出' ? '卖出' : '买入',
            note: parts[7] ?? '',
          });
        }
      }
      continue;
    }
  }
  return { cash, positions, trades };
}

/** 解析 config/持仓.md → { cash, positions: Map<code,{name,code,qty,cost}> } */
export function parsePositionsConfig(text) {
  const lines = String(text).replace(/\r\n/g, '\n').split('\n');
  let cash = NaN;
  const positions = new Map();
  for (const raw of lines) {
    const line = raw.trim();
    if (/^可用金额\s*:/.test(line)) {
      const n = parseNumber(line.replace(/^可用金额\s*:\s*/, ''));
      if (Number.isFinite(n)) cash = n;
      continue;
    }
    const parts = line.split('|').map((p) => p.trim());
    if (parts.length >= 5 && /^\d{6}$/.test(parts[2]) && parts[2].length === 6) {
      const qty = parseNumber(parts[3]);
      const cost = parseNumber(parts[4]);
      if (Number.isFinite(qty) && Number.isFinite(cost)) {
        positions.set(parts[2], { name: parts[1], code: parts[2], qty, cost });
      }
    }
  }
  return { cash, positions };
}

/** 序列化每日调仓.md（保持骨架与现有格式一致） */
export function serializeDailyLedger({ cash, positions, trades }) {
  const rows = [...positions.values()].sort((a, b) => a.code.localeCompare(b.code)).map((p) =>
    `| ${p.name} | ${p.code} | ${formatQty(p.qty)} | ${formatPrice(p.cost)} | `);
  const tradeRows = trades.map((t) =>
    `| ${t.date} | ${t.name} | ${t.code} | ${formatQty(t.qty)} | ${formatPrice(t.price)} | ${t.side} | ${t.note ?? ''} |`);
  return [
    '# 仓位',
    '',
    '## 0. 可用金额',
    '',
    formatCash(cash),
    '',
    '## 1. 当前持仓',
    '',
    '',
    '持仓：',
    '',
    '| 股票名称 | 代码 | 持仓量（份） | 成本价（元） | ',
    '| -------- | ------ | ------------ | ------------ | ',
    ...rows,
    '',
    '## 2. 调仓记录',
    '',
    '',
    '| 日期 | 股票名称 | 股票代码 | 交易数量 | 交易价格 | 买入/卖出 | 备注 |',
    '|---|---|---|---|---|---|---|',
    ...tradeRows,
    '',
  ].join('\n');
}

/** 序列化 config/持仓.md（保持与现有格式一致） */
export function serializePositionsConfig({ cash, positions }) {
  const rows = [...positions.values()].sort((a, b) => a.code.localeCompare(b.code)).map((p) =>
    `| ${p.name} | ${p.code} | ${formatQty(p.qty)} | ${formatPrice(p.cost)} |`);
  return [
    '# 当前持仓',
    '',
    '> 本文件由每日复盘自动同步自 每日调仓.md，反映最新持仓状态。',
    '> 最后更新: 自动同步',
    `可用金额: ${formatCash(cash)} 元`,
    '',
    '| 股票名称 | 代码 | 持仓数量（份） | 成本价（元） |',
    '| -------- | ------ | -------------- | ------------ |',
    ...rows,
    '',
  ].join('\n');
}

/**
 * 校验一笔交易（不修改状态）。
 * @returns {{ok:true}|{ok:false, error:string}}
 */
export function validateTrade(state, trade, { allowOverdraft = false } = {}) {
  const { date, name, code, qty, price, side } = trade;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date ?? '')) return { ok: false, error: `日期格式应为 YYYY-MM-DD，收到 "${date}"` };
  if (!/^\d{6}$/.test(code ?? '')) return { ok: false, error: `股票代码应为 6 位数字，收到 "${code}"` };
  if (!Number.isInteger(qty) || qty <= 0) return { ok: false, error: `交易数量必须为正整数，收到 ${qty}` };
  if (!Number.isFinite(price) || price <= 0) return { ok: false, error: `交易价格必须为正数，收到 ${price}` };
  if (!name || typeof name !== 'string') return { ok: false, error: '股票名称不能为空' };
  if (side !== '买入' && side !== '卖出') return { ok: false, error: `操作方向必须为 买入/卖出，收到 "${side}"` };

  const pos = state.positions.get(code);
  if (side === '卖出') {
    if (!pos) return { ok: false, error: `卖出失败：当前无 ${name}(${code}) 持仓` };
    if (pos.name !== name) return { ok: false, error: `卖出失败：代码 ${code} 的名称应为 "${pos.name}"，与 "${name}" 不一致` };
    if (qty > pos.qty) return { ok: false, error: `卖出失败：${name}(${code}) 仅持有 ${formatQty(pos.qty)} 份，无法卖出 ${formatQty(qty)} 份` };
    if (!isT0(code)) {
      // T+1：当日买入的份额当日不可卖出
      const todayBuys = state.trades
        .filter((t) => t.code === code && t.date === date && t.side === '买入')
        .reduce((sum, t) => sum + t.qty, 0);
      const sellable = pos.qty - todayBuys;
      if (qty > sellable) {
        return {
          ok: false,
          error: `卖出失败：${name}(${code}) 当日买入 ${formatQty(todayBuys)} 份，按 T+1 规则当日不可卖出；今日可卖 ${formatQty(Math.max(0, sellable))} 份`,
        };
      }
    }
  } else {
    const amount = qty * price;
    if (!allowOverdraft && amount > state.cash + 1e-6) {
      return { ok: false, error: `买入失败：成交金额 ${formatCash(amount)} 元 超出可用金额 ${formatCash(state.cash)} 元` };
    }
  }
  return { ok: true };
}

/**
 * 应用一笔交易，返回新状态（不可变）。
 */
export function applyTrade(state, trade) {
  const { code, name, qty, price, side } = trade;
  const positions = new Map(state.positions);
  if (side === '买入') {
    const prev = positions.get(code) ?? { name, code, qty: 0, cost: 0 };
    const newQty = prev.qty + qty;
    const newCost = (prev.qty * prev.cost + qty * price) / newQty;
    positions.set(code, { name, code, qty: newQty, cost: Math.round(newCost * 10000) / 10000 });
    return {
      cash: Math.round((state.cash - qty * price) * 100) / 100,
      positions,
      trades: [...state.trades, { ...trade, qty, price }],
    };
  }
  // 卖出
  const prev = positions.get(code);
  const remaining = prev.qty - qty;
  if (remaining <= 0) positions.delete(code);
  else positions.set(code, { ...prev, qty: remaining });
  return {
    cash: Math.round((state.cash + qty * price) * 100) / 100,
    positions,
    trades: [...state.trades, { ...trade, qty, price }],
  };
}

/** 从两个文件文本构建状态（权威=每日调仓.md，持仓.md 作为兜底） */
export function buildState(dailyText, positionsText) {
  const daily = parseDailyLedger(dailyText);
  const positions = daily.positions.size > 0 ? daily.positions : parsePositionsConfig(positionsText).positions;
  const cash = Number.isFinite(daily.cash) ? daily.cash : parsePositionsConfig(positionsText).cash;
  return { cash, positions, trades: daily.trades };
}

/** 便捷：按代码取名称 */
export function nameOf(positions, code) {
  return positions.get(code)?.name ?? '';
}
