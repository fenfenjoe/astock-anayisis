import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  parseDailyLedger, parsePositionsConfig,
  serializeDailyLedger, serializePositionsConfig,
  buildState, validateTrade, applyTrade,
  parseNumber, formatQty, formatPrice, formatCash, isT0,
} from './ledger.mjs';

const DAILY = `# 仓位

## 0. 可用金额

16131

## 1. 当前持仓


持仓：

| 股票名称 | 代码 | 持仓量（份） | 成本价（元） | 
| -------- | ------ | ------------ | ------------ | 
| 航空航天ETF | 159227 | 1,400 | 2.731 | 
| 半导体ETF | 512480 | 6,100 | 1.044 | 

## 2. 调仓记录


| 日期 | 股票名称 | 股票代码 | 交易数量 | 交易价格 | 买入/卖出 | 备注 |
|---|---|---|---|---|---|---|
| 2026-08-27 | 半导体ETF | 512480 | 6,100 | 1.044 | 买入 | 买入信号，目标价1.058  |
| 2026-08-27 | 电网设备ETF | 159326 | 1,900 | 1.695 | 卖出 | 正T卖出  |
`;

const POSITIONS = `# 当前持仓

> 本文件由每日复盘自动同步自 每日调仓.md，反映最新持仓状态。
> 最后更新: 自动同步
可用金额: 16131 元

| 股票名称 | 代码 | 持仓数量（份） | 成本价（元） |
| -------- | ------ | -------------- | ------------ |
| 航空航天ETF | 159227 | 1,400 | 2.731 |
| 半导体ETF | 512480 | 6,100 | 1.044 |
`;

function baseState() {
  return buildState(DAILY, POSITIONS);
}

test('解析：可用金额/持仓/调仓记录', () => {
  const st = baseState();
  assert.equal(st.cash, 16131);
  assert.equal(st.positions.size, 2);
  assert.equal(st.positions.get('512480').qty, 6100);
  assert.equal(st.positions.get('512480').cost, 1.044);
  assert.equal(st.trades.length, 2);
  assert.equal(st.trades[0].side, '买入');
});

test('序列化 round-trip：cash/positions/trades 保持一致', () => {
  const st = baseState();
  const st2 = buildState(serializeDailyLedger(st), serializePositionsConfig(st));
  assert.equal(st2.cash, st.cash);
  assert.equal(st2.positions.size, st.positions.size);
  assert.equal(st2.positions.get('512480').qty, st.positions.get('512480').qty);
  assert.equal(st2.trades.length, st.trades.length);
  assert.deepEqual(st2.trades[0], st.trades[0]);
});

test('买入加仓：移动平均成本 + 可用金额扣减', () => {
  const st = baseState();
  const n = applyTrade(st, { date: '2026-08-28', name: '半导体ETF', code: '512480', qty: 1000, price: 1.10, side: '买入' });
  const p = n.positions.get('512480');
  assert.equal(p.qty, 7100);
  // 成本内部保留 4 位小数：(6100*1.044 + 1000*1.10)/7100 ≈ 1.0519
  assert.ok(Math.abs(p.cost - (6100 * 1.044 + 1000 * 1.10) / 7100) < 5e-5);
  assert.ok(Math.abs(n.cash - (16131 - 1100)) < 1e-6);
});

test('卖出：数量减少、成本不变、资金回补；清仓移除', () => {
  const st = baseState();
  const n = applyTrade(st, { date: '2026-08-28', name: '半导体ETF', code: '512480', qty: 3000, price: 1.07, side: '卖出' });
  const p = n.positions.get('512480');
  assert.equal(p.qty, 3100);
  assert.equal(p.cost, 1.044);
  assert.ok(Math.abs(n.cash - (16131 + 3000 * 1.07)) < 1e-6);
  const cleared = applyTrade(st, { date: '2026-08-28', name: '半导体ETF', code: '512480', qty: 6100, price: 1.07, side: '卖出' });
  assert.equal(cleared.positions.has('512480'), false);
});

