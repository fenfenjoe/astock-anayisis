/**
 * AStock ETF Dashboard — Frontend Logic (v2.1)
 * - Strategy detail with race-condition guard & client-side KB cache
 * - Single-strategy backtest from operations column
 * - Charts removed (equity/drawdown) per UX simplification
 */
'use strict';

// ── State ──
const state = {
  strategies: [],
  selectedId: null,
  loadingSid: null,        // Currently loading strategy (prevents duplicate loads)
  requestIdKb: 0,          // Monotonic counter for KB loads (selectStrategy/refresh)
  requestIdTab: 0,          // Monotonic counter for tab lazy-loads (switchTab)
  sortField: 'id',
  sortAsc: true,
  kbCache: {},             // Client-side cache: {SID: {kb, metrics}} — KB never changes
  scoresLoadedFor: null,   // Track which strategy's scores are loaded (lazy)
  scoreChart: null,
  perfChart: null,          // 1Y performance chart instance
  reportScoreChart: null,   // Score chart in report tab
  klinesEnsured: {},       // Track per-strategy K-line sync: {SID: true}
  klinesSyncing: null,     // Currently syncing SID (prevents duplicate sync calls)
};

// ── Category → CSS class ──
const CAT_CSS = {
  '被动投资': 'cat-passive', '动量': 'cat-momentum', '趋势': 'cat-trend',
  '因子': 'cat-factor', '资产配置': 'cat-allocation', '风控': 'cat-risk',
  '多因子': 'cat-multifactor', '行业': 'cat-sector', '均值回归': 'cat-meanrev',
};

// ── ECharts availability check ──
function hasECharts() {
  return typeof echarts !== 'undefined';
}

// ── Number formatting helpers ──
function fmtPct(v) {
  if (v === null || v === undefined || v === '—') return '—';
  const n = parseFloat(v);
  if (isNaN(n)) return '—';
  return n.toFixed(2) + '%';
}

function fmtNum(v, decimals) {
  if (v === null || v === undefined || v === '—') return '—';
  const n = parseFloat(v);
  if (isNaN(n)) return '—';
  return n.toFixed(decimals || 2);
}

function numClass(val, thresholds) {
  if (val === null || val === undefined) return 'num-muted';
  if (val >= thresholds[0]) return 'num-positive';
  if (val >= thresholds[1]) return 'num-warning';
  return 'num-danger';
}

function ddClass(val) {
  if (val === null || val === undefined) return 'num-muted';
  if (val >= -15) return 'num-positive';
  if (val >= -30) return 'num-warning';
  return 'num-danger';
}

// ── DOM helpers ──
function $el(id) {
  return document.getElementById(id);
}

function safeSetHTML(id, html) {
  const el = $el(id);
  if (el) el.innerHTML = html;
}

function safeSetText(id, text) {
  const el = $el(id);
  if (el) el.textContent = text;
}

function safeSetStyle(id, prop, val) {
  const el = $el(id);
  if (el) el.style[prop] = val;
}


// ═══════════════════════════════════════════════════════════════
// API Calls
// ═══════════════════════════════════════════════════════════════

async function apiGet(path) {
  const res = await Auth.fetchGet(path);
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`API ${res.status}: ${txt.slice(0, 200)}`);
  }
  return res.json();
}

async function apiPost(path, body) {
  const res = await Auth.fetchPost(path, body || {});
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`API ${res.status}: ${txt.slice(0, 200)}`);
  }
  return res.json();
}

async function loadStrategies() {
  try {
    const data = await apiGet('/api/strategies');
    state.strategies = data;
    renderTable();
    return data;
  } catch (e) {
    toast('加载策略列表失败: ' + e.message, 'error');
    return [];
  }
}


// ═══════════════════════════════════════════════════════════════
// Table Rendering
// ═══════════════════════════════════════════════════════════════

function getFilteredStrategies() {
  const catFilterEl = $el('category-filter');
  const catFilter = catFilterEl ? catFilterEl.value : 'all';
  let list = [...state.strategies];
  if (catFilter !== 'all') {
    list = list.filter(s => s.category === catFilter);
  }

  const field = state.sortField;
  if (field === 'id') {
    list.sort((a, b) => {
      const na = parseInt(a.id.slice(1)), nb = parseInt(b.id.slice(1));
      return state.sortAsc ? na - nb : nb - na;
    });
  } else if (field === 'dd_val') {
    list.sort((a, b) => {
      const va = a[field] !== null ? a[field] : (state.sortAsc ? -999 : 999);
      const vb = b[field] !== null ? b[field] : (state.sortAsc ? -999 : 999);
      return state.sortAsc ? va - vb : vb - va;
    });
  } else {
    list.sort((a, b) => {
      const va = a[field] !== null ? a[field] : (state.sortAsc ? 9999 : -9999);
      const vb = b[field] !== null ? b[field] : (state.sortAsc ? 9999 : -9999);
      return state.sortAsc ? va - vb : vb - va;
    });
  }
  return list;
}

function renderTable() {
  const list = getFilteredStrategies();
  const tbody = $el('table-body');
  const countEl = $el('table-count');

  if (!tbody) return;

  if (list.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" class="loading-cell">无匹配策略</td></tr>';
    if (countEl) countEl.textContent = '0 个策略';
    return;
  }

  tbody.innerHTML = list.map(s => {
    const annHtml = s.ann_val !== null
      ? `<span class="${numClass(s.ann_val, [20, 10])}">${fmtPct(s.ann_val)}</span>`
      : '<span class="num-muted">—</span>';

    const sharpeHtml = s.sharpe !== null
      ? `<span class="${numClass(s.sharpe, [1.0, 0.5])}">${fmtNum(s.sharpe, 2)}</span>`
      : '<span class="num-muted">—</span>';

    const ddHtml = s.dd_val !== null
      ? `<span class="${ddClass(s.dd_val)}">${fmtPct(s.dd_val)}</span>`
      : '<span class="num-muted">—</span>';

    const calmarHtml = s.calmar !== null
      ? `<span class="${numClass(s.calmar, [1.0, 0.5])}">${fmtNum(s.calmar, 2)}</span>`
      : '<span class="num-muted">—</span>';

    const catClass = CAT_CSS[s.category] || '';
    const selected = s.id === state.selectedId ? ' selected' : '';
    const backtestWin = s.backtest_window || '—';

    return `<tr class="${selected}" data-sid="${s.id}" onclick="selectStrategy('${s.id}')">
      <td class="col-id">${s.id}</td>
      <td class="col-name">${s.name}</td>
      <td class="col-cat"><span class="cat-badge ${catClass}">${s.category_cn || s.category}</span></td>
      <td class="col-num">${annHtml}</td>
      <td class="col-num">${sharpeHtml}</td>
      <td class="col-num">${ddHtml}</td>
      <td class="col-num">${calmarHtml}</td>
      <td class="col-win">${backtestWin}</td>
      <td class="col-act">
        <div class="row-actions">
          <button class="btn-row btn-row-detail" onclick="event.stopPropagation(); selectStrategy('${s.id}')">详情</button>
          <button class="btn-row btn-row-backtest" onclick="event.stopPropagation(); backtestSingleStrategy('${s.id}')" title="运行回测">回测</button>
        </div>
      </td>
    </tr>`;
  }).join('');

  if (countEl) countEl.textContent = `共 ${list.length} 个策略`;

  // Update sort header indicators
  document.querySelectorAll('.data-table th.sortable').forEach(th => {
    const field = th.dataset.field;
    th.classList.toggle('sorted', field === state.sortField);
    th.classList.toggle('asc', field === state.sortField && state.sortAsc);
    th.classList.toggle('desc', field === state.sortField && !state.sortAsc);
  });
}

