/**
 * 每日复盘集成视图 — 持仓/资产、每日信号、报告、定时任务
 *
 * 依赖 dashboard.js 的全局工具（apiGet/apiPost/toast/$el/safeSetHTML/escapeHtml 在本文件定义）、
 * auth.js 的 Auth（getHeaders/fetchGet/fetchPost）。在 dashboard.html 中于 dashboard.js 之后加载。
 *
 * 视图切换：HTML 中 <nav class="topnav"> 的按钮调用 switchView(viewId)，
 * 各视图懒初始化（首次进入时加载），再次进入刷新以展示最新报告/运行日志。
 */
'use strict';

// ── 通用：PUT + markdown 渲染 ──
async function apiPut(path, body) {
  const res = await fetch(path, {
    method: 'PUT',
    headers: Auth.getHeaders(),
    body: JSON.stringify(body || {}),
  });
  if (res.status === 401) { showLoginPage(); throw new Error('认证已过期，请重新登录'); }
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`API ${res.status}: ${txt.slice(0, 200)}`);
  }
  return res.json();
}

function escapeHtml(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function renderMarkdown(md) {
  if (!md) return '<p class="muted">（空）</p>';
  if (typeof marked !== 'undefined' && marked.parse) {
    try { return '<div class="md-body">' + marked.parse(md) + '</div>'; } catch (e) { /* fall through to plain */ }
  }
  // 无 marked 时的纯文本兜底
  return '<pre class="md-plain">' + escapeHtml(md) + '</pre>';
}

function fmtMoney(v) {
  if (v === null || v === undefined || v === '—') return '—';
  const n = parseFloat(v);
  if (isNaN(n)) return '—';
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// ── 视图切换（懒初始化）──
const _viewInit = {};

function switchView(viewId) {
  document.querySelectorAll('.view').forEach((v) => {
    v.classList.toggle('view-active', v.id === viewId);
  });
  document.querySelectorAll('.topnav-item').forEach((b) => {
    b.classList.toggle('topnav-active', b.getAttribute('data-view') === viewId);
  });
  // 持仓只在首次进入加载（避免覆盖用户未保存的编辑）；
  // 信号/报告/调度每次进入都刷新（这些内容会随时间新增）。
  if (viewId === 'view-portfolio' && !_viewInit.portfolio) { _viewInit.portfolio = true; pfLoad(); }
  if (viewId === 'view-signals') { _viewInit.signals = true; sigLoad(true); sigqLoad('day'); }
  if (viewId === 'view-reports') { _viewInit.reports = true; repLoad(true); }
  if (viewId === 'view-scheduler') { _viewInit.scheduler = true; schedLoad(true); }
  if (viewId === 'view-agent') { _viewInit.agent = true; Agent.load(true); }
}


// ═══════════════════════════════════════════════════════════════
// 持仓 / 资产
// ═══════════════════════════════════════════════════════════════

let pfData = null;   // 最近一次 /api/portfolio 响应

function pfRenderSummary() {
  const val = pfData && pfData.valuation;
  const t = val ? val.totals : null;
  safeSetText('pf-total-assets', t && t.total_assets != null ? fmtMoney(t.total_assets) : '—');
  safeSetText('pf-mkt-value', t && t.mkt_value != null ? fmtMoney(t.mkt_value) : '—');
  safeSetText('pf-cost-value', t && t.cost_value != null ? fmtMoney(t.cost_value) : '—');
  const pnl = t ? t.pnl : null;
  safeSetText('pf-pnl', pnl != null ? fmtMoney(pnl) : '—');
  safeSetText('pf-pnl-sub', (t && t.pnl_pct != null ? t.pnl_pct.toFixed(2) : '—') + '%');
  const meta = pfData ? pfData.meta : {};
  safeSetText('pf-refreshed-at', meta.last_refresh_at ? '刷新于 ' + meta.last_refresh_at : '');
  safeSetText('pf-account-source', '数据源: ' + ((meta.account_source || 'manual') === 'eastmoney' ? '东财自动' : '手动配置'));
  // 可用现金输入框：始终同步服务器值（除非用户正在编辑）——录入交易后自动刷新扣款结果，
  // 避免旧值残留导致"保存"把过期的现金写回去。
  const cashInput = $el('pf-cash');
  if (cashInput && document.activeElement !== cashInput) {
    const want = meta.available_cash != null ? String(meta.available_cash) : '';
    cashInput.value = want;
  }
}

function pfRenderTable() {
  const tbody = $el('pf-tbody');
  if (!tbody) return;
  const holdings = pfData ? pfData.holdings : [];
  const rows = pfData && pfData.valuation ? pfData.valuation.rows : [];
  const byCode = {};
  rows.forEach((r) => { byCode[r.code] = r; });

  if (!holdings.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="loading-cell">暂无持仓，点击「添加持仓」开始</td></tr>';
    return;
  }
  tbody.innerHTML = holdings.map((h) => {
    const v = byCode[h.code] || {};
    const pnl = v.pnl != null ? fmtMoney(v.pnl) : '—';
    const pnlCls = v.pnl != null ? (v.pnl >= 0 ? 'num-positive' : 'num-danger') : '';
    const pct = v.pnl_pct != null ? v.pnl_pct.toFixed(2) + '%' : '—';
    return `<tr data-code="${escapeHtml(h.code)}">
      <td class="col-name"><input class="pf-inp pf-name" value="${escapeHtml(h.name || '')}" placeholder="名称"></td>
      <td class="col-num"><input class="pf-inp pf-code" value="${escapeHtml(h.code)}" placeholder="6位代码"></td>
      <td class="col-num"><input class="pf-inp pf-shares" type="number" step="1" min="0" value="${escapeHtml(h.shares)}"></td>
      <td class="col-num"><input class="pf-inp pf-cost" type="number" step="0.001" min="0" value="${h.cost_price != null ? h.cost_price : ''}"></td>
      <td class="col-num">${v.close != null ? v.close : '—'}</td>
      <td class="col-num">${v.mkt_value != null ? fmtMoney(v.mkt_value) : '—'}</td>
      <td class="col-num ${pnlCls}">${pnl}</td>
      <td class="col-num ${pnlCls}">${pct}</td>
      <td class="col-act">
        <button class="btn-icon-only" onclick="pfTradeFill('${escapeHtml(h.code)}', '${escapeHtml(h.name || '')}')" title="记一笔（填入交易表单）">💰</button>
        <button class="btn-icon-only" onclick="pfDelRow(this)" title="删除">✕</button>
      </td>
    </tr>`;
  }).join('');
}

async function pfLoad() {
  try {
    pfData = await apiGet('/api/portfolio');
    pfRenderSummary();
    pfRenderTable();
    pfTradeInit();
    emLoad();
  } catch (e) {
    toast('加载持仓失败: ' + e.message, 'error');
  }
}

function pfAddRow() {
  const tbody = $el('pf-tbody');
  if (!tbody) return;
  if (tbody.querySelector('.loading-cell')) tbody.innerHTML = '';
  const tr = document.createElement('tr');
  tr.innerHTML = `<td class="col-name"><input class="pf-inp pf-name" placeholder="名称"></td>
    <td class="col-num"><input class="pf-inp pf-code" placeholder="6位代码"></td>
    <td class="col-num"><input class="pf-inp pf-shares" type="number" step="1" min="0" placeholder="0"></td>
    <td class="col-num"><input class="pf-inp pf-cost" type="number" step="0.001" min="0" placeholder="0"></td>
    <td class="col-num">—</td><td class="col-num">—</td><td class="col-num">—</td><td class="col-num">—</td>
    <td class="col-act"><button class="btn-icon-only" onclick="pfDelRow(this)" title="删除">✕</button></td>`;
  tbody.appendChild(tr);
}

function pfDelRow(btn) {
  const tr = btn.closest('tr');
  if (tr) tr.remove();
}

async function pfSave() {
  const tbody = $el('pf-tbody');
  if (!tbody) return;
  const rows = [];
  tbody.querySelectorAll('tr[data-code], tr:not([data-code])').forEach((tr) => {
    const code = (tr.querySelector('.pf-code')?.value || '').trim();
    if (!code) return;
    const shares = parseFloat(tr.querySelector('.pf-shares')?.value) || 0;
    const costStr = (tr.querySelector('.pf-cost')?.value || '').trim();
    rows.push({
      code: code,
      name: (tr.querySelector('.pf-name')?.value || '').trim(),
      shares: shares,
      cost_price: costStr === '' ? null : parseFloat(costStr),
    });
  });
  if (!rows.length) { toast('没有可保存的持仓行', 'error'); return; }
  const cash = parseFloat($el('pf-cash')?.value);
  try {
    pfData = await apiPut('/api/portfolio/holdings', {
      rows: rows,
      available_cash: isNaN(cash) ? null : cash,
    });
    pfRenderSummary();
    pfRenderTable();
    toast('持仓已保存，并同步到 持仓.md', 'success');
  } catch (e) {
    toast('保存失败: ' + e.message, 'error');
  }
}

async function pfRefreshValuation() {
  try {
    await apiPost('/api/portfolio/refresh', {});
    toast('市值刷新已启动（后台同步行情）', 'success');
    setTimeout(async () => {
      try {
        pfData = await apiGet('/api/portfolio');
        pfRenderSummary();
        pfRenderTable();
        toast('市值已刷新', 'success');
      } catch (e) { /* ignore */ }
    }, 8000);
  } catch (e) {
    toast('刷新失败: ' + e.message, 'error');
  }
}


// ═══════════════════════════════════════════════════════════════
// 交易录入（每日调仓.md §2 调仓记录 + 自动重算持仓）
// ═══════════════════════════════════════════════════════════════

function pfTodayStr() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function pfTradeInit() {
  // 日期默认今天（只在为空时填）
  const dateEl = $el('pf-trade-date');
  if (dateEl && !dateEl.value) dateEl.value = pfTodayStr();
  // datalist 用当前持仓填充（名称/代码快速选择）
  const list = $el('pf-code-list');
  if (list && pfData && pfData.holdings) {
    list.innerHTML = pfData.holdings.map((h) =>
      `<option value="${escapeHtml(h.code)}">${escapeHtml(h.name)}（${escapeHtml(h.code)}）</option>`).join('');
  }
  pfTradeRender();
}

function pfTradeRender() {
  const tbody = $el('pf-trades-tbody');
  if (!tbody) return;
  const trades = (pfData && pfData.trades) || [];
  if (!trades.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="loading-cell">暂无调仓记录</td></tr>';
    return;
  }
  tbody.innerHTML = trades.map((t) => {
    const sideCls = t.side === '卖出' ? 'sell' : 'buy';
    const tag = `<span class="pf-trade-tag ${sideCls}">${escapeHtml(t.side)}</span>`;
    return `<tr>
      <td class="col-num">${escapeHtml(t.trade_date)}</td>
      <td class="col-name">${escapeHtml(t.name)}</td>
      <td class="col-num">${escapeHtml(t.code)}</td>
      <td class="col-num">${escapeHtml(String(t.quantity).replace(/\B(?=(\d{3})+(?!\d))/g, ','))}</td>
      <td class="col-num">${escapeHtml(String(t.price))}</td>
      <td class="col-num">${tag}</td>
      <td class="col-name pf-trade-remark-cell" title="${escapeHtml(t.remark || '')}">${escapeHtml(t.remark || '')}</td>
    </tr>`;
  }).join('');
}

function pfTradeFill(code, name) {
  const codeEl = $el('pf-trade-code');
  const nameEl = $el('pf-trade-name');
  if (codeEl) codeEl.value = code || '';
  if (nameEl) nameEl.value = name || '';
  const el = $el('view-portfolio');
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  if (codeEl) codeEl.focus();
  pfEstimateFee();
}

// ── 手续费预估（佣金万2.5/最低5元 + 股票卖出印花税0.05%，过户费忽略）──
const FEE_COMMISSION_RATE = 0.00025;   // 佣金 万2.5（可自行改）
const FEE_MIN = 5;                      // 最低佣金 5 元
const FEE_STAMP_RATE = 0.0005;          // 印花税 0.05%（仅股票卖出）

function pfEstimateFee() {
  const code = ($el('pf-trade-code')?.value || '').trim();
  const side = $el('pf-trade-side')?.value || '买入';
  const qty = parseFloat($el('pf-trade-qty')?.value);
  const price = parseFloat($el('pf-trade-price')?.value);
  const feeEl = $el('pf-trade-fee');
  const estEl = $el('pf-trade-fee-est');
  if (!feeEl || !(qty > 0) || !(price > 0)) {
    if (estEl) estEl.textContent = '';
    return;
  }
  const amount = qty * price;
  const isStock = /^(60|68|00|30)/.test(code);
  const commission = Math.max(amount * FEE_COMMISSION_RATE, FEE_MIN);
  const stamp = (side === '卖出' && isStock) ? amount * FEE_STAMP_RATE : 0;
  const est = Math.round((commission + stamp) * 100) / 100;
  const parts = [];
  parts.push('佣金' + (Math.max(amount * FEE_COMMISSION_RATE, FEE_MIN) >= FEE_MIN ? '(最低5元)' : ''));
  if (stamp > 0) parts.push('印花税' + stamp.toFixed(2));
  if (estEl) estEl.textContent = '≈' + est.toFixed(2) + '元';
  // 只在输入框为空或等于上次预估时自动填入（用户手改后不覆盖）
  const cur = feeEl.value;
  if (cur === '' || parseFloat(cur) === pfEstimateFee._last) {
    feeEl.value = est > 0 ? est.toFixed(2) : '';
  }
  pfEstimateFee._last = est;
}

async function pfTradeSubmit() {
  const date = ($el('pf-trade-date')?.value || '').trim();
  const name = ($el('pf-trade-name')?.value || '').trim();
  const code = ($el('pf-trade-code')?.value || '').trim();
  const side = $el('pf-trade-side')?.value || '买入';
  const qty = parseFloat($el('pf-trade-qty')?.value);
  const price = parseFloat($el('pf-trade-price')?.value);
  const fee = parseFloat($el('pf-trade-fee')?.value);
  const isT = !!$el('pf-trade-t')?.checked;
  let remark = ($el('pf-trade-remark')?.value || '').trim();
  if (isT) remark = '【做T】' + remark;

  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) { toast('日期格式应为 YYYY-MM-DD', 'error'); return; }
  if (!/^\d{6}$/.test(code)) { toast('请输入 6 位股票代码', 'error'); return; }
  if (!name) { toast('请输入股票名称', 'error'); return; }
  if (!Number.isInteger(qty) || qty <= 0) { toast('数量必须为正整数', 'error'); return; }
  if (!(price > 0)) { toast('价格必须为正数', 'error'); return; }
  if (fee < 0 || isNaN(fee)) { toast('手续费不能为负数', 'error'); return; }

  const btn = $el('pf-trade-submit');
  if (btn) btn.disabled = true;
  try {
    const r = await apiPost('/api/portfolio/trades', {
      trade_date: date, name: name, code: code,
      quantity: qty, price: price, side: side, remark: remark,
      fee: isNaN(fee) ? 0 : fee,
    });
    pfData = r;
    pfRenderSummary();
    pfRenderTable();
    pfTradeInit();
    $el('pf-trade-qty').value = '';
    $el('pf-trade-price').value = '';
    $el('pf-trade-fee').value = '';
    $el('pf-trade-fee-est').textContent = '';
    pfEstimateFee._last = undefined;
    $el('pf-trade-remark').value = '';
    $el('pf-trade-t').checked = false;
    toast(r.message || '交易已录入，持仓已自动更新', 'success');
  } catch (e) {
    toast('录入失败: ' + e.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function pfTradeUndo() {
  if (!confirm('确定撤销最近一笔界面录入？持仓与可用金额将回滚。')) return;
  const btn = $el('pf-trade-undo');
  if (btn) btn.disabled = true;
  try {
    const r = await apiPost('/api/portfolio/trades/undo', {});
    pfData = r;
    pfRenderSummary();
    pfRenderTable();
    pfTradeInit();
    toast(r.message || '已撤销最近一笔', 'success');
  } catch (e) {
    toast('撤销失败: ' + e.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}


// ═══════════════════════════════════════════════════════════════
// 东财实验区
// ═══════════════════════════════════════════════════════════════

async function emLoad() {
  try {
    const cfg = await apiGet('/api/portfolio/eastmoney/config');
    const status = $el('em-status');
    if (status) {
      if (cfg.has_creds) {
        status.textContent = '已配置（尾号 ' + (cfg.account_suffix || '****') + '）'
          + (cfg.last_error ? ' ⚠️ ' + cfg.last_error : '');
      } else if (cfg.last_error) {
        status.textContent = '⚠️ ' + cfg.last_error;
      } else {
        status.textContent = '未配置（可选实验功能）';
      }
    }
  } catch (e) { /* ignore */ }
}

async function emSave() {
  const account = ($el('em-account')?.value || '').trim();
  const password = $el('em-password')?.value || '';
  if (!account || !password) { toast('请输入账号和密码', 'error'); return; }
  try {
    const r = await apiPut('/api/portfolio/eastmoney/config', { account, password, note: 'dashboard' });
    $el('em-password').value = '';
    toast('凭据已加密保存（尾号 ' + r.account_suffix + '）', 'success');
    emLoad();
  } catch (e) {
    toast('保存失败: ' + e.message, 'error');
  }
}

async function emRefresh() {
  try {
    await apiPost('/api/portfolio/eastmoney/refresh', {});
    toast('东财拉取已启动，请稍后查看（失败自动回退手动配置）', 'success');
    setTimeout(() => pfLoad(), 6000);
  } catch (e) {
    toast('东财刷新失败: ' + e.message, 'error');
  }
}


// ═══════════════════════════════════════════════════════════════
// 每日信号
// ═══════════════════════════════════════════════════════════════

let sigView = 'markdown';  // markdown | table

async function sigLoad(force) {
  if (!force && !_viewInit.signals) return;
  try {
    const rep = await apiGet('/api/reports?type=' + encodeURIComponent('每日信号') + '&limit=200');
    const dates = rep.items.map((i) => i.report_date);
    const sel = $el('sig-date');
    if (sel && sel.options.length !== dates.length) {
      sel.innerHTML = dates.map((d) => `<option value="${d}">${d}</option>`).join('');
      if (dates.length) sel.value = dates[0];
    }
    // BUG-FIX(2026-09-07)：切换日期必须渲染用户选中的日期（sel.value），
    // 原先硬编码 dates[0] 导致历史信号永远显示最新一天，日期选择器形同虚设。
    const chosen = (sel && sel.options.length) ? sel.value : (dates[0] || null);
    if (chosen) sigRender(chosen);
  } catch (e) {
    safeSetHTML('sig-content', '<p class="muted">加载信号失败: ' + escapeHtml(e.message) + '</p>');
  }
}

async function sigLoadLatest() {
  try {
    const d = await apiGet('/api/daily-signals');
    const sel = $el('sig-date');
    if (sel && d.date) sel.value = d.date;
    sigRender(d.date);
  } catch (e) {
    safeSetHTML('sig-content', '<p class="muted">加载信号失败: ' + escapeHtml(e.message) + '</p>');
  }
}

async function sigRender(date) {
  try {
    const d = await apiGet('/api/daily-signals?date=' + encodeURIComponent(date));
    const box = $el('sig-content');
    if (!box) return;
    // Phase 3 云库化：云库有结构化信号（d.signals）→ 渲染含评价列的结构化表
    if (d.signals && d.signals.length) {
      box.innerHTML = renderCloudSignals(d.signals);
      return;
    }
    if (sigView === 'table' && d.parsed && d.parsed.length) {
      // 列与 每日信号.md v2.0 信号总表（12 列）对齐
      // BUG-FIX(2026-09-07)：补回"触发条件"列（原先 11 列，触发条件被静默丢弃），
      // 顺序与 _SIGNAL_COLUMNS 保持一致
      const cols = ['优先级', '标的', '触发条件', '操作类型', '状态', '方向', '紧急度', '预期触发率', '目标/止损', '有效时段', '仓位', '信号ID'];
      box.innerHTML = '<div class="table-wrap"><table class="data-table sig-table"><thead><tr>' +
        cols.map((c) => '<th>' + escapeHtml(c) + '</th>').join('') +
        '</tr></thead><tbody>' +
        d.parsed.map((r) => '<tr>' + cols.map((c) => '<td>' + escapeHtml(r[c] || '') + '</td>').join('') + '</tr>').join('') +
        '</tbody></table></div>';
    } else {
      box.innerHTML = renderMarkdown(d.markdown);
    }
  } catch (e) {
    safeSetHTML('sig-content', '<p class="muted">加载信号失败: ' + escapeHtml(e.message) + '</p>');
  }
}

// ── 云库信号结构化表（含复盘回填评价列）──
function renderCloudSignals(signals) {
  const cols = ['信号ID', '日期', '优先级', '标的', '操作', '状态', '方向', '紧急度', '预期触发率', '目标/止损', '仓位', '决策质量', '执行质量', 'P&L'];
  const rows = signals.map((s) => {
    const target = s.target_price != null ? s.target_price : (s.target_pct != null ? s.target_pct + '%' : '—');
    const stop = s.stop_price != null ? s.stop_price : (s.stop_pct != null ? s.stop_pct + '%' : '—');
    const pnl = s.pnl != null ? '<span class="sig-pnl ' + (s.pnl >= 0 ? 'up' : 'down') + '">' + fmtMoney(s.pnl) + '</span>' : '—';
    const statusClass = 'sig-status ' + String(s.status || '').replace(/[^a-z]/g, '');
    return '<tr>' +
      '<td>' + escapeHtml(s.signal_id || '') + '</td>' +
      '<td>' + escapeHtml((s.signal_date || s.trigger_date || '').slice(0, 10)) + '</td>' +
      '<td><span class="badge badge-' + escapeHtml(String(s.priority || '').toLowerCase()) + '">' + escapeHtml(s.priority || '') + '</span></td>' +
      '<td>' + escapeHtml(s.name || '') + ' <span class="muted">' + escapeHtml(s.ticker || '') + '</span></td>' +
      '<td>' + escapeHtml(s.trade_type === 'buy' ? '买入' : s.trade_type === 'sell' ? '卖出' : (s.trade_type || '')) + '</td>' +
      '<td><span class="' + statusClass + '">' + escapeHtml(s.status || '') + '</span></td>' +
      '<td>' + escapeHtml(s.direction === 'buy' ? '多' : s.direction === 'sell' ? '空' : '—') + '</td>' +
      '<td>' + escapeHtml(String(s.urgency || '')) + '</td>' +
      '<td>' + (s.expected_trigger_rate != null ? escapeHtml(String(s.expected_trigger_rate)) + '%' : '—') + '</td>' +
      '<td>' + escapeHtml(String(target)) + ' / ' + escapeHtml(String(stop)) + '</td>' +
      '<td>' + escapeHtml(s.position || '—') + '</td>' +
      '<td class="muted">' + escapeHtml(s.eval_decision_quality || '—') + '</td>' +
      '<td class="muted">' + escapeHtml(s.eval_execution_quality || '—') + '</td>' +
      '<td>' + pnl + '</td>' +
      '</tr>';
  }).join('');
  return '<div class="table-wrap"><table class="data-table sig-table"><thead><tr>' +
    cols.map((c) => '<th>' + escapeHtml(c) + '</th>').join('') +
    '</tr></thead><tbody>' + rows + '</tbody></table></div>';
}

// ── 信号质量评估（Phase 3 · §9.3）──
async function sigqLoad(period) {
  document.querySelectorAll('#sigq-period .seg-item').forEach((b) => {
    b.classList.toggle('is-active', b.getAttribute('data-period') === period);
  });
  try {
    const d = await apiGet('/api/signal-quality?period=' + encodeURIComponent(period));
    const box = $el('sigq-content');
    if (!box) return;
    const src = $el('sigq-source');
    if (src) src.textContent = '数据源: ' + (d.source === 'cloud' ? '云库' : '本地缓存');
    if (!d.metrics) {
      box.innerHTML = '<p class="muted">该周期暂无已生成信号</p>';
      return;
    }
    box.innerHTML = renderQuality(d);
  } catch (e) {
    safeSetHTML('sigq-content', '<p class="muted">加载质量评估失败: ' + escapeHtml(e.message) + '</p>');
  }
}

function renderQuality(d) {
  const m = d.metrics;
  const eva = m.expected_vs_actual || {};
  const gap = eva.avg_gap;
  const cards = [
    ['触发率 (P1)', m.trigger_rate_p1 + '%', m.trigger_rate_p1 >= 40 ? 'ok' : (m.trigger_rate_p1 < 40 && m.trigger_rate_p1 > 0 ? 'warn' : 'muted')],
    ['触发率 (全部)', m.trigger_rate_all + '%', 'neutral'],
    ['目标达成率', m.target_hit_rate + '%', m.target_hit_rate >= 50 ? 'ok' : 'warn'],
    ['平均达标天数', m.avg_hit_days + ' 天', m.avg_hit_days > 0 && m.avg_hit_days <= 2 ? 'ok' : 'warn'],
    ['平均盈亏比', m.avg_profit_loss_ratio, m.avg_profit_loss_ratio >= 1 ? 'ok' : 'warn'],
    ['方向准确率', m.direction_accuracy + '%', m.direction_accuracy >= 50 ? 'ok' : 'warn'],
    ['期望价值', fmtMoney(m.signal_expected_value), m.signal_expected_value >= 0 ? 'ok' : 'down'],
    ['单笔最大亏损', fmtMoney(m.max_loss), m.max_loss === 0 ? 'neutral' : 'down'],
  ];
  const cardHtml = cards.map(([label, val, tone]) =>
    '<div class="qcard qcard-' + tone + '"><div class="qcard-label">' + escapeHtml(label) + '</div>' +
    '<div class="qcard-value">' + escapeHtml(String(val)) + '</div></div>').join('');

  const p0 = d.p0_execution;
  let p0Html = '<p class="muted">暂无 P0 信号</p>';
  if (p0 && p0.total > 0) {
    p0Html = '<div class="qcard ' + (p0.rate >= 100 ? 'qcard-ok' : p0.rate >= 50 ? 'qcard-warn' : 'qcard-down') + '">' +
      '<div class="qcard-label">P0 执行率</div><div class="qcard-value">' + p0.rate + '%</div>' +
      '<div class="qcard-sub">' + p0.executed + '/' + p0.total + ' 已执行</div></div>';
    if (p0.pending && p0.pending.length) {
      p0Html += '<div class="qcard-warn-inline">待执行: ' +
        p0.pending.map((p) => escapeHtml((p.name || '') + ' (' + (p.status || '') + ')')).join('、') +
        '</div>';
    }
  }

  const gapHtml = (gap === null || gap === undefined)
    ? '<span class="muted">无预期率数据</span>'
    : '<span class="' + (gap >= 0 ? 'sig-pnl up' : 'sig-pnl down') + '">' + gap + ' 个百分点</span>' +
      (gap < 0 ? ' <span class="muted">(生成者偏乐观，建议下调预期)</span>' : '');

  return '<div class="qgrid">' + cardHtml + '</div>' +
    '<div class="qrow"><span class="qrow-label">预期 vs 实际触发率</span>' + gapHtml + '</div>' +
    '<div class="qrow"><span class="qrow-label">P0 执行</span><div class="qrow-inline">' + p0Html + '</div></div>' +
    '<p class="muted qnote">信号数 ' + d.signals_included + ' · 已结算 ' + d.settled_included + ' · 指标由复盘/周三周报生产，本页只读聚合展示</p>';
}

function sigToggle() {
  sigView = sigView === 'table' ? 'markdown' : 'table';
  const btn = $el('sig-toggle');
  if (btn) btn.textContent = sigView === 'table' ? '原文视图' : '表格视图';
  const sel = $el('sig-date');
  if (sel && sel.value) sigRender(sel.value);
}


// ═══════════════════════════════════════════════════════════════
// 报告
// ═══════════════════════════════════════════════════════════════

let repSelectedDate = null;

async function repLoad(force) {
  if (!force && !_viewInit.reports) return;
  try {
    const d = await apiGet('/api/reports?limit=500');
    const dates = [...new Set(d.items.map((i) => i.report_date))];
    const listEl = $el('rep-date-list');
    if (listEl) {
      listEl.innerHTML = dates.map((dt) =>
        `<button class="rep-date ${dt === repSelectedDate ? 'rep-date-active' : ''}" onclick="repSelectDate('${dt}')">${dt}</button>`
      ).join('') || '<p class="muted">暂无报告</p>';
    }
    if (dates.length && !repSelectedDate) repSelectDate(dates[0]);
  } catch (e) {
    safeSetHTML('rep-date-list', '<p class="muted">加载报告列表失败: ' + escapeHtml(e.message) + '</p>');
  }
}

async function repSelectDate(date) {
  repSelectedDate = date;
  document.querySelectorAll('.rep-date').forEach((b) => {
    b.classList.toggle('rep-date-active', b.textContent === date);
  });
  try {
    const d = await apiGet('/api/reports?date=' + encodeURIComponent(date));
    const types = d.items.map((i) => i.report_type);
    safeSetHTML('rep-types', types.map((t) =>
      `<button class="rep-type" onclick="repSelectType('${escapeHtml(t)}')">${escapeHtml(t)}</button>`).join(''));
    if (types.length) repSelectType(types[0]);
  } catch (e) {
    safeSetHTML('rep-content', '<p class="muted">加载失败: ' + escapeHtml(e.message) + '</p>');
  }
}

async function repSelectType(type) {
  try {
    const r = await apiGet('/api/reports/' + repSelectedDate + '/' + encodeURIComponent(type));
    document.querySelectorAll('.rep-type').forEach((b) => {
      b.classList.toggle('rep-type-active', b.textContent === type);
    });
    safeSetHTML('rep-content', renderMarkdown(r.markdown));
  } catch (e) {
    safeSetHTML('rep-content', '<p class="muted">加载失败: ' + escapeHtml(e.message) + '</p>');
  }
}

async function repImport() {
  try {
    const r = await apiPost('/api/reports/import', {});
    toast('已导入 ' + (r.imported || 0) + ' 份报告', 'success');
    repLoad(true);
  } catch (e) {
    toast('导入失败: ' + e.message, 'error');
  }
}


// ═══════════════════════════════════════════════════════════════
// 定时任务
// ═══════════════════════════════════════════════════════════════

let schedAuto = false;  // 当前 auto 开关状态（schedLoad 刷新）

async function schedLoad(force) {
  if (!force && !_viewInit.scheduler) return;
  try {
    const [tasksData, runs] = await Promise.all([
      apiGet('/api/scheduler/tasks'),
      apiGet('/api/scheduler/runs?limit=15'),
    ]);
    const tasks = tasksData;
    schedAuto = !!tasks.auto_enabled;
    const online = !!tasks.online;
    const eng = $el('sched-engine');
    if (eng) {
      if (!online) {
        eng.textContent = '😴 小满未上线 · 定时任务暂停'
          + ` · 今日交易日:${tasks.is_trading_day ? '是' : '否'}`
          + (tasks.last_tick ? ' · 心跳:' + tasks.last_tick.slice(11, 19) : '');
      } else {
        eng.textContent = (schedAuto ? '👔 上班中 · 按日程表执行' : '🏖️ 请假中 · 定时任务暂停')
          + ` · 今日交易日:${tasks.is_trading_day ? '是' : '否'}`
          + (tasks.last_tick ? ' · 心跳:' + tasks.last_tick.slice(11, 19) : '');
      }
    }
    const autoBtn = $el('sched-auto-btn');
    if (autoBtn) {
      if (!online) {
        autoBtn.style.display = 'none';
      } else {
        autoBtn.style.display = '';
        autoBtn.textContent = schedAuto ? '🏖️ 请假' : '👔 上班';
        autoBtn.classList.toggle('btn-accent', schedAuto);
        autoBtn.title = schedAuto ? '点击请假：暂停定时任务' : '点击上班：按日程表执行定时任务';
      }
    }
    const stText = { success: '✅ 成功', failed: '❌ 失败', timeout: '⏱️ 超时', running: '⏳ 运行中', skipped: '⏭️ 跳过' };
    function renderTasks(taskList, tbodyId) {
      const tbody = $el(tbodyId);
      if (tbody) {
        tbody.innerHTML = taskList.map((t) => {
          const last = t.last_run || {};
          const running = last.status === 'running';
          return `<tr>
            <td class="col-name"><b>${escapeHtml(t.task_id)}</b><br><span class="muted">${escapeHtml(t.description || '')}</span></td>
            <td class="col-num">${escapeHtml(t.target_time)}${t.hourly ? ' (每小时)' : ''}</td>
            <td class="col-num">${t.trading_day_required ? '是' : '否'}</td>
            <td class="col-num ${last.status === 'failed' ? 'num-danger' : ''}">${stText[last.status] || '—'}</td>
            <td class="col-num">${last.run_time ? escapeHtml(last.run_time.slice(0, 19)) : '—'}</td>
            <td class="col-act"><button class="btn btn-sm" onclick="schedRun('${t.task_id}')" ${running ? 'disabled' : ''}>▶ 立即运行</button></td>
          </tr>`;
        }).join('') || '<tr><td colspan="6" class="loading-cell">暂无任务</td></tr>';
      }
    }
    renderTasks(tasks.daily_tasks || [], 'sched-daily-tbody');
    renderTasks(tasks.other_tasks || [], 'sched-other-tbody');
    const runsEl = $el('sched-runs');
    if (runsEl) {
      runsEl.innerHTML = runs.items.map((r) => {
        const st = { success: '✅', failed: '❌', timeout: '⏱️', running: '⏳', skipped: '⏭️' }[r.status] || '·';
        return `<div class="sched-run" onclick="schedShowLog(${r.id})">
          <span>${st}</span> <b>${escapeHtml(r.task_id)}</b>
          <span class="muted">${r.trigger === 'manual' ? '手动' : '自动'} · ${escapeHtml(r.run_time || '')}</span>
          <span class="muted">${r.duration_sec != null ? r.duration_sec + 's' : ''}</span>
        </div>`;
      }).join('') || '<p class="muted">暂无运行记录</p>';
    }
  } catch (e) {
    safeSetHTML('sched-daily-tbody', '<tr><td colspan="6" class="loading-cell">加载失败: ' + escapeHtml(e.message) + '</td></tr>');
    safeSetHTML('sched-other-tbody', '<tr><td colspan="6" class="loading-cell">加载失败: ' + escapeHtml(e.message) + '</td></tr>');
  }
}

async function schedToggleAuto() {
  const btn = $el('sched-auto-btn');
  if (btn) btn.disabled = true;
  try {
    const r = await apiPost('/api/scheduler/auto', { enabled: !schedAuto });
    schedAuto = !!r.auto_enabled;
    toast(r.message || (schedAuto ? '👔 小满上班了，开始按日程表工作' : '🏖️ 小满请假了，定时任务暂停'), 'success');
    schedLoad(true);
  } catch (e) {
    toast('切换失败: ' + e.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function schedRun(taskId) {
  try {
    const r = await apiPost('/api/scheduler/run/' + encodeURIComponent(taskId), {});
    toast('已启动 ' + taskId + '（run#' + r.run_id + '）', 'success');
    setTimeout(() => schedLoad(true), 4000);
  } catch (e) {
    toast('运行失败: ' + e.message, 'error');
  }
}

async function schedShowLog(runId) {
  try {
    const r = await apiGet('/api/scheduler/runs/' + runId + '/log');
    const out = (r.output || '(无输出)').slice(-4000);
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.innerHTML = `<div class="modal-card">
      <div class="modal-head"><b>run#${r.id} · ${escapeHtml(r.task_id)}</b>
        <span class="muted">${escapeHtml(r.run_time || '')} · ${r.status} · ${r.duration_sec != null ? r.duration_sec + 's' : '—'}</span>
        <button class="btn-icon-only" onclick="this.closest('.modal-overlay').remove()">✕</button>
      </div>
      <pre class="modal-body">${escapeHtml(out)}</pre>
    </div>`;
    modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });
    document.body.appendChild(modal);
  } catch (e) {
    toast('读取日志失败: ' + e.message, 'error');
  }
}


// ═══════════════════════════════════════════════════════════════
// 自动轮询 — 迁移后调度器自动执行分析，报告/信号/运行状态自动刷新到页面
// ═══════════════════════════════════════════════════════════════

const POLL_INTERVAL_MS = 30000;

function pollActiveDailyView() {
  // 仅登录后且对应视图激活时刷新；持仓视图不轮询（避免覆盖用户未保存编辑）
  if (typeof Auth === 'undefined' || !Auth.isLoggedIn()) return;
  const active = document.querySelector('.view.view-active');
  if (!active) return;
  const id = active.id;
  if (id === 'view-signals') { sigLoad(true); }
  else if (id === 'view-reports') { repLoad(true); }
  else if (id === 'view-scheduler') { schedLoad(true); }
}

setInterval(pollActiveDailyView, POLL_INTERVAL_MS);
