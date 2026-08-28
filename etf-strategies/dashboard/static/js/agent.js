/* ═══════════════════════════════════════════════════════════════
   agent.js — 小满角色页（聊天 + 文章）

   依赖：Auth（auth.js 的 fetch 封装 + getHeaders）、marked（CDN 已引入）。
   聊天：POST /api/agent/sessions/{id}/messages → fetch 流式读 SSE。
   文章：GET /api/agent/articles[/{id}]。
   ═══════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const state = { sessionId: null, streaming: false, loaded: false };

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function scrollBottom() {
    const box = document.getElementById('agent-messages');
    if (box) box.scrollTop = box.scrollHeight;
  }

  function switchTab(tab) {
    document.querySelectorAll('.agent-tab').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-tab') === tab);
    });
    document.getElementById('agent-pane-chat').classList.toggle('active', tab === 'chat');
    document.getElementById('agent-pane-articles').classList.toggle('active', tab === 'articles');
    if (tab === 'articles') {
      loadArticles();
      loadSources();
    }
  }

  // ── 初始化（首次进入角色页由 switchView 调用）──
  function load(force) {
    if (!force && state.loaded) return;
    state.loaded = true;
    loadSessions();
    loadArticles();
    loadSources();
    loadStatus();
  }

  // ── 角色状态条 ──
  async function loadStatus() {
    try {
      const resp = await Auth.fetchGet('/api/agent/status');
      const s = await resp.json();
      const box = document.querySelector('.agent-tabs');
      const badge = document.createElement('span');
      badge.className = 'agent-status';
      badge.style.cssText = 'margin-left:auto;font-size:0.8rem;color:var(--text-muted);align-self:center;';
      badge.textContent = (s.alive ? '🟢 常驻运行中' : '⚪ 未运行') +
        (s.llm_configured ? '' : ' · ⚠️ 未配置 LLM Key') +
        (s.published_on ? ' · 今日已发文' : '');
      box.appendChild(badge);
    } catch (e) { /* 状态条失败不影响主体 */ }
  }

  // ── 会话 ──
  async function loadSessions() {
    const box = document.getElementById('agent-session-list');
    try {
      const resp = await Auth.fetchGet('/api/agent/sessions');
      const data = await resp.json();
      box.innerHTML = '';
      if (!data.sessions.length) {
        box.innerHTML = '<p class="muted">还没有会话，点「新会话」开始。</p>';
        return;
      }
      data.sessions.forEach(function (s) {
        const el = document.createElement('div');
        el.className = 'agent-session-item' + (s.id === state.sessionId ? ' active' : '');
        el.textContent = s.title;
        el.setAttribute('data-sid', s.id);
        el.onclick = function () { selectSession(s.id); };
        box.appendChild(el);
      });
      if (!state.sessionId) selectSession(data.sessions[0].id);
    } catch (e) {
      box.innerHTML = '<p class="agent-error">会话加载失败</p>';
    }
  }

  async function selectSession(id) {
    state.sessionId = id;
    document.querySelectorAll('.agent-session-item').forEach(function (el) {
      el.classList.toggle('active', Number(el.getAttribute('data-sid')) === id);
    });
    try {
      const resp = await Auth.fetchGet('/api/agent/sessions/' + id + '/messages');
      const data = await resp.json();
      renderMessages(data.messages || []);
    } catch (e) {
      const box = document.getElementById('agent-messages');
      box.innerHTML = '<p class="agent-error">历史消息加载失败</p>';
    }
  }

  async function newSession() {
    try {
      const resp = await Auth.fetchPost('/api/agent/sessions', { title: '新会话' });
      const data = await resp.json();
      state.sessionId = data.id;
      await loadSessions();
      renderMessages([]);
      const input = document.getElementById('agent-input');
      input.focus();
    } catch (e) {
      alert('新建会话失败：' + e.message);
    }
  }

  // ── 消息渲染 ──
  function renderMessages(msgs) {
    const box = document.getElementById('agent-messages');
    box.innerHTML = '';
    if (!msgs.length) {
      box.innerHTML = '<p class="muted">新会话～ 想聊点什么？</p>';
      return;
    }
    msgs.forEach(function (m) {
      appendBubble(m.role, m.content, m.sources || []);
    });
    scrollBottom();
  }

  function appendBubble(role, content, sources) {
    const box = document.getElementById('agent-messages');
    const div = document.createElement('div');
    div.className = 'agent-msg ' + role;
    if (role === 'assistant') {
      div.innerHTML = marked.parse(content);
      if (sources && sources.length) {
        const src = document.createElement('div');
        src.className = 'agent-msg-src';
        src.innerHTML = '来源：' + sources.map(function (s) {
          return '<a href="' + esc(s.url) + '" target="_blank" rel="noopener">' + esc(s.title) + '</a>';
        }).join('');
        div.appendChild(src);
      }
    } else {
      div.textContent = content;
    }
    box.appendChild(div);
    return div;
  }

  // ── 打字机渲染（dsh headless 非流式：SSE 一次返回全文，前端逐字模拟流式）──
  function typewriter(bubble, text, done) {
    let i = 0;
    const step = 4; // 每帧字数
    const timer = setInterval(function () {
      i = Math.min(i + step, text.length);
      bubble.innerHTML = marked.parse(text.slice(0, i));
      scrollBottom();
      if (i >= text.length) {
        clearInterval(timer);
        if (done) done();
      }
    }, 16);
  }

  // ── 发送（dsh 非流式：SSE 单事件全文 + 前端打字机）──
  async function send() {
    const input = document.getElementById('agent-input');
    const text = input.value.trim();
    if (!text || state.streaming) return;
    if (!state.sessionId) await newSession();
    if (!state.sessionId) return;

    input.value = '';
    appendBubble('user', text, []);
    state.streaming = true;
    const btn = document.getElementById('agent-send-btn');
    btn.disabled = true;

    const bubble = appendBubble('assistant', '', []);
    bubble.innerHTML = '<span class="muted">小满正在思考…</span>';
    let md = '';

    try {
      const resp = await fetch('/api/agent/sessions/' + state.sessionId + '/messages', {
        method: 'POST',
        headers: Auth.getHeaders(),
        body: JSON.stringify({ content: text }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(function () { return { detail: 'HTTP ' + resp.status }; });
        bubble.innerHTML = '<span class="agent-error">' + esc(err.detail || '请求失败') + '</span>';
        return;
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      let doneSources = null;
      for (;;) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buf += decoder.decode(chunk.value, { stream: true });
        const parts = buf.split('\n\n');
        buf = parts.pop();
        parts.forEach(function (part) {
          part.split('\n').forEach(function (line) {
            if (!line.startsWith('data: ')) return;
            let evt;
            try { evt = JSON.parse(line.slice(6)); } catch (e) { return; }
            if (evt.delta) {
              md += evt.delta; // dsh 非流式：通常一次到齐，先收集
            } else if (evt.error) {
              bubble.innerHTML = '<span class="agent-error">' + esc(evt.error) + '</span>';
            } else if (evt.done) {
              doneSources = evt.sources || [];
            }
          });
        });
      }
      // 收集完毕 → 打字机渲染全文
      typewriter(bubble, md, function () {
        if (doneSources && doneSources.length && !bubble.querySelector('.agent-msg-src')) {
          const src = document.createElement('div');
          src.className = 'agent-msg-src';
          src.innerHTML = '来源：' + doneSources.map(function (s) {
            return '<a href="' + esc(s.url) + '" target="_blank" rel="noopener">' + esc(s.title) + '</a>';
          }).join('');
          bubble.appendChild(src);
        }
        scrollBottom();
        loadSessions(); // 会话 updated_at 刷新排序
      });
    } catch (e) {
      bubble.innerHTML = '<span class="agent-error">请求失败：' + esc(e.message) + '</span>';
    } finally {
      state.streaming = false;
      btn.disabled = false;
    }
  }

  // ── 素材源（①）──
  async function loadSources() {
    const box = document.getElementById('agent-sources-list');
    try {
      const resp = await Auth.fetchGet('/api/agent/sources');
      const data = await resp.json();
      box.innerHTML = '';
      if (!data.sources.length) {
        box.innerHTML = '<p class="muted">还没有素材源。添加常驻站点让小满每日逛站找文章，或手动喂一篇好文。</p>';
        return;
      }
      data.sources.forEach(function (s) {
        const row = document.createElement('div');
        row.className = 'agent-source-item' + (s.enabled ? '' : ' disabled');
        const kindLabel = s.kind === 'website' ? '站点' : '单篇';
        row.innerHTML =
          '<div class="agent-source-info">' +
          '<span class="agent-source-name">' + esc(s.name) + '</span>' +
          '<span class="agent-source-url">' + esc(s.url) + '</span>' +
          '<span class="agent-source-kind">' + kindLabel + '</span>' +
          '</div>' +
          '<div class="agent-source-ops">' +
          (s.kind === 'website'
            ? '<button class="btn btn-xs" onclick="Agent.toggleSource(' + s.id + ')">' + (s.enabled ? '停用' : '启用') + '</button>'
            : '') +
          '<button class="btn btn-xs" onclick="Agent.deleteSource(' + s.id + ')">删除</button>' +
          '</div>';
        box.appendChild(row);
      });
    } catch (e) {
      box.innerHTML = '<p class="agent-error">素材源加载失败</p>';
    }
  }

  function toggleSourcesForm() {
    const f = document.getElementById('agent-sources-form');
    f.style.display = f.style.display === 'none' ? 'flex' : 'none';
  }

  async function addSource() {
    const name = document.getElementById('src-name').value.trim();
    const url = document.getElementById('src-url').value.trim();
    const kind = document.getElementById('src-kind').value;
    if (!name || !url) { alert('请填写名称和 URL'); return; }
    try {
      const resp = await Auth.fetchPost('/api/agent/sources',
        { name: name, url: url, kind: kind });
      if (!resp.ok) {
        const err = await resp.json().catch(function () { return { detail: '请求失败' }; });
        alert(err.detail || '添加失败');
        return;
      }
      document.getElementById('src-name').value = '';
      document.getElementById('src-url').value = '';
      toggleSourcesForm();
      loadSources();
    } catch (e) {
      alert('添加失败：' + e.message);
    }
  }

  async function toggleSource(id) {
    try {
      await Auth.fetchPost('/api/agent/sources/' + id + '/toggle', {});
      loadSources();
    } catch (e) { /* ignore */ }
  }

  async function deleteSource(id) {
    try {
      await fetch('/api/agent/sources/' + id, {
        method: 'DELETE',
        headers: Auth.getHeaders(),
      });
      loadSources();
    } catch (e) { /* ignore */ }
  }

  // ── 动态（③ 时间线：动态短条 + 文章卡混合）──
  async function loadArticles() {
    const box = document.getElementById('agent-articles');
    try {
      const resp = await Auth.fetchGet('/api/agent/articles');
      const data = await resp.json();
      box.innerHTML = '';
      if (!data.articles.length) {
        box.innerHTML = '<p class="muted">小满还没发东西，等她学习完今天的素材就来～</p>';
        return;
      }
      data.articles.forEach(function (a) {
        if (a.kind === 'post') {
          box.appendChild(postItem(a));
        } else {
          box.appendChild(articleItem(a));
        }
      });
    } catch (e) {
      box.innerHTML = '<p class="agent-error">动态加载失败</p>';
    }
  }

  function postItem(a) {
    const item = document.createElement('div');
    item.className = 'agent-post';
    const meta = [a.published_at || '', '动态'].filter(Boolean).join(' · ');
    item.innerHTML =
      '<div class="agent-post-meta"><span class="agent-post-avatar">🌾</span><span>' + esc(meta) + '</span></div>' +
      '<div class="agent-post-body">' + marked.parse(a.content || '') + '</div>';
    return item;
  }

  function articleItem(a) {
    const card = document.createElement('div');
    card.className = 'agent-article-card';
    const topics = (a.topics || []).map(esc).join(' · ');
    const meta = [a.published_at || '', topics].filter(Boolean).join(' · ');
    card.innerHTML =
      '<div class="agent-article-title">' + esc(a.title) + '</div>' +
      (meta ? '<div class="agent-article-meta">' + meta + '</div>' : '') +
      (a.summary ? '<div class="agent-article-summary">' + esc(a.summary) + '</div>' : '') +
      (a.sources && a.sources.length
        ? '<div class="agent-article-links">来源：' + a.sources.map(function (s) {
            return '<a href="' + esc(s.url) + '" target="_blank" rel="noopener" onclick="event.stopPropagation()">' + esc(s.title) + '</a>';
          }).join('') + '</div>'
        : '');
    card.onclick = function () { openArticle(a.id); };
    return card;
  }

  async function openArticle(id) {
    const box = document.getElementById('agent-articles');
    try {
      const resp = await Auth.fetchGet('/api/agent/articles/' + id);
      const a = await resp.json();
      box.innerHTML =
        '<div><button class="btn btn-sm" onclick="Agent.loadArticles()">← 返回列表</button></div>' +
        '<article class="agent-article-detail">' +
        '<h2 class="agent-article-title">' + esc(a.title) + '</h2>' +
        '<div class="agent-article-meta">' + esc(a.published_at || '') + '</div>' +
        '<div class="agent-article-body">' + marked.parse(a.content || '') + '</div>' +
        '</article>';
      scrollBottom();
    } catch (e) {
      box.innerHTML = '<p class="agent-error">文章加载失败</p>';
    }
  }

  window.Agent = {
    switchTab: switchTab,
    load: load,
    loadArticles: loadArticles,
    loadSources: loadSources,
    toggleSourcesForm: toggleSourcesForm,
    addSource: addSource,
    toggleSource: toggleSource,
    deleteSource: deleteSource,
    newSession: newSession,
    send: send,
  };
})();