function toggleSortOrder() {
  state.sortAsc = !state.sortAsc;
  const btn = $el('btn-sort-order');
  if (btn) btn.textContent = state.sortAsc ? '↑' : '↓';
  renderTable();
}

// ── KPI Cards: compute stats from strategy data ──
function updateKpiCards() {
  const list = state.strategies;
  if (!list || list.length === 0) return;

  // 策略总数
  safeSetText('kpi-total', list.length);
  safeSetText('kpi-total-sub', '已维护策略');

  // Filter strategies with valid metrics (exclude pending backtests)
  const valid = list.filter(s => s.ann_val !== null && s.ann_val !== undefined);

  if (valid.length === 0) {
    safeSetText('kpi-best-sharpe', '—');
    safeSetText('kpi-best-sharpe-sub', '待回测');
    safeSetText('kpi-best-ann', '—');
    safeSetText('kpi-best-ann-sub', '待回测');
    safeSetText('kpi-best-dd', '—');
    safeSetText('kpi-best-dd-sub', '待回测');
    return;
  }

  // 最优夏普 (?? treats 0 as valid, unlike ||)
  const bestSharpe = valid.reduce((a, b) => (a.sharpe ?? -999) > (b.sharpe ?? -999) ? a : b);
  safeSetText('kpi-best-sharpe', `${bestSharpe.id} · ${fmtNum(bestSharpe.sharpe, 2)}`);
  safeSetText('kpi-best-sharpe-sub', bestSharpe.name);

  // 最优年化
  const bestAnn = valid.reduce((a, b) => (a.ann_val ?? -999) > (b.ann_val ?? -999) ? a : b);
  safeSetText('kpi-best-ann', `${bestAnn.id} · ${fmtPct(bestAnn.ann_val)}`);
  safeSetText('kpi-best-ann-sub', bestAnn.name);

  // 最低回撤 (least negative = highest dd_val)
  const bestDD = valid.reduce((a, b) => (a.dd_val ?? -999) > (b.dd_val ?? -999) ? a : b);
  safeSetText('kpi-best-dd', `${bestDD.id} · ${fmtPct(bestDD.dd_val)}`);
  safeSetText('kpi-best-dd-sub', bestDD.name);
}


// Table header click → sort
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.data-table th.sortable').forEach(th => {
    th.addEventListener('click', () => {
      const field = th.dataset.field;
      if (state.sortField === field) {
        state.sortAsc = !state.sortAsc;
      } else {
        state.sortField = field;
        state.sortAsc = (field === 'dd_val');
      }
      const btn = $el('btn-sort-order');
      if (btn) btn.textContent = state.sortAsc ? '↑' : '↓';
      // Sync dropdown to current sort field
      const dropdown = $el('sort-field');
      if (dropdown) dropdown.value = state.sortField;
      renderTable();
    });
  });

  // Sort dropdown change → update state and re-render
  const sortDropdown = $el('sort-field');
  if (sortDropdown) {
    sortDropdown.addEventListener('change', () => {
      state.sortField = sortDropdown.value;
      state.sortAsc = (state.sortField === 'dd_val');
      const btn = $el('btn-sort-order');
      if (btn) btn.textContent = state.sortAsc ? '↑' : '↓';
      renderTable();
    });
  }

  // Sync initial sort arrow to match state.sortAsc = true
  const sortBtn = $el('btn-sort-order');
  if (sortBtn) sortBtn.textContent = state.sortAsc ? '↑' : '↓';
});


// ═══════════════════════════════════════════════════════════════
// Strategy Selection → Detail Panel (with race-condition guard)
// ═══════════════════════════════════════════════════════════════

const LOADING_HTML = '<div style="display:flex;align-items:center;justify-content:center;padding:2rem;gap:0.5rem;color:var(--text-muted)"><span class="spinner"></span> 数据加载中...</div>';

async function selectStrategy(sid) {
  // ── Guard: skip if already loading the same strategy ──
  if (state.loadingSid === sid) return;
  state.loadingSid = sid;

  // ── Invalidate any in-flight requests ──
  state.selectedId = sid;
  state.requestIdKb++;
  const reqId = state.requestIdKb;

  // ── Clear all content & show loading / click-to-load ──
  safeSetHTML('kb-content', LOADING_HTML);
  safeSetHTML('signal-content', '<p class="muted">点击「📡 今日信号」Tab 加载</p>');
  safeSetHTML('rebalances-content', '<p class="muted">点击「🔄 调仓记录」Tab 加载</p>');
  safeSetHTML('report-content', '<p class="muted">点击「📊 回测报告」Tab 加载</p>');
  safeSetHTML('source-content', '<p class="muted">点击「📝 策略源码」Tab 加载</p>');

  // ── Re-render table to show selection highlight ──
  renderTable();

  // ── Show detail panel ──
  safeSetStyle('panel-detail', 'display', 'block');
  safeSetText('detail-title', `📋 ${sid} 策略详情`);

  // ── Reset to KB tab (first tab) ──
  switchTab('tab-kb');

  // ── Reset score state ──
  state.scoresLoadedFor = null;
  safeDispose(state.scoreChart); state.scoreChart = null;
  safeDispose(state.perfChart); state.perfChart = null;
  safeDispose(state.reportScoreChart); state.reportScoreChart = null;

  // ── Scroll to detail panel ──
  const panel = $el('panel-detail');
  if (panel) {
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // ── Load KB data (metrics may have changed, KB is cached) ──
  const cached = state.kbCache[sid];
  if (cached) {
    // Render KB from cache instantly
    if (reqId === state.requestIdKb) {
      renderKB(cached.kb);
    }
  }

  try {
    const detailData = cached
      ? Promise.resolve(cached.metrics)
      : apiGet('/api/strategies/' + sid).catch(e => ({ _error: e.message }));

    const data = await detailData;

    // Check race-condition guard
    if (reqId !== state.requestIdKb) return;

    // Render KB + metrics from detail data
    if (!cached) {
      if (data._error) {
        safeSetHTML('kb-content', `<p class="muted">❌ 知识库加载失败: ${data._error}</p>`);
      } else {
        renderKB(data);
        // Cache for future use (KB data never changes)
        state.kbCache[sid] = {
          kb: data,
          metrics: data,
        };
      }
    }
  } catch (e) {
    if (reqId === state.requestIdKb) {
      safeSetHTML('kb-content', `<p class="muted">❌ 加载失败: ${e.message}</p>`);
    }
  } finally {
    if (state.loadingSid === sid) {
      state.loadingSid = null;
    }
  }
}

// ── Safe chart disposal (guards against double-dispose, DOM removal, etc.) ──
function safeDispose(chartRef) {
  try {
    if (chartRef && !chartRef.isDisposed()) {
      chartRef.dispose();
    }
  } catch (e) {
    // Ignore disposal errors (DOM already removed, etc.)
  }
}

function closeDetail() {
  state.selectedId = null;
  state.loadingSid = null;
  state.requestIdKb++;
  state.requestIdTab++;
  state.scoresLoadedFor = null;  // Reset so report loads fresh next time
  safeSetStyle('panel-detail', 'display', 'none');
  // Dispose all charts to free memory
  safeDispose(state.scoreChart); state.scoreChart = null;
  safeDispose(state.perfChart); state.perfChart = null;
  safeDispose(state.reportScoreChart); state.reportScoreChart = null;
  renderTable();
}

// ── K-line sync: ensure fresh data before loading signal/rebalances/report ──
async function ensureKlinesFresh(sid) {
  // Already ensured for this strategy → skip
  if (state.klinesEnsured[sid]) return true;

  // Already syncing this strategy → wait for it
  if (state.klinesSyncing === sid) {
    // Poll until done (max 15s)
    for (let i = 0; i < 30; i++) {
      await new Promise(r => setTimeout(r, 500));
      if (state.klinesEnsured[sid]) return true;
    }
    return false;
  }

  state.klinesSyncing = sid;

  try {
    const res = await apiPost('/api/klines/ensure/' + sid);
    state.klinesEnsured[sid] = true;
    state.klinesSyncing = null;

    if (res.total_new_rows > 0) {
      toast(`📡 ${sid}: ${res.message}`, 'success');
    }
    return true;
  } catch (e) {
    state.klinesSyncing = null;
    toast(`K线同步失败: ${e.message}`, 'error');
    return false;
  }
}

async function switchTab(tabId) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

  const tabEl = document.querySelector(`[data-tab="${tabId}"]`);
  const contentEl = $el(tabId);

  if (tabEl) tabEl.classList.add('active');
  if (contentEl) contentEl.classList.add('active');

  // ── Tabs that need fresh K-line data: ensure sync first ──
  const klineTabs = ['tab-signal', 'tab-rebalances', 'tab-report'];
  if (klineTabs.includes(tabId) && state.selectedId) {
    const sid = state.selectedId;
    const containerId = tabId.replace('tab-', '') + '-content';
    const container = $el(containerId);

    // Show K-line sync status if this is a first-time load
    if (!state.klinesEnsured[sid] && container &&
        (container.textContent.includes('点击') || container.innerHTML.includes('数据加载中'))) {
      container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;padding:2rem;gap:0.5rem;color:var(--accent-cyan)"><span class="spinner"></span> 📡 K线数据获取中，请稍候...</div>';
    }

    const ensured = await ensureKlinesFresh(sid);
    if (!ensured) {
      // Sync failed — show error in the tab content
      safeSetHTML(containerId, '<p class="muted">❌ K线数据同步失败，请检查网络后重试</p>');
      return;
    }
  }

  // Lazy-load signal when user clicks "今日信号" tab
  if (tabId === 'tab-signal' && state.selectedId) {
    const sid = state.selectedId;
    const container = $el('signal-content');
    if (container && (container.textContent.includes('点击') || container.innerHTML.includes('K线数据获取中'))) {
      container.innerHTML = LOADING_HTML;
      state.requestIdTab++;
      const reqId = state.requestIdTab;
      try {
        const data = await apiGet('/api/signals/' + sid);
        if (reqId === state.requestIdTab) renderSignal(data);
      } catch (e) {
        if (reqId === state.requestIdTab) {
          safeSetHTML('signal-content', `<p class="muted">❌ 信号加载失败: ${e.message}</p>`);
        }
      }
    }
  }

  // Lazy-load rebalances when user clicks "调仓记录" tab
  if (tabId === 'tab-rebalances' && state.selectedId) {
    const sid = state.selectedId;
    const container = $el('rebalances-content');
    if (container && (container.textContent.includes('点击') || container.innerHTML.includes('K线数据获取中'))) {
      container.innerHTML = LOADING_HTML;
      state.requestIdTab++;
      loadAndRenderRebalances(sid, state.requestIdTab);
    }
  }

  // Lazy-load backtest report when user clicks "回测报告" tab
  if (tabId === 'tab-report' && state.selectedId && state.selectedId !== state.scoresLoadedFor) {
    const sid = state.selectedId;
    const container = $el('report-content');
    if (container) {
      container.innerHTML = LOADING_HTML;
      state.requestIdTab++;
      loadAndRenderReport(sid, state.requestIdTab);
    }
  }

  // Lazy-load source code when user clicks "策略源码" tab
  if (tabId === 'tab-source' && state.selectedId) {
    const sid = state.selectedId;
    const srcContainer = $el('source-content');
    if (srcContainer && srcContainer.textContent.includes('点击')) {
      srcContainer.innerHTML = LOADING_HTML;
      state.requestIdTab++;
      loadAndRenderSource(sid, state.requestIdTab);
    }
  }
}


