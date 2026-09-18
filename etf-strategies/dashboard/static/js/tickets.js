var Tickets = {

  load: async function() {
    const container = document.getElementById('tickets-container');
    container.innerHTML = '<div class="xm-loading">加载中...</div>';

    var params = new URLSearchParams(window._ticketFilter || {});
    try {
      var r = await Auth.fetchGet('/api/tickets?' + params.toString());
      var data = await r.json();
      this.renderList(data);
    } catch (e) {
      container.innerHTML = '<div class="xm-error">加载失败: ' + e.message + '</div>';
    }
  },

  renderList: function(data) {
    var container = document.getElementById('tickets-container');
    var tickets = data.tickets || [];
    if (tickets.length === 0) {
      container.innerHTML = '<div class="xm-empty">暂无工单</div>';
      return;
    }

    var html = '<table class="sched-table"><thead><tr>' +
      '<th>ID</th><th>类型</th><th>标题</th><th>严重度</th><th>状态</th><th>来源任务</th><th>创建时间</th><th>操作</th>' +
      '</tr></thead><tbody>';

    tickets.forEach(function(t) {
      var statusLabel = ({open:'待处理',analyzing:'分析中',in_progress:'处理中',needs_human:'需人工',resolved:'已解决',closed:'已关闭'})[t.status] || t.status;
      var severityIcon = ({p0:'🔴',p1:'🟠',p2:'🟡',p3:'🟢'})[t.severity] || '⚪';
      var kindIcon = t.kind === 'bug' ? '🐛' : '📋';
      html += '<tr class="ticket-row" onclick="Tickets.showDetail(\'' + t.id + '\')">' +
        '<td class="mono">' + t.id.substring(0, 8) + '</td>' +
        '<td>' + kindIcon + ' ' + (t.kind === 'bug' ? 'BUG' : 'REQ') + '</td>' +
        '<td>' + Tickets.esc(t.title) + '</td>' +
        '<td>' + severityIcon + ' ' + t.severity.toUpperCase() + '</td>' +
        '<td><span class="ticket-status ticket-status-' + t.status + '">' + statusLabel + '</span></td>' +
        '<td class="mono">' + Tickets.esc(t.source_task || '—') + '</td>' +
        '<td>' + (t.created_at || '').substring(0, 16) + '</td>' +
        '<td><button class="btn-small" onclick="event.stopPropagation();Tickets.retrigger(\'' + t.id + '\')">🔄 重跑</button></td>' +
        '</tr>';
    });

    html += '</tbody></table>';
    html += '<div class="xm-pager">第 ' + data.page + '/' + data.total_pages + ' 页，共 ' + data.total + ' 条</div>';
    container.innerHTML = html;
  },

  showDetail: async function(id) {
    try {
      var r = await Auth.fetchGet('/api/tickets/' + id);
      var t = await r.json();
      this.renderDetail(t);
    } catch (e) {
      alert('加载工单详情失败: ' + e.message);
    }
  },

  renderDetail: function(t) {
    var detailEl = document.getElementById('ticket-detail');
    var logs = [];
    try { logs = JSON.parse(t.log_entries || '[]'); } catch(e) {}

    var statusLabel = ({open:'待处理',analyzing:'分析中',in_progress:'处理中',needs_human:'需人工',resolved:'已解决',closed:'已关闭'})[t.status] || t.status;
    var severityIcon = ({p0:'🔴',p1:'🟠',p2:'🟡',p3:'🟢'})[t.severity] || '⚪';
    var kindIcon = t.kind === 'bug' ? '🐛' : '📋';

    var html = '<div class="ticket-detail-card">' +
      '<div class="ticket-detail-header">' +
      '<h3>' + kindIcon + ' ' + this.esc(t.title) + ' <span class="ticket-status ticket-status-' + t.status + '">' + statusLabel + '</span></h3>' +
      '<div class="ticket-meta">' +
      '<span>' + severityIcon + ' ' + t.severity.toUpperCase() + '</span> | ' +
      '<span>任务: ' + this.esc(t.source_task || '—') + '</span> | ' +
      '<span>' + (t.created_at || '').substring(0, 16) + '</span>' +
      '</div></div>';

    if (t.description) {
      html += '<div class="ticket-section"><h4>描述</h4><pre class="ticket-desc">' + this.esc(t.description) + '</pre></div>';
    }

    if (logs.length > 0) {
      html += '<div class="ticket-section"><h4>执行日志</h4><div class="ticket-log-timeline">';
      logs.forEach(function(l) {
        html += '<div class="ticket-log-entry">' +
          '<span class="ticket-log-time">' + (l.ts || '').substring(0, 19) + '</span> ' +
          '<span class="ticket-log-step">' + this.esc(l.step) + '</span> ' +
          '<span class="ticket-log-detail">' + this.esc(l.detail || '') + '</span>' +
          '</div>';
      }.bind(this));
      html += '</div></div>';
    }

    if (t.result) {
      html += '<div class="ticket-section"><h4>处理结果</h4><div class="ticket-result">' + marked.parse(t.result) + '</div></div>';
    }

    html += '<div class="ticket-actions">' +
      '<button class="btn-small" onclick="Tickets.retrigger(\'' + t.id + '\')">🔄 重新执行</button> ' +
      '<button class="btn-small btn-secondary" onclick="document.getElementById(\'ticket-detail\').innerHTML=\'\'">✕ 关闭</button>' +
      '</div></div>';

    detailEl.innerHTML = html;
  },

  retrigger: async function(id) {
    try {
      var r = await Auth.fetchPost('/api/tickets/' + id + '/retrigger', {});
      var data = await r.json();
      if (data.started) {
        alert('已提交重新执行，请稍后刷新查看结果');
      } else {
        alert('提交失败: ' + (data.message || data.reason));
      }
    } catch (e) {
      alert('重新触发失败: ' + e.message);
    }
  },

  applyFilter: function() {
    var f = {};
    var kindEl = document.getElementById('ticket-filter-kind');
    var sevEl = document.getElementById('ticket-filter-severity');
    var statusEl = document.getElementById('ticket-filter-status');
    if (kindEl && kindEl.value) f.kind = kindEl.value;
    if (sevEl && sevEl.value) f.severity = sevEl.value;
    if (statusEl && statusEl.value) f.status = statusEl.value;
    window._ticketFilter = f;
    this.load();
  },

  esc: function(s) {
    var d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

};
