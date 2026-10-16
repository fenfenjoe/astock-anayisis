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

// ── HTML 报告渲染（2026-10 回退：早盘/复盘报告恢复 markdown 渲染；以下仅作历史 HTML 行兜底）──
function isHtmlReport(s) {
  // 剥离 UTF-8 BOM 与首尾空白后再判定（LLM 写入的 HTML 可能带 \ufeff）
  const t = String(s || '').replace(/^\uFEFF/, '').trim().toLowerCase();
  return /^<!doctype html/.test(t) || /^<html[\s>]/.test(t) || /<style[\s>]/.test(t);
}

function sanitizeReportHtml(html) {
  if (typeof DOMParser === 'undefined') {
    // 极旧浏览器兜底：粗粒度剥离危险内容
    return String(html || '')
      .replace(/<script[\s\S]*?<\/script>/gi, '')
      .replace(/<iframe[\s\S]*?<\/iframe>/gi, '')
      .replace(/<object[\s\S]*?<\/object>/gi, '')
      .replace(/<embed[\s\S]*?>/gi, '')
      .replace(/\son\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, '')
      .replace(/javascript:/gi, '');
  }
  const doc = new DOMParser().parseFromString(String(html || ''), 'text/html');
  // 移除危险/交互节点（保留 <style>，报告自带设计系统）
  const bad = doc.querySelectorAll('script, iframe, object, embed, link, meta, base, form, input, button, select, textarea');
  bad.forEach((n) => n.remove());
  // 剥离事件属性与 javascript: URL
  doc.querySelectorAll('*').forEach((el) => {
    Array.from(el.attributes).forEach((attr) => {
      const name = attr.name.toLowerCase();
      const val = (attr.value || '').toLowerCase();
      if (name.startsWith('on') || val.startsWith('javascript:')) {
        el.removeAttribute(attr.name);
      }
    });
  });
  return doc.body ? doc.body.innerHTML : String(html || '');
}