// ═══════════════════════════════════════════════════════════════
// Per-Row Actions
// ═══════════════════════════════════════════════════════════════

async function refreshSingleStrategy(sid) {
  toast(`刷新 ${sid} 信号...`, 'loading');

  // Ensure K-line data is fresh before generating signals
  const ensured = await ensureKlinesFresh(sid);
  if (!ensured) {
    toast(`${sid} K线同步失败`, 'error');
    return;
  }

  try {
    await apiGet('/api/signals/' + sid);
    // Refresh the detail panel if this strategy is currently selected
    if (sid === state.selectedId) {
      state.requestIdKb++;
      const reqId = state.requestIdKb;
      safeSetHTML('signal-content', LOADING_HTML);
      try {
        const data = await apiGet('/api/signals/' + sid);
        if (reqId === state.requestIdKb) renderSignal(data);
      } catch (e) {
        if (reqId === state.requestIdKb) {
          safeSetHTML('signal-content', `<p class="muted">❌ 信号加载失败: ${e.message}</p>`);
        }
      }
    }
    toast(`${sid} 信号已刷新`, 'success');
  } catch (e) {
    toast(`${sid} 刷新失败: ${e.message}`, 'error');
  }
}

async function backtestSingleStrategy(sid) {
  toast(`⏳ 正在对 ${sid} 执行完整窗口回测，请耐心等待...`, 'loading');
  try {
    const res = await apiPost('/api/backtest/' + sid);
    toast(`✅ ${sid} 回测完成 — 年化 ${res.annual_return} | 夏普 ${res.sharpe} | 回撤 ${res.max_drawdown}`, 'success');
    // Refresh strategy table to show updated metrics
    await loadStrategies();
    updateKpiCards();
    // If this strategy is currently selected, refresh its detail too
    if (sid === state.selectedId) {
      state.kbCache = {};  // Clear cache to pick up new metrics
      state.requestIdKb++;
      const reqId = state.requestIdKb;
      try {
        const detailData = await apiGet('/api/strategies/' + sid);
        if (reqId === state.requestIdKb) {
          renderKB(detailData);
          state.kbCache[sid] = { kb: detailData, metrics: detailData };
        }
      } catch (e) {
        // Silently fail — table is already refreshed
      }
    }
  } catch (e) {
    toast(`${sid} 回测失败: ${e.message}`, 'error');
  }
}


// ═══════════════════════════════════════════════════════════════
// Signal Rendering
// ═══════════════════════════════════════════════════════════════