test('校验：卖出超持仓 / 名称-代码不一致 / 数量非正整数 / 可用金额不足', () => {
  const st = baseState();
  assert.equal(validateTrade(st, { date: '2026-08-28', name: '半导体ETF', code: '512480', qty: 99999, price: 1.1, side: '卖出' }).ok, false);
  assert.equal(validateTrade(st, { date: '2026-08-28', name: '恒生科技ETF', code: '512480', qty: 100, price: 1.1, side: '卖出' }).ok, false);
  assert.equal(validateTrade(st, { date: '2026-08-28', name: '半导体ETF', code: '512480', qty: 100.5, price: 1.1, side: '买入' }).ok, false);
  assert.equal(validateTrade(st, { date: '2026-08-28', name: '半导体ETF', code: '512480', qty: 100000, price: 1.1, side: '买入' }).ok, false);
});

test('T+1：当日买入份额当日不可卖出（权益 ETF）', () => {
  const st = baseState();
  const t1 = applyTrade(st, { date: '2026-08-28', name: '半导体ETF', code: '512480', qty: 1000, price: 1.10, side: '买入' });
  // 卖 6200 > 原持仓 6100：超出的 1000 是当日买入，拦截
  const chk = validateTrade(t1, { date: '2026-08-28', name: '半导体ETF', code: '512480', qty: 6200, price: 1.11, side: '卖出' });
  assert.equal(chk.ok, false);
  assert.match(chk.error, /T\+1/);
  // 卖 2000 ≤ 原持仓 6100：合法（卖的是昨日持仓）
  assert.equal(validateTrade(t1, { date: '2026-08-28', name: '半导体ETF', code: '512480', qty: 2000, price: 1.11, side: '卖出' }).ok, true);
});

test('T+0 品种（跨境/债券）：当日买入可当日卖出', () => {
  assert.equal(isT0('513100'), true);
  assert.equal(isT0('511010'), true);
  assert.equal(isT0('512480'), false);
  const st = baseState();
  const t1 = applyTrade(st, { date: '2026-08-28', name: '纳指ETF', code: '513100', qty: 1000, price: 2.30, side: '买入' });
  assert.equal(validateTrade(t1, { date: '2026-08-28', name: '纳指ETF', code: '513100', qty: 1000, price: 2.31, side: '卖出' }).ok, true);
});

test('反T（先卖后买）：持仓净不变、资金 = 价差×数量、成本按移动平均重算', () => {
  const st = baseState();
  const sellN = applyTrade(st, { date: '2026-08-28', name: '半导体ETF', code: '512480', qty: 3000, price: 1.07, side: '卖出' });
  const buyN = applyTrade(sellN, { date: '2026-08-28', name: '半导体ETF', code: '512480', qty: 3000, price: 1.03, side: '买入' });
  assert.equal(buyN.positions.get('512480').qty, 6100);
  // 买回价 1.03 < 原成本 1.044 → 成本应下降：(3100*1.044 + 3000*1.03)/6100 ≈ 1.0371
  assert.ok(Math.abs(buyN.positions.get('512480').cost - (3100 * 1.044 + 3000 * 1.03) / 6100) < 5e-5);
  assert.ok(Math.abs(buyN.cash - (st.cash + 3000 * (1.07 - 1.03))) < 1e-6);
});

test('格式化辅助函数', () => {
  assert.equal(parseNumber('1,400'), 1400);
  assert.equal(parseNumber(''), NaN);
  assert.equal(formatQty(6100), '6,100');
  assert.equal(formatPrice(1.044), '1.044');
  assert.equal(formatPrice(9.05), '9.05');
  assert.equal(formatCash(16131), '16131');
  assert.equal(formatCash(16131.5), '16131.5');
});

test('config/持仓.md 解析', () => {
  const { cash, positions } = parsePositionsConfig(POSITIONS);
  assert.equal(cash, 16131);
  assert.equal(positions.get('512480').qty, 6100);
});