function renderReportContent(raw) {
  if (!raw) return '<p class="muted">（空）</p>';
  if (isHtmlReport(raw)) {
    return '<div class="rep-html">' + sanitizeReportHtml(raw) + '</div>';
  }
  return renderMarkdown(raw);
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
  // 信号/报告每次进入都刷新（这些内容会随时间新增）。
  if (viewId === 'view-portfolio' && !_viewInit.portfolio) { _viewInit.portfolio = true; pfLoad(); }
  if (viewId === 'view-signals') { _viewInit.signals = true; sigLoad(true); sigqLoad('day'); }
  if (viewId === 'view-reports') { _viewInit.reports = true; repLoad(true); }
  if (viewId === 'view-tickets') { _viewInit.tickets = true; Tickets.load(); }
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
// 每日信号（任务4 重做 · 2026-09-14）
// ═══════════════════════════════════════════════════════════════

let sigEnums = null;          // /api/signal-enums 缓存
let sigHistPage = 1;          // 历史查询当前页
let sigHistState = {};        // 历史查询条件

async function sigLoad(force) {
  // 进入视图时同时加载今日信号 + 历史查询（sigqLoad 由 switchView 调用）
  try {
    _sigTrigCache = {};   // 触发记录展开缓存：视图每次进入时清空，避免陈旧
    _sigCheckCache = {};  // 盘中检查记录展开缓存：同上
    if (!sigEnums) {
      sigEnums = await apiGet('/api/signal-enums');
      _fillSigSelects();
    }
    await sigTodayLoad();
    await sigHistorySearch(1);
  } catch (e) {
    safeSetHTML('sig-content', '<p class="muted">加载信号失败: ' + escapeHtml(e.message) + '</p>');
  }
}

function _fillSigSelects() {
  const typeSel = $el('sig-hist-type');
  const statusSel = $el('sig-hist-status');
  if (!typeSel || !statusSel || !sigEnums) return;
  typeSel.innerHTML = '<option value="">操作类型</option>' +
    (sigEnums.trade_type || []).map((v) =>
      '<option value="' + escapeHtml(v) + '">' + escapeHtml(v) + '</option>').join('');
  statusSel.innerHTML = '<option value="">状态</option>' +
    (sigEnums.status || []).map((v) =>
      '<option value="' + escapeHtml(v) + '">' + escapeHtml(_statusCN(v)) + '</option>').join('');
}

function _tradeTypeLabel(t) {
  return t === 'buy' ? '买入' : (t === 'sell' ? '卖出' : (t || '—'));
}

// 云库状态英文内部值 → 中文展示（与 每日信号.md 信号总表中文状态一致；v3.0：初始=未触发、新增已过期）
const SIG_STATUS_CN = {
  open: '未触发',
  triggered: '已触发',
  executed: '已执行',
  partial_executed: '部分执行',
  settled: '已结算',
  expired: '已过期',
};

function _statusCN(s) {
  if (!s) return '—';
  return SIG_STATUS_CN[s] || s; // 未识别的值原样展示
}

function _statusClass(s) {
  return 'sig-status ' + String(s || '').replace(/[^a-z]/g, '');
}

// ── 表1 今日信号 ──
async function sigTodayLoad() {
  const dateInput = $el('sig-date');
  let date = dateInput && dateInput.value ? dateInput.value.replace(/-/g, '') : '';
  try {
    const d = await apiGet('/api/daily-signals' + (date ? '?date=' + date : ''));
    const box = $el('sig-content');
    if (!box) return;
    if (dateInput && d.date && !dateInput.value) dateInput.value = d.date.replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3');
    if (!d.signals || !d.signals.length) {
      box.innerHTML = '<p class="muted">今日暂无信号（非交易日或无信号生成）</p>';
      return;
    }
    const cols = ['优先级', '标的', '操作类型', '仓位', '有效时段', '状态', '交易价', '目标价', '止损价', '信号ID', '操作'];
    box.innerHTML = '<div class="table-wrap"><table class="data-table sig-table"><thead><tr>' +
      '<th class="sig-toggle-th" title="点击信号行展开盘中检查记录"></th>' +
      cols.map((c) => '<th>' + escapeHtml(c) + '</th>').join('') +
      '</tr></thead><tbody>' +
      d.signals.map((s) => _sigRowHtml(s, cols, false)).join('') +
      '</tbody></table></div>';
  } catch (e) {
    safeSetHTML('sig-content', '<p class="muted">加载失败: ' + escapeHtml(e.message) + '</p>');
  }
}

function _sigRowHtml(s, cols, withDate) {
  const typeLabel = _tradeTypeLabel(s.trade_type);
  const sid = s.signal_id || '';
  const cells = {
    '日期': withDate ? escapeHtml((s.signal_date || '').slice(5)) : '',
    '优先级': escapeHtml(s.priority || '—'),
    '标的': '<span class="sig-name">' + escapeHtml(s.name || s.ticker || '—') + '</span>' +
      (s.ticker ? ' <span class="muted">' + escapeHtml(s.ticker) + '</span>' : ''),
    '操作类型': '<span class="' + (s.trade_type === 'sell' ? 'num-danger' : 'num-positive') + '">' + escapeHtml(typeLabel) + '</span>',
    '仓位': escapeHtml(s.position || '—'),
    '有效时段': escapeHtml(s.valid_window || '—'),
    '状态': '<span class="' + _statusClass(s.status) + '">' + escapeHtml(_statusCN(s.status)) + '</span>',
    '交易价': s.trade_price != null && s.trade_price !== '' ? escapeHtml(s.trade_price) : '—',
    '目标价': escapeHtml(s.target_price || '—'),
    '止损价': escapeHtml(s.stop_price || '—'),
    '信号ID': sid
      ? '<span class="sig-expand" data-signal-id="' + escapeHtml(sid) +
        '" onclick="sigToggleTriggers(event,\'' + escapeHtml(sid).replace(/'/g, "\\'") + '\')">' +
        '<span class="sig-caret">▸</span> <code class="sig-id">' + escapeHtml(sid) + '</code></span>'
      : '<span class="muted">—</span>',
    '操作': _sigActionCell(s),
  };
  // 行首展开指示器：点击整行展开「盘中检查记录」（再次点击收起）
  const caretCell = '<td class="sig-toggle-cell"><span class="sig-caret sig-row-caret">▸</span></td>';
  return '<tr class="sig-row" data-signal-id="' + escapeHtml(sid) + '"' +
    (sid ? ' onclick="sigToggleChecks(event,\'' + escapeHtml(sid).replace(/'/g, "\\'") + '\')"' : '') + '>' +
    caretCell +
    cols.map((c) => '<td>' + (cells[c] || '') + '</td>').join('') + '</tr>';
}

// ── 信号触发记录展开（2026-09-21 新增）──────────────────────────
// 点击信号ID → 从 /api/signal-trigger-records 拉取该信号的触发记录明细，
// 在信号行下方插入一个 colspan 明细行，内嵌一张触发记录表格。再次点击收起。
const _sigTrigCacheInit = {};   // signal_id -> {loaded, html, loading}（sigLoad 时整体替换清空）
let _sigTrigCache = _sigTrigCacheInit;

async function sigToggleTriggers(ev, signalId) {
  ev.stopPropagation();
  const toggle = ev.currentTarget;
  const row = toggle.closest('tr.sig-row');
  if (!row) return;
  const tbody = row.parentNode;
  if (!tbody) return;

  // 已有触发记录展开行 → 收起
  const next = row.nextElementSibling;
  if (next && next.classList.contains('sig-trigger-detail')) {
    next.remove();
    const caret = toggle.querySelector('.sig-caret');
    if (caret) caret.textContent = '▸';
    return;
  }

  // 展开前收起该行的盘中检查记录（互斥，避免同一信号行下两个展开面板）
  const checkDetail = row.nextElementSibling;
  if (checkDetail && checkDetail.classList.contains('sig-check-detail')) {
    checkDetail.remove();
    const rowCaret = row.querySelector('.sig-row-caret');
    if (rowCaret) rowCaret.textContent = '▸';
  }

  // 展开：插入明细行
  const detail = document.createElement('tr');
  detail.className = 'sig-trigger-detail';
  detail.innerHTML = '<td colspan="' + row.children.length + '"><div class="sig-trigger-box">' +
    '<span class="muted">加载触发记录...</span></div></td>';
  tbody.insertBefore(detail, row.nextSibling);
  const caret = toggle.querySelector('.sig-caret');
  if (caret) caret.textContent = '▾';

  // 有缓存 → 直接渲染
  if (_sigTrigCache[signalId] && _sigTrigCache[signalId].loaded) {
    _renderTrigDetail(detail, _sigTrigCache[signalId].items, signalId);
    return;
  }

  try {
    const d = await apiGet('/api/signal-trigger-records?signal_id=' + encodeURIComponent(signalId));
    const items = d.items || [];
    _sigTrigCache[signalId] = { loaded: true, items };
    _renderTrigDetail(detail, items, signalId);
  } catch (e) {
    detail.innerHTML = '<td colspan="' + row.children.length + '"><div class="sig-trigger-box">' +
      '<span class="num-danger">加载失败: ' + escapeHtml(e.message) + '</span></div></td>';
    if (caret) caret.textContent = '▸';
  }
}

function _renderTrigDetail(detail, items, signalId) {
  const prev = detail.previousElementSibling;
  const cols = prev ? prev.children.length : 8;
  if (!items || !items.length) {
    detail.innerHTML = '<td colspan="' + cols + '"><div class="sig-trigger-box"><span class="muted">' +
      '该信号暂无触发记录（signal_id=' + escapeHtml(signalId) + '）</span></div></td>';
    return;
  }
  // 归因优先（2026-09-24）：早盘预填的「已生成」记录（内容=生成原因）排最前，
  // 其后按时间倒序展示盘中「已触发」等记录 —— 用户先看到"为什么生成"，再看到触发过程
  const sorted = items.slice().sort((a, b) => {
    const aGen = (a.status || '').indexOf('已生成') !== -1 ? 0 : 1;
    const bGen = (b.status || '').indexOf('已生成') !== -1 ? 0 : 1;
    if (aGen !== bGen) return aGen - bGen;
    return String(b.trigger_time || '').localeCompare(String(a.trigger_time || ''));
  });
  const head = ['触发时间', '优先级', '标的', '操作类型', '触发条件摘要', '状态', '建议操作', '用户操作'];
  const body = sorted.map((r) => {
    const isGen = (r.status || '').indexOf('已生成') !== -1;
    const statusCls = isGen ? 'sig-gen-status' : 'sig-status';
    return '<tr>' +
      '<td class="mono">' + escapeHtml(r.trigger_time || '—') + '</td>' +
      '<td>' + escapeHtml(r.priority || '—') + '</td>' +
      '<td>' + escapeHtml((r.name || '') + (r.ticker ? ' <span class="muted">' + r.ticker + '</span>' : '')) + '</td>' +
      '<td>' + escapeHtml(r.action_type || '—') + '</td>' +
      '<td class="sig-trig-cond">' + escapeHtml(r.condition || '—') + '</td>' +
      '<td><span class="' + statusCls + '">' + escapeHtml(r.status || '—') + '</span></td>' +
      '<td>' + escapeHtml(r.suggest || '—') + '</td>' +
      '<td>' + escapeHtml(r.result || '—') + '</td>' +
      '</tr>';
  }).join('');
  detail.innerHTML = '<td colspan="' + cols + '"><div class="sig-trigger-box">' +
    '<div class="sig-trigger-head">📋 信号触发记录 <span class="muted">(' + items.length + ' 条 · 首条=生成归因)</span></div>' +
    '<div class="table-wrap"><table class="data-table sig-trigger-table"><thead><tr>' +
    head.map((h) => '<th>' + escapeHtml(h) + '</th>').join('') +
    '</tr></thead><tbody>' + body + '</tbody></table></div></div></td>';
}

// ── 盘中检查记录展开（2026-09-24 新增）──────────────────────────
// 点击信号**行** → 从 /api/signal-check-records 拉取该信号每个检查点的盘中检查结果，
// 在信号行下方插入一个 colspan 明细行，内嵌检查记录表格。再次点击收起。
const _sigCheckCacheInit = {};   // signal_id -> {loaded, html, loading}
let _sigCheckCache = _sigCheckCacheInit;

// 行内交互元素（点击不触发整行展开）
function _isSigInnerClick(ev) {
  const t = ev && ev.target;
  if (!t || !t.closest) return false;
  return !!t.closest('.sig-expand, .sig-exec-btn, button, a, input, select, textarea');
}

async function sigToggleChecks(ev, signalId) {
  if (_isSigInnerClick(ev)) return;  // 内部交互（信号ID展开/执行按钮）不触发行展开
  const row = ev.currentTarget.closest('tr.sig-row');
  if (!row) return;
  const tbody = row.parentNode;
  if (!tbody) return;

  // 已有检查记录展开行 → 收起
  const next = row.nextElementSibling;
  if (next && next.classList.contains('sig-check-detail')) {
    next.remove();
    const caret = row.querySelector('.sig-row-caret');
    if (caret) caret.textContent = '▸';
    return;
  }

  // 展开前先收起该行的触发记录展开（互斥，避免同一信号行下两个展开面板）
  const triggerDetail = row.nextElementSibling;
  if (triggerDetail && triggerDetail.classList.contains('sig-trigger-detail')) {
    triggerDetail.remove();
    const idCaret = row.querySelector('.sig-expand .sig-caret');
    if (idCaret) idCaret.textContent = '▸';
  }

  // 展开：插入明细行
  const detail = document.createElement('tr');
  detail.className = 'sig-check-detail';
  detail.innerHTML = '<td colspan="' + row.children.length + '"><div class="sig-trigger-box">' +
    '<span class="muted">加载盘中检查记录...</span></div></td>';
  tbody.insertBefore(detail, row.nextSibling);
  const caret = row.querySelector('.sig-row-caret');
  if (caret) caret.textContent = '▾';

  // 有缓存 → 直接渲染
  if (_sigCheckCache[signalId] && _sigCheckCache[signalId].loaded) {
    _renderCheckDetail(detail, _sigCheckCache[signalId].items, signalId);
    return;
  }

  try {
    const d = await apiGet('/api/signal-check-records?signal_id=' + encodeURIComponent(signalId));
    const items = d.items || [];
    _sigCheckCache[signalId] = { loaded: true, items };
    _renderCheckDetail(detail, items, signalId);
  } catch (e) {
    detail.innerHTML = '<td colspan="' + row.children.length + '"><div class="sig-trigger-box">' +
      '<span class="num-danger">加载失败: ' + escapeHtml(e.message) + '</span></div></td>';
    if (caret) caret.textContent = '▸';
  }
}

function _renderCheckDetail(detail, items, signalId) {
  const prev = detail.previousElementSibling;
  const cols = prev ? prev.children.length : 9;
  if (!items || !items.length) {
    detail.innerHTML = '<td colspan="' + cols + '"><div class="sig-trigger-box"><span class="muted">' +
      '该信号暂无盘中检查记录（signal_id=' + escapeHtml(signalId) + '）</span></div></td>';
    return;
  }
  const head = ['检查点', '检查时间', '现价', '交易价', '触发判定', '状态变化', '检查摘要'];
  // 按 日期+时间 升序展示（09:40 → 14:30 的当日检查轨迹，读取更自然）
  const sorted = items.slice().sort((a, b) =>
    String(a.check_date || '').localeCompare(String(b.check_date || '')) ||
    String(a.check_time || '').localeCompare(String(b.check_time || ''))
  );
  const body = sorted.map((r) => {
    const price = r.price != null && r.price !== '' ? escapeHtml(String(r.price)) : '—';
    const tp = r.trade_price != null && r.trade_price !== '' ? escapeHtml(String(r.trade_price)) : '—';
    const condCls = _checkCondClass(r.condition_met);
    const sb = escapeHtml(r.status_before || '—');
    const sa = escapeHtml(r.status_after || '—');
    const flow = (r.status_before && r.status_after && r.status_before !== r.status_after)
      ? sb + ' → <b class="' + condCls + '">' + sa + '</b>'
      : (sb + (r.status_after && r.status_after !== r.status_before ? '' : ''));
    return '<tr>' +
      '<td>' + escapeHtml(r.check_point || '—') + '</td>' +
      '<td class="mono">' + escapeHtml(r.check_time || '—') + '</td>' +
      '<td class="mono">' + price + '</td>' +
      '<td class="mono">' + tp + '</td>' +
      '<td><span class="' + condCls + '">' + escapeHtml(r.condition_met || '—') + '</span></td>' +
      '<td>' + flow + '</td>' +
      '<td class="sig-trig-cond">' + escapeHtml(r.note || '—') + '</td>' +
      '</tr>';
  }).join('');
  detail.innerHTML = '<td colspan="' + cols + '"><div class="sig-trigger-box">' +
    '<div class="sig-trigger-head">🔍 盘中检查记录 <span class="muted">(' + items.length + ' 条检查点)</span></div>' +
    '<div class="table-wrap"><table class="data-table sig-trigger-table"><thead><tr>' +
    head.map((h) => '<th>' + escapeHtml(h) + '</th>').join('') +
    '</tr></thead><tbody>' + body + '</tbody></table></div></div></td>';
}

function _checkCondClass(c) {
  const s = String(c || '');
  if (s.indexOf('触发') !== -1 && s.indexOf('未') === -1) return 'num-positive';
  if (s.indexOf('已过期') !== -1) return 'muted';
  if (s.indexOf('跳过') !== -1) return 'muted';
  if (s.indexOf('未触发') !== -1) return 'muted';
  return 'muted';
}

// 操作列：可执行信号（open/triggered + buy/sell）渲染「执行」按钮，其余渲染状态态文本
function _sigActionCell(s) {
  const status = s.status || '';
  const type = s.trade_type || '';
  if ((status === 'open' || status === 'triggered') && (type === 'buy' || type === 'sell')) {
    const sid = escapeHtml(s.signal_id || '');
    const price = (s.trade_price != null && s.trade_price !== '') ? s.trade_price
      : (s.entry_price != null && s.entry_price !== '') ? s.entry_price : '';
    const qty = (s.shares != null && s.shares !== '') ? s.shares : '';
    return '<button class="btn-mini sig-exec-btn" data-signal-id="' + sid +
      '" data-price="' + escapeHtml(String(price)) + '" data-qty="' + escapeHtml(String(qty)) +
      '" onclick="sigExecute(\'' + sid + '\')">执行</button>';
  }
  if (status === 'executed') return '<span class="muted">✓ 已执行</span>';
  if (status === 'settled') return '<span class="muted">已结算</span>';
  return '<span class="muted">—</span>';
}

// ── 一键执行信号：弹窗（成交价/数量可改，信号已有值默认填入）→ POST /api/signal-execute → 刷新
function sigExecute(signalId) {
  const btn = document.querySelector('.sig-exec-btn[data-signal-id="' + signalId + '"]');
  const name = btn ? (btn.closest('tr')?.querySelector('.sig-name')?.textContent || signalId) : signalId;
  const knownPrice = btn ? btn.dataset.price : '';
  const knownQty = btn ? btn.dataset.qty : '';

  const modal = document.createElement('div');
  modal.className = 'modal-overlay';
  modal.innerHTML = `<div class="modal-card sig-exec-modal">
    <div class="modal-head">
      <b>执行信号 ${escapeHtml(signalId)}</b>
      <span class="muted">${escapeHtml(name)} · 将录入交易并更新持仓/资产</span>
      <button class="btn-icon-only" onclick="this.closest('.modal-overlay').remove()">✕</button>
    </div>
    <div class="modal-body sig-exec-body">
      <div class="sig-exec-form">
        <label class="sig-exec-field">
          <span>成交价（元/份）</span>
          <input type="number" step="0.001" min="0" id="sig-exec-price"
                 value="${escapeHtml(String(knownPrice))}" placeholder="必填，如 1.620">
        </label>
        <label class="sig-exec-field">
          <span>成交数量（份）</span>
          <input type="number" step="1" min="0" id="sig-exec-qty"
                 value="${escapeHtml(String(knownQty))}" placeholder="必填，如 1000">
        </label>
        <div class="sig-exec-actions">
          <button class="btn btn-secondary sig-exec-cancel">取消</button>
          <button class="btn btn-primary sig-exec-confirm">确认执行</button>
        </div>
      </div>
    </div>
  </div>`;

  // 关闭（取消 / 点遮罩 / ✕）
  const close = () => modal.remove();
  modal.querySelector('.sig-exec-cancel').addEventListener('click', close);
  modal.querySelector('.btn-icon-only').addEventListener('click', close);
  modal.addEventListener('click', (e) => { if (e.target === modal) close(); });

  // 确认：校验 → 提交 → 关闭 → 刷新
  const confirmBtn = modal.querySelector('.sig-exec-confirm');
  confirmBtn.addEventListener('click', async () => {
    const priceNum = parseFloat(modal.querySelector('#sig-exec-price').value);
    const qtyNum = parseFloat(modal.querySelector('#sig-exec-qty').value);
    if (!isFinite(priceNum) || priceNum <= 0 || !isFinite(qtyNum) || qtyNum <= 0) {
      toast('成交价与数量必须为正数', 'error');
      return;
    }
    confirmBtn.disabled = true;
    confirmBtn.textContent = '执行中...';
    try {
      const r = await apiPost('/api/signal-execute', {
        signal_id: signalId,
        price: priceNum,
        quantity: qtyNum,
      });
      close();
      toast(r.message || '信号已执行，持仓/资产已更新', 'success');
      await sigTodayLoad();
      await sigHistorySearch(1);  // 历史表状态同步刷新
    } catch (e) {
      confirmBtn.disabled = false;
      confirmBtn.textContent = '确认执行';
      toast('执行失败: ' + e.message, 'error');
    }
  });

  document.body.appendChild(modal);
  // 焦点给第一个输入框，Enter 提交
  const priceInput = modal.querySelector('#sig-exec-price');
  priceInput.focus();
  priceInput.select();
  modal.querySelectorAll('input').forEach((inp) => {
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') confirmBtn.click();
    });
  });
}

// ── 表2 历史信号查询 ──
function _sigHistParams(page) {
  const g = (id) => { const el = $el(id); return el ? el.value.trim() : ''; };
  const p = new URLSearchParams();
  if (g('sig-hist-date')) p.set('date', g('sig-hist-date').replace(/-/g, ''));
  if (g('sig-hist-ticker')) p.set('ticker', g('sig-hist-ticker'));
  if (g('sig-hist-type')) p.set('trade_type', g('sig-hist-type'));
  if (g('sig-hist-status')) p.set('status', g('sig-hist-status'));
  if (g('sig-hist-id')) p.set('signal_id', g('sig-hist-id'));
  p.set('page', page || 1);
  p.set('page_size', 20);
  return p.toString();
}

async function sigHistorySearch(page) {
  const pageno = page || 1;
  const q = _sigHistParams(pageno);
  try {
    const d = await apiGet('/api/signal-history?' + q);
    const box = $el('sig-hist-content');
    const pager = $el('sig-hist-pager');
    if (!box) return;
    sigHistPage = pageno;
    const cols = ['日期', '优先级', '标的', '操作类型', '仓位', '有效时段', '状态', '交易价', '目标价', '止损价', '信号ID'];
    if (!d.items || !d.items.length) {
      box.innerHTML = '<p class="muted">无符合条件的信号</p>';
      if (pager) pager.style.display = 'none';
      return;
    }
    box.innerHTML = '<div class="table-wrap"><table class="data-table sig-table"><thead><tr>' +
      '<th class="sig-toggle-th" title="点击信号行展开盘中检查记录"></th>' +
      cols.map((c) => '<th>' + escapeHtml(c) + '</th>').join('') +
      '</tr></thead><tbody>' +
      d.items.map((s) => _sigRowHtml(s, cols, true)).join('') +
      '</tbody></table></div>';
    const totalPages = Math.max(1, Math.ceil((d.total || 0) / (d.page_size || 20)));
    if (pager) {
      pager.style.display = 'flex';
      pager.innerHTML = '<span class="muted">共 ' + (d.total || 0) + ' 条 · 第 ' + sigHistPage + '/' + totalPages + ' 页</span>' +
        '<button class="btn btn-sm" ' + (sigHistPage <= 1 ? 'disabled' : '') + ' onclick="sigHistorySearch(' + (sigHistPage - 1) + ')">◀ 上一页</button>' +
        '<button class="btn btn-sm" ' + (sigHistPage >= totalPages ? 'disabled' : '') + ' onclick="sigHistorySearch(' + (sigHistPage + 1) + ')">下一页 ▶</button>';
    }
  } catch (e) {
    safeSetHTML('sig-hist-content', '<p class="muted">加载失败: ' + escapeHtml(e.message) + '</p>');
  }
}

function sigHistoryReset() {
  ['sig-hist-date', 'sig-hist-ticker', 'sig-hist-type', 'sig-hist-status', 'sig-hist-id']
    .forEach((id) => { const el = $el(id); if (el) el.value = ''; });
  sigHistorySearch(1);
}

// ── 信号质量评估（表3，保留；2026-09-14 任务4 重写信号块时误删，已恢复）──
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
    safeSetHTML('rep-content', renderReportContent(r.markdown));
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
}

setInterval(pollActiveDailyView, POLL_INTERVAL_MS);