function renderSignal(data) {
  const container = $el('signal-content');
  if (!container) return;

  if (!data || data.error) {
    container.innerHTML = '<p class="muted">❌ 信号数据不可用</p>';
    return;
  }

  const { signal_date, data_start, data_end, trading_days,
          assets = [], actions = [], holdings = [], has_signals } = data;

  let html = `
    <div style="display:flex;gap:2rem;margin-bottom:1rem;flex-wrap:wrap;font-size:0.78rem;color:var(--text-muted)">
      <span>📅 信号日期: <strong style="color:var(--accent-cyan)">${signal_date}</strong></span>`;

  // Only show data window info if available (cached signals don't have this)
  if (data_start && data_end && trading_days) {
    html += `<span>📡 数据窗口: ${data_start} ~ ${data_end} (${trading_days}天)</span>`;
  }

  html += `</div>`;

  // Staleness warning — when data is behind today (API sync may have failed)
  if (data.data_stale && data.staleness_msg) {
    html += `<div style="margin:0.5rem 0;padding:0.5rem 0.75rem;
      background:oklch(0.12 0.06 45);border:1px solid oklch(0.32 0.12 45);
      border-radius:var(--radius-sm);color:var(--accent-amber);font-size:0.78rem">
      &#9888;&#65039; ${data.staleness_msg}
    </div>`;
  }

  if (!has_signals) {
    html += '<p style="color:var(--text-secondary)">✅ 今日无需操作，维持现有持仓。</p>';
  } else {
    html += '<p style="color:var(--accent-amber);margin-bottom:0.5rem">📋 今日需操作:</p>';
    html += '<div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-bottom:1rem">';
    actions.forEach(a => {
      const emoji = a.action === 'BUY' ? '🟢' : '🔴';
      const label = a.action === 'BUY' ? '加仓' : '减仓';
      html += `<span style="padding:4px 12px;background:var(--bg-primary);border:1px solid var(--border);border-radius:var(--radius-sm);font-size:0.78rem">
        ${emoji} <strong>${label}</strong> ${a.code} ${a.name}: ${a.change_pct}%
      </span>`;
    });
    html += '</div>';
  }

  // Signal detail table
  html += `<table class="signal-table">
    <thead><tr>
      <th>代码</th><th>名称</th><th>目标权重</th><th>上期权重</th><th>变动</th><th>操作</th>
    </tr></thead><tbody>`;

  assets.forEach(a => {
    let actionHtml;
    if (a.change > 0.001) {
      actionHtml = '<span class="signal-action-buy">🟢 加仓</span>';
    } else if (a.change < -0.001) {
      actionHtml = '<span class="signal-action-sell">🔴 减仓</span>';
    } else if (a.target_weight > 0.001) {
      actionHtml = '<span class="signal-action-hold">🟡 持有</span>';
    } else {
      actionHtml = '<span class="signal-action-hold">⚪ 空仓</span>';
    }

    const changeStr = a.change >= 0 ? `+${(a.change*100).toFixed(1)}%` : `${(a.change*100).toFixed(1)}%`;
    const changeCls = a.change > 0.001 ? 'signal-action-buy' : (a.change < -0.001 ? 'signal-action-sell' : '');

    html += `<tr>
      <td style="font-family:var(--font-mono)">${a.code}</td>
      <td>${a.name}</td>
      <td style="font-family:var(--font-mono)">${(a.target_weight*100).toFixed(1)}%</td>
      <td style="font-family:var(--font-mono)">${(a.prev_weight*100).toFixed(1)}%</td>
      <td style="font-family:var(--font-mono)" class="${changeCls}">${changeStr}</td>
      <td>${actionHtml}</td>
    </tr>`;
  });

  html += '</tbody></table>';

  // Holdings summary
  if (holdings.length > 0) {
    html += '<div style="margin-top:1rem"><strong style="font-size:0.8rem">💼 建议持仓:</strong></div>';
    html += '<div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-top:0.5rem">';
    holdings.forEach(h => {
      html += `<span style="padding:4px 10px;background:oklch(0.18 0.04 145);border:1px solid oklch(0.28 0.06 145);border-radius:var(--radius-sm);font-size:0.75rem;font-family:var(--font-mono)">
        ${h.code} ${h.name}: ${(h.weight*100).toFixed(1)}%
      </span>`;
    });
    html += '</div>';
  } else {
    html += '<p style="margin-top:1rem;color:var(--text-muted)">(空仓/货币)</p>';
  }

  container.innerHTML = html;
}


// ═══════════════════════════════════════════════════════════════
// KB & Metrics Rendering
// ═══════════════════════════════════════════════════════════════

function renderKB(data) {
  const container = $el('kb-content');
  if (!container) return;

  if (!data) {
    container.innerHTML = '<p class="muted">知识库数据不可用</p>';
    return;
  }

  // Merge process_desc into intro if available
  let introContent = data.intro || '';
  if (data.process_desc) {
    const lines = data.process_desc.split('\n').filter(l => l.trim());
    if (lines.length > 0) {
      introContent += '\n\n执行流程：\n' + lines.join('\n');
    }
  }

  const sections = [
    ['📖 策略简介', introContent],
    ['🎯 择股逻辑', data.stock_selection],
    ['⏱️ 择时逻辑', data.market_timing],
    ['📐 使用因子', data.factors],
    ['🔄 调仓节奏', data.rebalance],
    ['✅ 优势', data.strengths],
    ['⚠️ 劣势', data.weaknesses],
  ];

  let html = '';

  // Source URL
  if (data.source_url) {
    html += `<div class="kb-section">
      <h4>📎 策略来源</h4>
      <p>${data.source_url}</p>
    </div>`;
  }

  sections.forEach(([title, content]) => {
    if (content) {
      html += `<div class="kb-section">
        <h4>${title}</h4>
        <p>${content}</p>
      </div>`;
    }
  });

  if (data.backtest && Object.keys(data.backtest).length > 0) {
    html += '<div class="kb-section"><h4>⚙️ 回测参数</h4><div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:0.75rem">';
    Object.entries(data.backtest).forEach(([k, v]) => {
      html += `<div style="color:var(--text-muted)">${k}</div><div style="color:var(--text-secondary);font-family:var(--font-mono)">${v}</div>`;
    });
    html += '</div></div>';
  }

  container.innerHTML = html || '<p class="muted">无知识库数据</p>';
}

// ═══════════════════════════════════════════════════════════════
// Score Chart (相关图表 Tab)
// ═══════════════════════════════════════════════════════════════

const SERIES_COLORS = [
  '#4FC3F7', '#81C784', '#FFB74D', '#E57373', '#BA68C8',
  '#4DD0E1', '#AED581', '#FF8A65', '#7986CB', '#9575CD',
  '#90CAF9', '#A5D6A7', '#FFCC80', '#EF9A9A', '#CE93D8', '#80DEEA',
];

function chartBaseOpt() {
  return {
    backgroundColor: 'transparent',
    grid: { left: 60, right: 30, top: 50, bottom: 55 },
    toolbox: {
      feature: {
        dataZoom: { yAxisIndex: 'none' },
        restore: {},
        saveAsImage: { pixelRatio: 2 },
      },
      right: 10, top: 5,
      iconStyle: { borderColor: 'oklch(0.42 0.02 210)' },
      emphasis: { iconStyle: { borderColor: 'oklch(0.72 0.16 215)' } },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'oklch(0.12 0.02 210)',
      borderColor: 'oklch(0.28 0.03 210)',
      textStyle: { color: 'oklch(0.93 0.01 210)', fontSize: 12 },
    },
    legend: {
      type: 'scroll',
      top: 0,
      right: 0,
      textStyle: { color: 'oklch(0.65 0.02 210)', fontSize: 10 },
      pageTextStyle: { color: 'oklch(0.42 0.02 210)' },
    },
    xAxis: {
      type: 'category',
      axisLine: { lineStyle: { color: 'oklch(0.22 0.03 210)' } },
      axisTick: { show: false },
      axisLabel: { color: 'oklch(0.42 0.02 210)', fontSize: 10 },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: 'oklch(0.42 0.02 210)', fontSize: 10 },
      splitLine: { lineStyle: { color: 'oklch(0.15 0.02 210)' } },
    },
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      { type: 'slider', start: 0, end: 100, height: 20, bottom: 30,
        borderColor: 'oklch(0.22 0.03 210)',
        backgroundColor: 'oklch(0.10 0.02 210)',
        fillerColor: 'oklch(0.18 0.04 215)',
        textStyle: { color: 'oklch(0.42 0.02 210)' },
      },
    ],
  };
}

// ═══════════════════════════════════════════════════════════════
// Rebalance History Rendering
// ═══════════════════════════════════════════════════════════════

async function loadAndRenderRebalances(sid, reqId) {
  const container = $el('rebalances-content');
  if (!container) return;

  try {
    const data = await apiGet('/api/strategies/' + sid + '/rebalances');
    if (reqId !== state.requestIdTab) return;  // Race-condition guard
    const { total_dates, rebalances } = data;

    if (!rebalances || rebalances.length === 0) {
      container.innerHTML = '<p class="muted">暂无调仓记录（该策略可能为买入持有或无显著调仓）</p>';
      return;
    }

    let html = `<p style="font-size:0.78rem;color:var(--text-muted);margin-bottom:0.75rem">📋 最近 ${rebalances.length} 次调仓（共计 ${total_dates} 次调仓日）</p>`;

    // Grouped by date: newest date first
    rebalances.reverse().forEach((record, idx) => {
      const { date, total_buy, total_sell, changes } = record;

      // Date header
      const buyBadge = total_buy > 0 ? `<span style="color:var(--accent-green);font-weight:600">+${total_buy} 加仓</span>` : '';
      const sellBadge = total_sell > 0 ? `<span style="color:var(--accent-red);font-weight:600">-${total_sell} 减仓</span>` : '';
      const sep = total_buy > 0 && total_sell > 0 ? ' · ' : '';

      html += `<div class="rebalance-group" style="margin-bottom:1rem;border:1px solid var(--border);border-radius:var(--radius-md);overflow:hidden">
        <div style="display:flex;justify-content:space-between;align-items:center;padding:0.5rem 0.75rem;background:var(--bg-primary);border-bottom:1px solid var(--border)">
          <span style="font-weight:600;font-size:0.82rem">📅 ${date}</span>
          <span style="font-size:0.75rem">${buyBadge}${sep}${sellBadge}</span>
        </div>
        <table class="signal-table" style="margin:0">
          <thead><tr>
            <th>代码</th><th>名称</th><th>原权重</th><th>目标权重</th><th>变动</th><th>方向</th>
          </tr></thead><tbody>`;

      changes.forEach(r => {
        const changeCls = r.change_pct > 0 ? 'signal-action-buy' : 'signal-action-sell';
        const actionCls = r.action === '加仓' ? 'signal-action-buy' : 'signal-action-sell';
        html += `<tr>
          <td style="font-family:var(--font-mono)">${r.code}</td>
          <td>${r.name}</td>
          <td style="font-family:var(--font-mono)">${r.from_weight}%</td>
          <td style="font-family:var(--font-mono)">${r.to_weight}%</td>
          <td style="font-family:var(--font-mono)" class="${changeCls}">${r.change_pct > 0 ? '+' : ''}${r.change_pct}%</td>
          <td class="${actionCls}">${r.action}</td>
        </tr>`;
      });

      html += '</tbody></table></div>';
    });

    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = `<p class="muted">❌ 调仓记录加载失败: ${e.message}</p>`;
  }
}


// ═══════════════════════════════════════════════════════════════
// Backtest Report Rendering (process desc + diagnostics + chart)
// ═══════════════════════════════════════════════════════════════

async function loadAndRenderReport(sid, reqId) {
  const container = $el('report-content');
  if (!container) return;

  // Build report from multiple data sources
  let html = '';
  let hasChart = false;
  let hasPerfChart = false;
  let scoreData = null;
  let perfData = null;

  // 1. Diagnostics (from API) — Process description now merged into intro (renderKB)
  try {
    const diag = await apiGet('/api/strategies/' + sid + '/diagnostics');
    if (reqId !== state.requestIdTab) return;

    const params = diag.parameters || {};
    const scores = diag.scores || {};
    const scoreDetails = diag.score_details || {};
    const holdings = diag.holdings || {};

    // Diagnostics table
    if (Object.keys(params).length > 0) {
      html += '<div class="kb-section"><h4>📊 最新诊断参数（' + (diag.latest_date || '—') + '）</h4>';
      html += '<table class="signal-table"><thead><tr><th>参数</th><th>当前值</th></tr></thead><tbody>';
      Object.entries(params).forEach(([k, v]) => {
        html += `<tr><td>${k}</td><td style="font-family:var(--font-mono)">${v}</td></tr>`;
      });
      html += '</tbody></table></div>';
    }

    // Scores table (for scoring strategies)
    if (Object.keys(scores).length > 0) {
      html += '<div class="kb-section"><h4>🎯 ETF 动量得分</h4>';
      html += '<table class="signal-table"><thead><tr><th>ETF</th><th>得分</th></tr></thead><tbody>';
      const sorted = Object.entries(scores).sort((a, b) => b[1] - a[1]);
      sorted.forEach(([name, score]) => {
        const sv = (score != null && !isNaN(score)) ? score.toFixed(4) : '—';
        html += `<tr><td>${name}</td><td style="font-family:var(--font-mono)">${sv}</td></tr>`;
      });
      html += '</tbody></table></div>';
    }

    // Score breakdown table (年化收益 + R² + 综合得分 — for strategies that expose detail)
    if (Object.keys(scoreDetails).length > 0) {
      // Detect S18-specific fields (RSRS + 25d/200d momentum decomposition)
      const hasRsrs = Object.values(scoreDetails).some(d => d.rsrs && Object.keys(d.rsrs).length > 0);
      const hasReversal = Object.values(scoreDetails).some(d => d.mom_25d !== undefined && d.mom_200d !== undefined);

      if (hasReversal) {
        // S18-specific: RSRS增强反转动量 得分明细
        html += '<div class="kb-section"><h4>📐 动量得分明细（RSRS增强反转动量）</h4>';
        html += '<table class="signal-table"><thead><tr>';
        html += '<th>ETF</th><th>25日动量</th><th>200日动量</th><th>综合得分</th>';
        if (hasRsrs) html += '<th>RSRS Beta</th><th>RSRS z-score</th><th>RSRS通过</th>';
        html += '</tr></thead><tbody>';
        const sortedDetails = Object.entries(scoreDetails).sort((a, b) => b[1].score - a[1].score);
        sortedDetails.forEach(([name, d]) => {
          const scoreCls = d.score >= 0 ? 'signal-action-buy' : 'signal-action-sell';
          const mom25Cls = d.mom_25d >= 0 ? 'signal-action-buy' : 'signal-action-sell';
          const mom200Cls = d.mom_200d >= 0 ? 'signal-action-buy' : 'signal-action-sell';
          html += `<tr>
            <td>${name}</td>
            <td style="font-family:var(--font-mono)" class="${mom25Cls}">${(d.mom_25d || 0).toFixed(4)}</td>
            <td style="font-family:var(--font-mono)" class="${mom200Cls}">${(d.mom_200d || 0).toFixed(4)}</td>
            <td style="font-family:var(--font-mono);font-weight:600" class="${scoreCls}">${(d.score || 0).toFixed(4)}</td>`;
          if (hasRsrs) {
            const rsrs = d.rsrs || {};
            const passCls = rsrs.rsrs_pass ? 'signal-action-buy' : 'signal-action-sell';
            html += `<td style="font-family:var(--font-mono)">${(rsrs.rsrs_beta || 0).toFixed(4)}</td>
              <td style="font-family:var(--font-mono)">${(rsrs.rsrs_zscore || 0).toFixed(2)}</td>
              <td class="${passCls}" style="font-weight:600">${rsrs.rsrs_pass ? '✅' : '❌'}</td>`;
          }
          html += '</tr>';
        });
        html += '</tbody></table>';
        html += '<p style="font-size:0.7rem;color:var(--text-muted);margin-top:0.25rem">综合得分 = 25日动量 − (200日动量 / 6) | RSRS Beta = log(H)~log(L) OLS 斜率 | z-score < −2.0 排除</p>';
        html += '</div>';
      } else {
        // Standard: 年化收益 × R² format (S4, S15, S16, S17, S19, etc.)
        html += '<div class="kb-section"><h4>📐 动量得分明细（年化收益 × R²）</h4>';
        html += '<table class="signal-table"><thead><tr><th>ETF</th><th>年化收益</th><th>R²</th><th>综合得分</th></tr></thead><tbody>';
        const sortedDetails = Object.entries(scoreDetails).sort((a, b) => b[1].score - a[1].score);
        sortedDetails.forEach(([name, d]) => {
          const annCls = (d.ann_return || 0) >= 0 ? 'signal-action-buy' : 'signal-action-sell';
          const r2Cls = (d.r_squared || 0) >= 0.7 ? 'signal-action-buy' : ((d.r_squared || 0) >= 0.3 ? '' : 'signal-action-sell');
          const scoreCls = (d.score || 0) >= 0 ? 'signal-action-buy' : 'signal-action-sell';
          const annV = d.ann_return != null ? (d.ann_return*100).toFixed(2) : '—';
          const r2V = d.r_squared != null ? d.r_squared.toFixed(4) : '—';
          const scoreV = d.score != null ? d.score.toFixed(4) : '—';
          html += `<tr>
            <td>${name}</td>
            <td style="font-family:var(--font-mono)" class="${annCls}">${annV}%</td>
            <td style="font-family:var(--font-mono)" class="${r2Cls}">${r2V}</td>
            <td style="font-family:var(--font-mono);font-weight:600" class="${scoreCls}">${scoreV}</td>
          </tr>`;
        });
        html += '</tbody></table>';
        html += '<p style="font-size:0.7rem;color:var(--text-muted);margin-top:0.25rem">年化收益 = exp(日斜率×250)−1 | R² 越接近1趋势越"干净" | 综合得分 = 年化收益 × R²</p>';
        html += '</div>';
      }
    }

    // Holdings
    if (Object.keys(holdings).length > 0) {
      html += '<div class="kb-section"><h4>💼 当前持仓</h4>';
      html += '<div style="display:flex;gap:0.5rem;flex-wrap:wrap">';
      Object.entries(holdings).forEach(([code, w]) => {
        const wv = (w != null && !isNaN(w)) ? (w*100).toFixed(1) : '0.0';
        html += `<span style="padding:4px 10px;background:oklch(0.18 0.04 145);border:1px solid oklch(0.28 0.06 145);border-radius:var(--radius-sm);font-size:0.75rem;font-family:var(--font-mono)">${code}: ${wv}%</span>`;
      });
      html += '</div></div>';
    }
  } catch (e) {
    html += `<p class="muted">⚠️ 诊断数据不可用: ${e.message}</p>`;
  }

  // 2. One-Year Performance vs Index (new)
  try {
    perfData = await apiGet('/api/strategies/' + sid + '/perf-1y');
    if (reqId !== state.requestIdTab) return;
    if (perfData && perfData.status === 'done' && perfData.dates && perfData.dates.length > 0) {
      hasPerfChart = true;
    }
  } catch (e) {
    // 1Y perf not available — will skip chart
  }

  // 3. Scoring chart (for scoring-type strategies)
  try {
    scoreData = await apiGet('/api/scores/' + sid);
    if (reqId !== state.requestIdTab) return;
    if (scoreData && scoreData.dates && scoreData.dates.length > 0) {
      hasChart = true;
    }
  } catch (e) {
    // No scoring data — chart won't be rendered
  }

  // ── Render 1Y Performance section BEFORE scoring chart ──
  if (hasPerfChart) {
    const m = perfData.metrics;
    const retCls = m.strategy_return >= 0 ? 'signal-action-buy' : 'signal-action-sell';
    const exCls = (m.excess_return || 0) >= 0 ? 'signal-action-buy' : 'signal-action-sell';

    // Determine if we have real index data (not just placeholder)
    const hasIdx = perfData.index_nav && perfData.index_nav.length > 0;
    const fmtIdxPct = (v) => (v !== null && v !== undefined) ? v.toFixed(2) + '%' : '—';

    // Metrics table
    html += '<div class="kb-section"><h4>📅 最近一年业绩 vs 上证指数</h4>';
    html += `<p style="font-size:0.72rem;color:var(--text-muted);margin-bottom:0.5rem">${m.period_start} ~ ${m.period_end} · ${m.trading_days} 个交易日</p>`;
    html += '<table class="signal-table" style="margin-bottom:1rem"><thead><tr>';
    html += '<th>指标</th><th>策略</th><th>上证指数</th><th>超额</th>';
    html += '</tr></thead><tbody>';

    // 累计收益
    const sr = m.strategy_return != null ? m.strategy_return.toFixed(2) : '—';
    const ir = hasIdx && m.index_return != null ? m.index_return.toFixed(2) : '—';
    const exr = hasIdx && m.excess_return != null ? m.excess_return.toFixed(2) : '—';
    html += `<tr>
      <td>累计收益</td>
      <td class="${retCls}" style="font-family:var(--font-mono)">${sr}%</td>
      <td style="font-family:var(--font-mono)">${ir !== '—' ? ir + '%' : '—'}</td>
      <td class="${exCls}" style="font-family:var(--font-mono)">${exr !== '—' ? exr + '%' : '—'}</td>
    </tr>`;

    // 年化收益
    const sar = m.strategy_ann_return != null ? m.strategy_ann_return.toFixed(2) : '—';
    const iar = hasIdx && m.index_ann_return != null ? m.index_ann_return.toFixed(2) : '—';
    const exar = hasIdx && m.excess_ann_return != null ? m.excess_ann_return.toFixed(2) : '—';
    html += `<tr>
      <td>年化收益</td>
      <td style="font-family:var(--font-mono)">${sar}%</td>
      <td style="font-family:var(--font-mono)">${iar !== '—' ? iar + '%' : '—'}</td>
      <td style="font-family:var(--font-mono)">${exar !== '—' ? exar + '%' : '—'}</td>
    </tr>`;

    // 夏普比率
    html += `<tr>
      <td>夏普比率</td>
      <td style="font-family:var(--font-mono)">${m.strategy_sharpe.toFixed(2)}</td>
      <td style="color:var(--text-muted)">—</td>
      <td style="color:var(--text-muted)">—</td>
    </tr>`;

    // 最大回撤
    html += `<tr>
      <td>最大回撤</td>
      <td style="font-family:var(--font-mono)">${m.strategy_max_drawdown.toFixed(2)}%</td>
      <td style="font-family:var(--font-mono)">${hasIdx ? m.index_max_drawdown.toFixed(2) + '%' : '—'}</td>
      <td style="color:var(--text-muted)">—</td>
    </tr>`;

    // 年化波动率
    html += `<tr>
      <td>年化波动率</td>
      <td style="font-family:var(--font-mono)">${m.strategy_volatility.toFixed(2)}%</td>
      <td style="color:var(--text-muted)">—</td>
      <td style="color:var(--text-muted)">—</td>
    </tr>`;

    // Calmar
    html += `<tr>
      <td>Calmar比率</td>
      <td style="font-family:var(--font-mono)">${m.strategy_calmar.toFixed(2)}</td>
      <td style="color:var(--text-muted)">—</td>
      <td style="color:var(--text-muted)">—</td>
    </tr>`;

    // 日胜率
    html += `<tr>
      <td>日胜率</td>
      <td style="font-family:var(--font-mono)">${m.strategy_win_rate.toFixed(1)}%</td>
      <td style="color:var(--text-muted)">—</td>
      <td style="color:var(--text-muted)">—</td>
    </tr>`;

    // Beta / Alpha
    if (m.beta !== null && m.beta !== undefined) {
      html += `<tr>
        <td>Beta (相对上证)</td>
        <td style="font-family:var(--font-mono)">${m.beta.toFixed(2)}</td>
        <td style="color:var(--text-muted)">1.00</td>
        <td style="color:var(--text-muted)">—</td>
      </tr>`;
    }
    if (m.alpha !== null && m.alpha !== undefined) {
      const aCls = m.alpha >= 0 ? 'signal-action-buy' : 'signal-action-sell';
      html += `<tr>
        <td>Alpha (年化)</td>
        <td class="${aCls}" style="font-family:var(--font-mono)">${m.alpha.toFixed(2)}%</td>
        <td style="color:var(--text-muted)">—</td>
        <td style="color:var(--text-muted)">—</td>
      </tr>`;
    }

    // Information Ratio
    if (m.info_ratio !== null && m.info_ratio !== undefined) {
      html += `<tr>
        <td>信息比率</td>
        <td style="font-family:var(--font-mono)">${m.info_ratio.toFixed(2)}</td>
        <td style="color:var(--text-muted)">—</td>
        <td style="color:var(--text-muted)">—</td>
      </tr>`;
    }

    html += '</tbody></table>';

    // Chart placeholder
    html += '<div class="chart-container" id="chart-perf-1y" style="height:380px"></div>';
    html += '</div>';
  }

  // Render scoring chart section
  if (hasChart) {
    html += '<div class="kb-section"><h4>📈 股票池打分曲线</h4>';
    html += '<div class="chart-container" id="chart-scores-report" style="height:380px"></div>';
    html += '</div>';
  }

  container.innerHTML = html;

  // Render 1Y performance chart after DOM is updated
  if (hasPerfChart && hasECharts()) {
    setTimeout(() => renderPerf1YChart(perfData), 100);
  }

  // Render scoring chart after DOM is updated
  if (hasChart && hasECharts()) {
    setTimeout(() => renderScoreChartInline(scoreData), 100);
  }

  // Mark scores as loaded for this strategy (so tab re-click reloads)
  state.scoresLoadedFor = sid;
}

function renderScoreChartInline(data) {
  if (!hasECharts()) return;
  if (!data || !data.assets || !data.asset_names || !data.scores) return;
  const chartDom = $el('chart-scores-report');
  if (!chartDom || chartDom.clientHeight === 0) return;

  // Dispose previous instance to avoid memory leak
  if (state.reportScoreChart) { state.reportScoreChart.dispose(); }
  const chart = echarts.init(chartDom);
  state.reportScoreChart = chart;
  const opt = chartBaseOpt();
  opt.grid = { left: 60, right: 30, top: 40, bottom: 55 };
  opt.title = [{
    text: `${data.strategy_id} ${data.strategy_name} — 股票池打分曲线`,
    left: 10, top: 5,
    textStyle: { color: 'oklch(0.68 0.02 210)', fontSize: 12, fontWeight: 500 },
  }];
  opt.tooltip.valueFormatter = (value) => (value !== null && value !== undefined) ? value.toFixed(4) : '-';
  opt.yAxis.axisLabel.formatter = (v) => v.toFixed(2);
  opt.xAxis.data = data.dates || [];
  opt.series = data.assets.map((code, i) => ({
    name: `${code} ${data.asset_names[code] || ''}`,
    type: 'line', data: data.scores[code] || [],
    smooth: false, symbol: 'none',
    lineStyle: { width: 1.5, color: SERIES_COLORS[i % SERIES_COLORS.length] },
    itemStyle: { color: SERIES_COLORS[i % SERIES_COLORS.length] },
  }));
  chart.setOption(opt, true);
  chart.resize();
}

/**
 * Render 1-Year Performance comparison chart (cumulative return % curve).
 * Transforms NAV data (starting at 1.0) into cumulative return percentages.
 * @param {Object} data — from GET /api/strategies/{sid}/perf-1y
 */
function renderPerf1YChart(data) {
  if (!hasECharts()) return;
  const chartDom = $el('chart-perf-1y');
  if (!chartDom || chartDom.clientHeight === 0) return;

  // Dispose previous instance to avoid memory leak
  if (state.perfChart) { state.perfChart.dispose(); }

  // Transform NAV (starts at 1.0) → cumulative return percentage
  const toReturnPct = (navArr) => (navArr || []).map(v => v != null ? (v - 1) * 100 : null);

  const chart = echarts.init(chartDom);
  state.perfChart = chart;
  const opt = chartBaseOpt();
  opt.grid = { left: 65, right: 30, top: 40, bottom: 55 };
  opt.title = [{
    text: `${data.strategy_id} ${data.strategy_name} vs ${data.index_name} — 最近一年收益率曲线`,
    left: 10, top: 5,
    textStyle: { color: 'oklch(0.68 0.02 210)', fontSize: 12, fontWeight: 500 },
  }];
  opt.tooltip.valueFormatter = (value) => (value !== null && value !== undefined) ? value.toFixed(2) + '%' : '-';
  opt.yAxis.axisLabel.formatter = (v) => v.toFixed(0) + '%';
  opt.xAxis.data = data.dates || [];

  const strategyReturns = toReturnPct(data.strategy_nav);
  const series = [{
    name: `${data.strategy_id} ${data.strategy_name}`,
    type: 'line',
    data: strategyReturns,
    smooth: true,
    symbol: 'none',
    lineStyle: { width: 2, color: '#4FC3F7' },
    itemStyle: { color: '#4FC3F7' },
    areaStyle: {
      color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
        { offset: 0, color: 'rgba(79, 195, 247, 0.15)' },
        { offset: 1, color: 'rgba(79, 195, 247, 0.01)' },
      ]),
    },
  }];

  // Add index series if available
  if (data.index_nav && data.index_nav.length > 0) {
    const indexReturns = toReturnPct(data.index_nav);
    series.push({
      name: data.index_name || '上证指数',
      type: 'line',
      data: indexReturns,
      smooth: true,
      symbol: 'none',
      lineStyle: { width: 1.5, color: '#FFB74D', type: 'dashed' },
      itemStyle: { color: '#FFB74D' },
    });
  }

  // Add baseline at 0%
  series.push({
    name: '零收益线',
    type: 'line',
    data: data.dates.map(() => 0),
    smooth: false,
    symbol: 'none',
    lineStyle: { width: 0.5, color: 'oklch(0.28 0.03 210)', type: 'dotted' },
    itemStyle: { color: 'oklch(0.28 0.03 210)' },
    legendHoverLink: false,
    silent: true,
  });

  opt.series = series;
  chart.setOption(opt, true);
  chart.resize();
}

// ═══════════════════════════════════════════════════════════════
// Actions
// ═══════════════════════════════════════════════════════════════

async function refreshAll() {
  toast('刷新策略列表...', 'loading');
  // Clear caches
  state.kbCache = {};
  state.klinesEnsured = {};
  state.klinesSyncing = null;
  state.strategies = [];
  state.selectedId = null;
  state.loadingSid = null;
  state.requestIdKb++;
  state.requestIdTab++;
  safeSetStyle('panel-detail', 'display', 'none');

  await loadStrategies();
  updateKpiCards();
  toast('刷新完成', 'success');
}

async function triggerBacktest() {
  toast('启动全量回测，约 60-120 秒，请耐心等待...', 'loading');
  try {
    const res = await apiPost('/api/backtest/run');
    toast('回测已启动: ' + res.message, 'loading');

    // Poll for completion
    const poll = setInterval(async () => {
      try {
        const status = await apiGet('/api/charts/status');
        if (status.ready) {
          clearInterval(poll);
          toast('回测完成！正在刷新策略数据...', 'success');
          // Clear caches and reload strategy table
          state.kbCache = {};
          await loadStrategies();
          updateKpiCards();
          toast('策略全景已更新', 'success');
        } else if (status.status === 'error') {
          clearInterval(poll);
          toast('回测失败: ' + status.message, 'error');
        } else {
          toast('⏳ ' + (status.message || '回测中...'), 'loading');
        }
      } catch (e) {
        console.warn('Backtest poll error:', e);
      }
    }, 3000);
  } catch (e) {
    toast('启动回测失败: ' + e.message, 'error');
  }
}

// ═══════════════════════════════════════════════════════════════
// Toast
// ═══════════════════════════════════════════════════════════════

function toast(msg, type) {
  const container = $el('toast-container');
  if (!container) return;

  const el = document.createElement('div');
  el.className = 'toast toast-' + (type || '');
  el.textContent = msg;
  container.appendChild(el);

  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transform = 'translateX(20px)';
    el.style.transition = 'all 200ms ease-out';
    setTimeout(() => el.remove(), 200);
  }, 4000);
}


// ═══════════════════════════════════════════════════════════════
// Clock
// ═══════════════════════════════════════════════════════════════

function updateClock() {
  const now = new Date();
  const str = now.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false,
  });
  safeSetText('header-clock', str);
}


// ═══════════════════════════════════════════════════════════════
// Source Code Rendering
// ═══════════════════════════════════════════════════════════════

async function loadAndRenderSource(sid, reqId) {
  const container = $el('source-content');
  if (!container) return;

  try {
    const data = await apiGet('/api/strategies/' + sid + '/source');
    if (reqId !== state.requestIdTab) return;  // Race-condition guard
    const { file_path, source_code, lines } = data;

    // Escape HTML entities in source code
    const code = source_code || '';
    const escaped = code
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    container.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.75rem">
        <span style="font-size:0.78rem;color:var(--text-muted)">
          📄 <code style="color:var(--accent-cyan);font-family:var(--font-mono)">${file_path}</code>
          · ${lines} 行
        </span>
      </div>
      <div style="background:var(--bg-primary);border:1px solid var(--border);border-radius:var(--radius-md);overflow:hidden">
        <pre style="margin:0;padding:1rem;overflow:auto;max-height:600px;font-family:var(--font-mono);font-size:0.72rem;line-height:1.6;color:var(--text-secondary);white-space:pre;tab-size:4"><code>${escaped}</code></pre>
      </div>`;
  } catch (e) {
    container.innerHTML = `<p class="muted">❌ 源码加载失败: ${e.message}</p>`;
  }
}


// ═══════════════════════════════════════════════════════════════
// Pre-fetch all KB data on load for instant detail rendering
// ═══════════════════════════════════════════════════════════════

async function preFetchAllKB() {
  if (state.strategies.length === 0) return;

  // Fetch KB for all strategies in parallel (max 5 at a time to avoid overwhelming server)
  const sids = state.strategies.map(s => s.id);
  const batchSize = 5;

  for (let i = 0; i < sids.length; i += batchSize) {
    const batch = sids.slice(i, i + batchSize);
    await Promise.all(batch.map(async (sid) => {
      try {
        const data = await apiGet('/api/strategies/' + sid);
        state.kbCache[sid] = { kb: data, metrics: data };
      } catch (e) {
        // Silently fail — will fetch on demand
      }
    }));
  }
}


// ═══════════════════════════════════════════════════════════════
// Auth-aware Init
// ═══════════════════════════════════════════════════════════════

function showLoginPage() {
  const overlay = $el('login-overlay');
  const app = $el('app-main');
  if (overlay) overlay.style.display = 'flex';
  if (app) app.style.display = 'none';
  // Clear any previous error
  const errEl = $el('login-error');
  if (errEl) errEl.style.display = 'none';
  // 桌宠下线（pet.js 监听）
  document.dispatchEvent(new CustomEvent('xm:auth', { detail: { authed: false } }));
}

function showApp() {
  const overlay = $el('login-overlay');
  const app = $el('app-main');
  if (overlay) overlay.style.display = 'none';
  if (app) app.style.display = 'block';
  // 桌宠上线（pet.js 监听；内部按角色门控 + 拉状态）
  document.dispatchEvent(new CustomEvent('xm:auth', { detail: { authed: true } }));
}

// ═══════════════════════════════════════════════════════════════
// 模式切换：主页（home） / 后台（admin）
// 主页展示：策略全景 / 持仓 / 信号 / 报告
// 后台展示：工作日程 / 角色 —— 仅管理员可见切换按钮
// ═══════════════════════════════════════════════════════════════

let _currentMode = 'home';   // 'home' | 'admin'

function isAdminUser() {
  const u = Auth.getUser();
  return !!(u && u.role === 'admin');
}

function applyModeUI(mode) {
  _currentMode = mode;
  const nav = $el('topnav');
  if (nav) nav.classList.toggle('mode-admin', mode === 'admin');
  const inAdmin = mode === 'admin';
  document.body.classList.toggle('mode-admin', inAdmin);
  const btn = $el('mode-switch-btn');
  if (btn) {
    btn.textContent = inAdmin ? '🏠 进入主页' : '🛠️ 进入后台';
    btn.title = inAdmin ? '返回主页' : '进入后台';
    btn.classList.toggle('mode-on', inAdmin);
  }
}

function switchMode() {
  // 仅管理员可进入后台模式
  if (!isAdminUser()) {
    toast('仅管理员可进入后台', 'error');
    return;
  }
  const target = _currentMode === 'admin' ? 'home' : 'admin';
  applyModeUI(target);
  // 进入后台默认落在“工作日程”，进入主页默认落在“策略全景”
  switchView(target === 'admin' ? 'view-agent' : 'view-strategies');
}

function setupModeUI() {
  // 仅管理员展示“进入后台”按钮；非管理员固定主页模式
  if (isAdminUser()) {
    const btn = $el('mode-switch-btn');
    if (btn) btn.style.display = 'inline-flex';
  } else {
    const btn = $el('mode-switch-btn');
    if (btn) btn.style.display = 'none';
    applyModeUI('home');
  }
}

async function handleLogin() {
  const username = ($el('login-username')?.value || '').trim();
  const password = $el('login-password')?.value || '';
  const btn = $el('login-btn');
  const errEl = $el('login-error');

  if (!username || !password) {
    if (errEl) { errEl.textContent = '请输入用户名和密码'; errEl.style.display = 'block'; }
    return;
  }

  if (btn) { btn.disabled = true; btn.textContent = '登录中...'; }
  if (errEl) errEl.style.display = 'none';

  try {
    await Auth.login(username, password);
    showApp();
    // Update user display
    const user = Auth.getUser();
    if (user) {
      safeSetText('header-user', user.display_name || user.username);
    }
    // 模式切换 UI（管理员才显示进入后台按钮）
    setupModeUI();
    // Kick off data loading
    updateClock();
    setInterval(updateClock, 10000);
    await loadStrategies();
    updateKpiCards();
    setTimeout(() => preFetchAllKB(), 500);
  } catch (e) {
    if (errEl) { errEl.textContent = e.message || '登录失败'; errEl.style.display = 'block'; }
    if (btn) { btn.disabled = false; btn.textContent = '登 录'; }
  }
}

function handleLogout() {
  Auth.logout();
  showLoginPage();
}

document.addEventListener('DOMContentLoaded', async () => {
  // ── Auth check ──
  const loggedIn = Auth.init();

  if (!loggedIn) {
    showLoginPage();
    // Bind login form
    const form = $el('login-form');
    if (form) {
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        handleLogin();
      });
    }
    // Bind Enter key
    const pwInput = $el('login-password');
    if (pwInput) {
      pwInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleLogin();
      });
    }
    const unInput = $el('login-username');
    if (unInput) {
      unInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleLogin();
      });
    }
    return;  // Don't load data until authenticated
  }

  // ── Already authenticated ──
  showApp();
  const user = Auth.getUser();
  if (user) {
    safeSetText('header-user', user.display_name || user.username);
  }
  // 模式切换 UI（管理员才显示进入后台按钮）
  setupModeUI();

  updateClock();
  setInterval(updateClock, 10000);
  await loadStrategies();
  updateKpiCards();
  setTimeout(() => preFetchAllKB(), 500);
});

// Resize handler for score chart only
window.addEventListener('resize', () => {
  if (state.scoreChart) state.scoreChart.resize();
  if (state.perfChart) state.perfChart.resize();
  if (state.reportScoreChart) state.reportScoreChart.resize();
});
