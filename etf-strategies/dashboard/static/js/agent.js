/* ═══════════════════════════════════════════════════════════════
   agent.js — 小满角色页（聊天 + 文章）

   依赖：Auth（auth.js 的 fetch 封装 + getHeaders）、marked（CDN 已引入）。
   聊天：POST /api/agent/sessions/{id}/messages → fetch 流式读 SSE。
   文章：GET /api/agent/articles[/{id}]。
   ═══════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const state = { sessionId: null, streaming: false, loaded: false, statusBound: false };

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // 发文时间展示：同一年 → "MM-DD HH:MM"，跨年 → "YYYY-MM-DD HH:MM"。
  // 输入兼容 "YYYY-MM-DD HH:MM:SS" / ISO "YYYY-MM-DDTHH:MM:SS" / 纯日期。
  function fmtTime(s) {
    if (!s) return '';
    var m = String(s).replace('T', ' ').trim().match(/^(\d{4})-(\d{2})-(\d{2})(?:[ ](\d{2}):(\d{2}))?/);
    if (!m) return String(s).slice(0, 16);
    var nowY = new Date().getFullYear();
    var hm = (m[4] != null) ? (' ' + m[4] + ':' + (m[5] || '00')) : '';
    return (Number(m[1]) === nowY ? '' : (m[1] + '-')) + m[2] + '-' + m[3] + hm;
  }

  function scrollBottom() {
    const box = document.getElementById('agent-messages');
    if (box) box.scrollTop = box.scrollHeight;
  }

  function switchTab(tab) {
    document.querySelectorAll('.agent-tab').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-tab') === tab);
    });
    document.getElementById('agent-pane-profile').classList.toggle('active', tab === 'profile');
    document.getElementById('agent-pane-chat').classList.toggle('active', tab === 'chat');
    document.getElementById('agent-pane-articles').classList.toggle('active', tab === 'articles');
    if (tab === 'profile') {
      loadProfile();
    } else if (tab === 'articles') {
      loadArticles();
    } else if (tab === 'chat') {
      // 进入聊天页：刷新提示/待办（含未读小红点）
      loadNotices();
    }
  }

  // ── 初始化（首次进入角色页由 switchView 调用）──
  function load(force) {
    if (!force && state.loaded) return;
    state.loaded = true;
    loadProfile();
    loadSessions();
    loadArticles();
    loadSources();
    loadStatus();
    loadNotices();
    // 状态轮询收敛到桌宠 pet.js（单一轮询源，30s）；角色页订阅 xm:status 更新 pill
    if (!state.statusBound) {
      state.statusBound = true;
      document.addEventListener('xm:status', function (e) {
        renderStatus(e.detail);
      });
    }
  }

  // ── 小满状态栏（请假中 / 摸鱼中 / 正在做XXX）
  //    数据源：桌宠 pet.js 是唯一轮询源，广播 CustomEvent('xm:status') 更新 pill；
  //    首次进入若缓存新鲜（<35s）直接用，否则兜底直拉一次。
  async function loadStatus() {
    try {
      const cache = window.__xmStatusCache;
      if (cache && (Date.now() - cache.t < 35000)) {
        renderStatus(cache.data);
        return;
      }
      const resp = await Auth.fetchGet('/api/agent/status');
      const s = await resp.json();
      renderStatus(s);
    } catch (e) { /* 状态栏失败不影响主体 */ }
  }

  function renderStatus(s) {
    const el = document.getElementById('agent-mood');
    const btn = document.getElementById('agent-online-btn');
    if (!el) return;
    const mood = s.mood || {};
    const parts = [];
    if (s.online) {
      parts.push((s.alive ? '🟢' : '⚪') + (mood.icon || ''));
    } else {
      parts.push('⚪😴');
    }
    parts.push(mood.label || '未知状态');
    if (s.attendance === 'on' && s.current_task) {
      parts.push('· 开始于 ' + (s.current_task.started_at || ''));
    }
    if (!s.alive) parts.push('·（小满进程未运行）');
    el.textContent = parts.join(' ');
    // 状态随出勤/任务态/上线着色（阅读/写作/思考等认真态也算 working）
    let cls;
    if (!s.online) {
      cls = 'pill-offline';
    } else if (s.attendance === 'leave') {
      cls = 'pill-leave';
    } else if (s.current_task || (mood.busy)) {
      cls = 'pill-working';
    } else {
      cls = 'pill-slack';
    }
    el.className = 'agent-status-pill ' + cls;

    // 上线/下线按钮
    if (btn) {
      if (s.online) {
        btn.textContent = '😴 让小满休息';
        btn.className = 'btn btn-sm btn-offline';
      } else {
        btn.textContent = '🌱 让小满上线';
        btn.className = 'btn btn-sm btn-primary';
      }
    }
  }

  // 桌宠思考联动（让 pet.js 显示"思考中"瞬时态）
  function dispatchThinking(on) {
    try {
      document.dispatchEvent(new CustomEvent('xm:thinking', { detail: { on: on } }));
    } catch (e) { /* ignore */ }
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
        el.setAttribute('data-sid', s.id);
        const name = document.createElement('span');
        name.className = 'agent-session-name';
        name.textContent = s.title;
        const del = document.createElement('button');
        del.className = 'agent-session-del';
        del.title = '删除会话';
        del.textContent = '✕';
        del.onclick = function (ev) { ev.stopPropagation(); deleteSession(s.id); };
        el.appendChild(name);
        el.appendChild(del);
        el.onclick = function () { selectSession(s.id); };
        box.appendChild(el);
      });
      if (!state.sessionId) selectSession(data.sessions[0].id);
    } catch (e) {
      box.innerHTML = '<p class="agent-error">会话加载失败</p>';
    }
  }

  async function deleteSession(id) {
    if (!confirm('确定删除这个会话？聊天记录会一起删掉，且不可恢复。')) return;
    try {
      // BUG-FIX(2026-09-07)：改用 Auth.fetchDelete，token 过期时统一跳登录（原裸 fetch 静默失败）
      const resp = await Auth.fetchDelete('/api/agent/sessions/' + id);
      if (!resp.ok) { alert('删除失败'); return; }
      if (state.sessionId === id) {
        state.sessionId = null;
        const box = document.getElementById('agent-messages');
        box.innerHTML = '<p class="muted">会话已删除，选一个或新建会话开始聊。</p>';
      }
      await loadSessions();
    } catch (e) {
      alert('删除失败：' + e.message);
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
      // 每条 assistant 消息本身就是一条气泡（拆几条由 dsh 决定，前端不再切文本）
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

  function typePromise(bubble, text) {
    return new Promise(function (resolve) {
      typewriter(bubble, text, resolve);
    });
  }

  // 把 dsh 返回的多条消息逐条打字渲染（一条消息 = 一个气泡，像真人连发消息）
  async function playAssistantMessages(msgs, sources) {
    let lastBubble = null;
    for (let i = 0; i < msgs.length; i++) {
      const b = appendBubble('assistant', '', []);
      lastBubble = b;
      await typePromise(b, msgs[i]);
    }
    if (sources && sources.length && lastBubble) {
      const src = document.createElement('div');
      src.className = 'agent-msg-src';
      src.innerHTML = '来源：' + sources.map(function (s) {
        return '<a href="' + esc(s.url) + '" target="_blank" rel="noopener">' + esc(s.title) + '</a>';
      }).join('');
      lastBubble.appendChild(src);
    }
    scrollBottom();
    loadSessions(); // 会话 updated_at 刷新排序
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

    const thinkBubble = appendBubble('assistant', '', []);
    thinkBubble.innerHTML = '<span class="muted">小满正在思考…</span>';
    dispatchThinking(true);   // 桌宠进入"思考中"瞬时态
    const msgParts = [];      // dsh 拆好的消息：一条消息 = 一个气泡

    try {
      // BUG-FIX(2026-09-07)：改用 Auth.fetchPost，token 过期统一跳登录（原裸 fetch 静默 401）
      const resp = await Auth.fetchPost('/api/agent/sessions/' + state.sessionId + '/messages',
                                        { content: text });
      if (!resp.ok) {
        const err = await resp.json().catch(function () { return { detail: 'HTTP ' + resp.status }; });
        thinkBubble.innerHTML = '<span class="agent-error">' + esc(err.detail || '请求失败') + '</span>';
        dispatchThinking(false);
        return;
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      let doneSources = null;
      let hadError = false;   // BUG-FIX(2026-09-07)：SSE 错误曾被 thinkBubble.remove() 静默删掉
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
              msgParts.push(evt.delta); // 每条 delta = 一条消息（后端已按行拆好）
            } else if (evt.error) {
              hadError = true;
              thinkBubble.innerHTML = '<span class="agent-error">' + esc(evt.error) + '</span>';
            } else if (evt.done) {
              doneSources = evt.sources || [];
            }
          });
        });
      }
      // 收集完毕 → 去掉"思考中"占位，逐条消息打字出现（每条 = 一个气泡）
      // BUG-FIX：发生 SSE 错误时保留错误气泡可见，不再 remove()
      if (hadError && thinkBubble.parentNode) {
        dispatchThinking(false);
        loadSessions();
        return;
      }
      if (thinkBubble.parentNode) thinkBubble.remove();
      if (!msgParts.length) {
        dispatchThinking(false);
        loadSessions();
      } else {
        await playAssistantMessages(msgParts, doneSources || []);
        dispatchThinking(false); // 全部消息展示完 → 桌宠退出"思考中"
      }
    } catch (e) {
      thinkBubble.innerHTML = '<span class="agent-error">请求失败：' + esc(e.message) + '</span>';
      dispatchThinking(false);
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
      // BUG-FIX(2026-09-07)：改用 Auth.fetchDelete，token 过期统一跳登录；且检查 resp.ok
      const resp = await Auth.fetchDelete('/api/agent/sources/' + id);
      if (!resp.ok) { alert('删除失败'); return; }
      loadSources();
    } catch (e) { alert('删除失败：' + (e.message || e)); }
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
    // BUG-FIX(2026-09-08)：动态必须展示发文时间（fmtTime 格式化），
    // 且已回填 published_at + article_create 云端补写，时间不会再为空。
    const meta = [(a.published_at ? fmtTime(a.published_at) : ''), '动态'].filter(Boolean).join(' · ');
    item.innerHTML =
      '<div class="agent-post-meta"><span class="agent-post-avatar">🌾</span><span>' + esc(meta) + '</span></div>' +
      '<div class="agent-post-body">' + marked.parse(a.content || '') + '</div>';
    return item;
  }

  function articleItem(a) {
    const card = document.createElement('div');
    card.className = 'agent-article-card';
    const topics = (a.topics || []).map(esc).join(' · ');
    const meta = [(a.published_at ? fmtTime(a.published_at) : ''), topics].filter(Boolean).join(' · ');
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
        '<div class="agent-article-meta">' + esc(a.published_at ? fmtTime(a.published_at) : '') + '</div>' +
        '<div class="agent-article-body">' + marked.parse(a.content || '') + '</div>' +
        '</article>';
      scrollBottom();
    } catch (e) {
      box.innerHTML = '<p class="agent-error">文章加载失败</p>';
    }
  }

  // ── 认识小满（介绍页）──
  async function loadProfile() {
    const box = document.getElementById('agent-profile');
    if (!box) return;
    try {
      const resp = await Auth.fetchGet('/api/agent/profile');
      const p = await resp.json();
      renderProfile(p);
    } catch (e) {
      box.innerHTML = '<p class="agent-error">介绍加载失败</p>';
    }
  }

  // ── 社交平台品牌 SVG（前端内置，方案 v1.10 §9.4；仅作链接入口指名使用）──
  // 图标为简化品牌徽标（单色，经 CSS 着色：可达=高亮色，不可达=置灰）
  var PLATFORM_ICONS = {
    weibo: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M10.05 12.53c-.55-.26-1.2-.08-1.5.32-.27.36-.2.82.17 1.1.45.32 1.15.23 1.54-.17.35-.4.28-.97-.21-1.25zM11.1 13.35c.32-.15.4-.53.2-.84-.19-.3-.6-.36-.92-.19-.3.18-.38.55-.19.85.2.28.6.35.91.18z"/><path d="M12 2a10 10 0 100 20 10 10 0 000-20zm4.46 13.3c-.15.4-.37.7-.64.95-.29.27-.65.5-1.1.7-.85.4-2 .6-3.32.6-1.24 0-2.37-.22-3.34-.66-.51-.23-.97-.55-1.37-.96-.18-.18-.34-.37-.47-.56.55-.06 1-.3 1.34-.7.3-.37.28-.9-.06-1.24-.35-.34-.86-.35-1.23-.06-.08.06-.15.13-.2.21.66-2.6 2.2-4.16 3.4-4.55.87-.28 1.6.05 1.8.83.13.5-.08 1.06-.53 1.4-.3.23-.66.34-1.02.32-.2.04-.4.02-.6 0 .6.55 1.4.87 2.3.95.58.05 1.1-.34 1.2-.92.08-.5-.2-1-.68-1.2-.13-.06-.27-.1-.4-.1 1.4-.32 2.9.16 3.87 1.38.67.83.95 1.83.76 2.65zM7.2 8.42c.48.66.95 1.33 1.42 2l.05.05c.36.55.28 1.27-.2 1.7-.5.46-1.24.47-1.76.07l-.02-.02c-.83-.6-1.64-1.24-2.42-1.88-.34-.3-.36-.8-.07-1.14.3-.35.8-.38 1.15-.1l.3.28c.17-.36.3-.7.45-1.02.16-.36.53-.58.93-.55.4.03.75.3.9.68.14.34.06.72-.27.97l-.66.57c.03.01.06.03.1.04zM5.9 10.7c-.28.08-.5.33-.55.62-.06.3.1.59.38.73.27.13.6.08.82-.13.3-.3.2-.8-.2-.96a.61.61 0 00-.45-.26z"/></svg>',
    xhs: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2c1.8 0 3.2.7 4.2 1.9 1 1.3 1.6 3.1 1.6 5.2 0 2.2-.8 4.1-2.2 5.6-.8.9-1.9 1.7-3.2 2.3l-1.4-.7c1.1-.5 2-1.1 2.7-1.9-2 .3-3.8-.3-4.9-1.7-.9-1.2-1.2-2.7-.8-4.2.4-1.6 1.3-2.8 2.5-3.5.8-.5 1.7-.8 2.6-.8.9 0 1.7.3 2.4.8-1.9.1-3.3.9-4 2.3-.5 1-.4 2 .2 2.8.6.9 1.6 1.4 2.8 1.4 1.1 0 2.1-.4 2.8-1.2.6-.8.9-1.8.7-2.9-.3-1.4-1-2.6-2.1-3.4C14.7 2.5 13.4 2 12 2zm0 2.2c1.3 0 2.3.4 3 1.1.6.7 1 1.6 1 2.7 0 1.4-.5 2.6-1.4 3.4-.8.8-1.9 1.2-3.1 1.2-1.2 0-2.3-.5-3-1.3-.7-.8-1-1.8-.9-2.9.1-1.4.6-2.5 1.5-3.3.8-.7 1.9-1 3-1l-.1.1zm0 3.4c-1 0-1.9.8-1.9 1.9 0 1 .9 1.9 1.9 1.9s1.9-.9 1.9-1.9-.9-1.9-1.9-1.9zm7.6 6.4c-1.9.2-3.4 1.3-4.2 3.1-.3.7-.5 1.5-.4 2.3.1.8.5 1.5 1.1 2 .6.5 1.4.8 2.2.8h2.1c1 0 1.9-.5 2.5-1.2.6-.8.9-1.7.8-2.7-.1-1-.6-1.9-1.4-2.5-.7-.6-1.6-.9-2.5-.9l-.2.1zm.6 1.9c.8 0 1.5.3 2 .8.5.5.8 1.2.8 2 0 .7-.3 1.4-.8 1.9-.5.5-1.2.8-2 .8-.8 0-1.5-.3-2-.8-.5-.5-.8-1.2-.8-2 0-.8.3-1.5.8-2 .5-.5 1.2-.8 2-.8z"/></svg>',
    x: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M18.24 2.25h3.31l-7.23 8.26 8.5 11.24h-6.66l-5.21-6.82L5 21.75H1.68l7.73-8.84L1.25 2.25h6.83l4.71 6.23 5.45-6.23zm-1.16 17.52h1.83L7.08 4.13H5.12l11.96 15.64z"/></svg>',
    zhihu: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12.45 2.5h7.3c.6 0 1.1.5 1.1 1.1v16.8c0 .6-.5 1.1-1.1 1.1h-7.3l-2.2 1.3c-.5.3-1.1-.1-1.1-.7v-.6H4.35c-.6 0-1.1-.5-1.1-1.1V3.6c0-.6.5-1.1 1.1-1.1h7.3l.8-.5v.5zm-1.7 2.2H4.6a.9.9 0 00-.9.9v15.6a.9.9 0 00.9.9h2.7v.4l1.6-.9v.5h1.4l.45-.3v-16.4a.5.5 0 00-.5-.7zm8.6 0h-6.5v17.2h6.5a.9.9 0 00.9-.9V5.6a.9.9 0 00-.9-.9z"/></svg>',
    xueqiu: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2.5c1.9 0 3.6.6 5 1.7 1.5 1.1 2.5 2.8 2.5 4.7 0 1.4-.4 2.7-1.1 3.9.8.6 1.4 1.5 1.7 2.5.3 1.1.2 2.3-.4 3.3-.6 1.1-1.5 1.9-2.7 2.4-.8.3-1.7.5-2.6.5-.9 0-1.8-.2-2.5-.5-1-.3-1.8-.9-2.4-1.7-.5-.7-.8-1.6-.7-2.5l.1-.9c-1.6.6-3 .4-4.1-.5-1-.9-1.5-2.2-1.4-3.6.1-1.3.6-2.5 1.4-3.4.8-1 1.9-1.6 3.2-1.8.5-2.4 1.9-4.3 3.9-5.4.7-.4 1.5-.6 2.3-.6zm0 2.1c-1.4 0-2.7.4-3.7 1.2-1.6 1.2-2.5 3.2-2.5 5.5v.2c-.9.3-1.6.8-2.1 1.5-.5.7-.8 1.5-.7 2.4 0 .9.4 1.8 1 2.4.7.7 1.7 1 2.9.8-.1 1-.2 1.9-.7 2.5-.6.8-1.7 1.4-3 1.4.2-1 .8-1.9 1.6-2.5.6-.5 1.4-.8 2.2-.8.3 0 .5 0 .8.1-.3 1.3 0 2.6.9 3.5.6.6 1.4 1 2.3 1.3.8.3 1.7.4 2.5.4 1.9 0 3.7-.7 5-2 .9-1 1.4-2.3 1.3-3.7-.1-1.2-.6-2.3-1.4-3.1-.4-.4-.9-.7-1.4-.9.2-.8.1-1.6-.4-2.3-.5-.7-1.4-1.1-2.4-1.2l-.2-.1v-.1c0-2.3-.8-4.3-2.2-5.6-.7-.6-1.5-1-2.3-1.2l-.3-.1z"/></svg>',
    cls: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="4"/><path d="M13.2 6.5l-4.6 5.6h3.1l-1.4 5.4 5-5.8h-3.2l1.1-5.2z" fill="var(--bg-deep, #1a140f)"/></svg>',
    wallstreetcn: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M4 4h4.2l3.8 6.6L15.8 4H20l-6.4 9.3V20h-3.2v-6.7L4 4z"/></svg>',
  };
  var PLATFORM_FALLBACK = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2a10 10 0 100 20 10 10 0 000-20zm0 18a8 8 0 110-16 8 8 0 010 16zm0-11a1 1 0 00-1 1v4a1 1 0 002 0v-4a1 1 0 00-1-1zm0 7.5a1.2 1.2 0 100 2.4 1.2 1.2 0 000-2.4z"/></svg>';

  function renderSocialPlatforms(list) {
    if (!list || !list.length) return '';
    // 可达的排前面（高亮），不可达的排后面；组内保持原有顺序（稳定排序）
    return list.slice().sort(function (a, b) {
      return (b.reachable ? 1 : 0) - (a.reachable ? 1 : 0);
    }).map(function (s) {
      var icon = PLATFORM_ICONS[s.icon] || PLATFORM_FALLBACK;
      var reachable = !!s.reachable;
      var tip = s.reason || (reachable ? '可访问' : '暂不可访问');
      return '<a class="xm-social-item ' + (reachable ? 'is-on' : 'is-off') + '" ' +
        'href="' + esc(s.url) + '" target="_blank" rel="noopener" ' +
        'title="' + esc(s.name + ' · ' + tip) + '" aria-label="' + esc(s.name) + '">' +
        '<span class="xm-social-icon">' + icon + '</span>' +
        '<span class="xm-social-name">' + esc(s.name) + '</span>' +
        (reachable ? '<span class="xm-social-dot" title="小满可以逛这里"></span>' : '') +
        '</a>';
    }).join('');
  }

  function renderProfile(p) {
    const box = document.getElementById('agent-profile');
    const chips = function (arr, cls) {
      return (arr || []).map(function (t) {
        return '<span class="xm-chip ' + cls + '">' + esc(t) + '</span>';
      }).join('');
    };

    const basicLi = (p.basic || []).map(function (b) {
      return '<li class="xm-basic-item"><b>' + esc(b.k) + '</b>' + esc(b.v) + '</li>';
    }).join('');

    // ── 爱逛的地方（方案 v1.10 §9.4 + 2026-09 合并）：社交平台 + 财联社/华尔街见闻 ──
    const social = renderSocialPlatforms(p.social_platforms);

    box.innerHTML =
      '<div class="xm-page">' +
        '<aside class="xm-side">' +
          '<div class="xm-hero xm-hero-side">' +
            '<div class="xm-hero-avatar">🌾</div>' +
            '<div class="xm-hero-text">' +
              '<h2 class="xm-hero-name">小满</h2>' +
              '<div class="xm-hero-sub">元气财经博主 · 名自二十四节气「小满」</div>' +
            '</div>' +
          '</div>' +
          '<section class="xm-card">' +
            '<h3 class="em-title">🌙 关于我</h3>' +
            (basicLi ? '<ul class="xm-basic">' + basicLi + '</ul>' : '<p class="muted">（人设卡暂无「基本」节）</p>') +
          '</section>' +
          '<section class="xm-card">' +
            '<h3 class="em-title">💛 爱好</h3>' +
            '<div class="xm-chip-row"><span class="xm-chip-label">研究</span>' + chips(p.interests, 'xm-chip-blue') + '</div>' +
            '<div class="xm-chip-row"><span class="xm-chip-label">生活</span>' + chips(p.hobbies, 'xm-chip-warm') + '</div>' +
          '</section>' +
          (social
            ? '<section class="xm-card">' +
                '<h3 class="em-title">🌐 爱逛的地方</h3>' +
                '<div class="xm-social">' + social + '</div>' +
                '<p class="xm-social-note muted">置灰 = 小满暂时逛不了这里（可点击仍可人工访问）</p>' +
              '</section>'
            : '') +
        '</aside>' +
        '<main class="xm-main">' +
          '<section class="xm-card xm-card-activity" id="xm-activities-section">' +
            '<div class="xm-act-head">' +
              '<h3 class="em-title">🌱 做过的事</h3>' +
              '<div class="xm-act-filter">' +
                '<input type="date" id="xm-act-date-filter" class="xm-act-date-input" title="按日期筛选">' +
                '<button id="xm-act-filter-today" class="btn btn-sm" title="只看今天">今天</button>' +
                '<button id="xm-act-filter-all" class="btn btn-sm" title="查看全部">全部</button>' +
              '</div>' +
            '</div>' +
            '<div id="xm-act-list"><p class="muted">加载中...</p></div>' +
            '<div id="xm-act-pager" class="xm-act-pager"></div>' +
          '</section>' +
        '</main>' +
      '</div>';

    setTimeout(function () { loadActivities(); }, 50);

    document.getElementById('xm-act-date-filter').addEventListener('change', function () {
      loadActivities(1);
    });
    document.getElementById('xm-act-filter-today').addEventListener('click', function () {
      var today = new Date().toISOString().slice(0, 10);
      document.getElementById('xm-act-date-filter').value = today;
      loadActivities(1);
    });
    document.getElementById('xm-act-filter-all').addEventListener('click', function () {
      document.getElementById('xm-act-date-filter').value = '';
      loadActivities(1);
    });
  }

  var _actPage = 1;
  function loadActivities(page) {
    page = page || _actPage || 1;
    _actPage = page;
    var dateFilter = '';
    var dateEl = document.getElementById('xm-act-date-filter');
    if (dateEl) dateFilter = dateEl.value || '';

    Auth.fetchGet('/api/agent/activities?page=' + page + '&page_size=20&date=' + encodeURIComponent(dateFilter))
      .then(function (resp) { return resp.json(); })
      .then(function (data) {
        renderActivities(data);
      })
      .catch(function () {
        document.getElementById('xm-act-list').innerHTML = '<p class="agent-error">加载失败</p>';
      });
  }

  function renderActivities(data) {
    var list = document.getElementById('xm-act-list');
    var pager = document.getElementById('xm-act-pager');

    var rows = (data.activities || []).map(function (a) {
      var title = a.url
        ? '<a class="xm-act-link" href="' + esc(a.url) + '" target="_blank" rel="noopener">' + esc(a.title) + '</a>'
        : '<span class="xm-act-title">' + esc(a.title) + '</span>';
      var range = a.ended
        ? esc(a.at || '') + ' → ' + esc(a.ended || '')
        : esc(a.at || '') + ' · <span class="xm-act-ing">进行中</span>';
      return '<li class="xm-act-item' + (a.ended ? '' : ' ongoing') + '">' +
        '<span class="xm-act-label">' + esc(a.label) + '</span>' +
        '<span class="xm-act-main">' + title +
          (a.meta ? '<span class="xm-act-meta">' + esc(a.meta) + '</span>' : '') +
        '</span>' +
        '<span class="xm-act-date">' + range + '</span>' +
        '<span class="xm-act-tokens" title="该活动的真实 token 用量">' +
          (a.tokens == null ? '—' : esc(String(a.tokens))) +
        '</span>' +
        '</li>';
    }).join('');

    if (!rows) {
      list.innerHTML = '<p class="muted">还没有自主活动记录——等她去阅读、写文章、逛站点吧～</p>';
      pager.innerHTML = '';
      return;
    }
    list.innerHTML = '<ul class="xm-act">' + rows + '</ul>';

    pager.innerHTML = '';
    if (data.total_pages <= 1) return;
    var pagerHtml = '<div class="xm-pager">';
    pagerHtml += '<span class="xm-pager-info">共 ' + data.total + ' 条，' + data.total_pages + ' 页</span>';
    for (var i = 1; i <= data.total_pages; i++) {
      if (i === data.page) {
        pagerHtml += '<span class="xm-pager-btn is-active">' + i + '</span>';
      } else {
        pagerHtml += '<button class="xm-pager-btn" data-page="' + i + '">' + i + '</button>';
      }
    }
    pagerHtml += '</div>';
    pager.innerHTML = pagerHtml;

    var btns = pager.querySelectorAll('.xm-pager-btn');
    for (var j = 0; j < btns.length; j++) {
      btns[j].addEventListener('click', function () {
        var p = parseInt(this.getAttribute('data-page'), 10);
        if (p) loadActivities(p);
      });
    }
  }

  async function toggleOnline() {
    const cache = window.__xmStatusCache;
    const online = cache && cache.data && cache.data.online;
    const endpoint = online ? '/api/agent/offline' : '/api/agent/online';
    try {
      await Auth.fetchPost(endpoint, {});
      const resp = await Auth.fetchGet('/api/agent/status');
      const s = await resp.json();
      window.__xmStatusCache = { data: s, t: Date.now() };
      renderStatus(s);
      document.dispatchEvent(new CustomEvent('xm:status', { detail: s }));
    } catch (e) {
      alert('操作失败：' + e.message);
    }
  }

  // ── 📌 提示与待办（REQ-002）：小满主动发；提示不需回复，待办回复后回调执行 ──
  //    未处理在前、已处理（已阅/已回复/已忽略）排后并置灰；分页防堆积
  //    待办状态机：open(未处理) → done(处理成功，展示小满回复) / 失败回 open(展示失败原因，可重试)
  //    状态变更后【就地更新】当前项，不整页重拉（否则已处理项被排到后面/翻页，看不到置灰）
  var _notices = [];
  var _noticesPage = 1;
  var _noticesTotalPages = 1;
  var _NOTICES_PAGE_SIZE = 5;

  function updateNoticesBadge(unread) {
    var badge = document.getElementById('agent-chat-badge');
    if (!badge) return;
    unread = Number(unread) || 0;
    if (unread > 0) {
      badge.textContent = unread > 99 ? '99+' : String(unread);
      badge.hidden = false;
    } else {
      badge.hidden = true;
    }
  }

  // 就地合并某条提示/待办（未处理在前 → 已处理自动排到末尾）。
  // patch 可为完整卡片（API 返回）或局部字段（如 {id, read:true}）；未找到则插入。
  function upsertNotice(patch) {
    if (!patch || !patch.id) return;
    var found = false;
    for (var i = 0; i < _notices.length; i++) {
      if (_notices[i].id === patch.id) {
        for (var k in patch) {
          if (patch.hasOwnProperty(k)) _notices[i][k] = patch[k];
        }
        found = true;
        break;
      }
    }
    if (!found) _notices.unshift(patch);
    // 排序：未处理在前，已处理在后（组内保持顺序）
    _notices.sort(function (a, b) {
      var ap = isProcessedNotice(a) ? 1 : 0;
      var bp = isProcessedNotice(b) ? 1 : 0;
      return ap - bp;
    });
  }

  function isProcessedNotice(n) {
    return n.read || n.status === 'done' || n.status === 'dismissed';
  }

  async function loadNotices(page) {
    if (page === undefined) page = _noticesPage;
    try {
      const resp = await Auth.fetchGet('/api/agent/notices?page=' + page +
        '&page_size=' + _NOTICES_PAGE_SIZE);
      const d = await resp.json();
      _notices = d.notices || [];
      _noticesPage = d.page || page;
      _noticesTotalPages = d.total_pages || 0;
      updateNoticesBadge(d.unread_count);
      renderNotices();
    } catch (e) {
      // 加载失败：不阻塞聊天页，仅隐藏面板
      const sec = document.getElementById('agent-notices');
      if (sec) sec.hidden = true;
    }
  }

  function escAttr(s) {
    return esc(s).replace(/"/g, '&quot;');
  }

  function noticeCard(n) {
    var isTodo = n.kind === 'todo';
    var processed = isProcessedNotice(n);
    var cls = ['agent-notice'];
    cls.push(isTodo ? 'is-todo' : 'is-notice');
    if (processed) cls.push('is-processed');
    if (!n.read && n.status !== 'dismissed') cls.push('is-unread');
    var tag = isTodo
      ? '<span class="agent-notice-tag todo">待办</span>'
      : '<span class="agent-notice-tag notice">提示</span>';
    var meta = fmtTime(n.created_at) + (n.source ? ' · ' + esc(n.source) : '');
    // 状态行：小满处理结果（成功回复 / 失败原因）
    var stateLine = '';
    if (isTodo && n.status === 'done' && n.result) {
      stateLine = '<div class="agent-notice-result">✅ 处理成功 · 小满：' + esc(n.result) + '</div>';
    } else if (isTodo && n.status === 'open' && n.result && n.reply) {
      stateLine = '<div class="agent-notice-result is-fail">⚠️ 处理失败：' + esc(n.result) + '（可重新回复重试）</div>';
    }
    // 用户已回复内容
    var replyLine = '';
    if (isTodo && n.reply) {
      replyLine = '<div class="agent-notice-replied">已回复：' + esc(n.reply) + '</div>';
    }
    var actions = '';
    if (isTodo) {
      if (n.status === 'open') {
        // 未处理：可回复（失败后重试也走这里）
        actions =
          '<input class="agent-notice-reply-input" data-reply-id="' + n.id + '" ' +
          'placeholder="回复内容…" aria-label="回复待办：' + escAttr(n.title) + '">' +
          '<button class="agent-notice-btn" data-reply-btn="' + n.id + '" onclick="Agent.noticeReply(' + n.id + ')">回复</button>' +
          '<button class="agent-notice-btn" onclick="Agent.noticeDismiss(' + n.id + ')" title="忽略该待办，不再提示">忽略</button>';
      } else if (n.status === 'done') {
        actions = '<button class="agent-notice-btn" onclick="Agent.noticeDismiss(' + n.id + ')" title="忽略该待办，不再提示">忽略</button>';
      }
      // dismissed：无操作
    } else if (!n.read && n.status !== 'dismissed') {
      actions = '<button class="agent-notice-btn" onclick="Agent.noticeMarkRead(' + n.id + ')" title="标记为已读">知道了</button>';
    }
    return '<div class="' + cls.join(' ') + '" data-nid="' + n.id + '">' +
      '<div class="agent-notice-body">' +
        '<div class="agent-notice-title">' + tag + esc(n.title) + '</div>' +
        '<div class="agent-notice-content">' + esc(n.content) + '</div>' +
        replyLine + stateLine +
        '<div class="agent-notice-meta">' + esc(meta) + '</div>' +
      '</div>' +
      '<div class="agent-notice-actions">' + actions + '</div>' +
    '</div>';
  }

  function renderNotices() {
    var sec = document.getElementById('agent-notices');
    var box = document.getElementById('agent-notices-list');
    var pager = document.getElementById('agent-notices-pager');
    if (!sec || !box) return;
    if (!_notices.length) {
      sec.hidden = true;
      return;
    }
    sec.hidden = false;
    box.innerHTML = _notices.map(noticeCard).join('');
    // 待办输入框：Enter 提交
    box.querySelectorAll('.agent-notice-reply-input').forEach(function (inp) {
      inp.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter') {
          ev.preventDefault();
          var id = Number(inp.getAttribute('data-reply-id'));
          Agent.noticeReply(id);
        }
      });
    });
    // 分页控件
    if (pager) {
      pager.innerHTML =
        '<button class="agent-notice-page-btn" onclick="Agent.noticesPage(' + (_noticesPage - 1) + ')" ' +
        (_noticesPage <= 1 ? 'disabled' : '') + '>‹ 上一页</button>' +
        '<span class="agent-notice-page-info">第 ' + _noticesPage + ' / ' +
        (_noticesTotalPages || 1) + ' 页</span>' +
        '<button class="agent-notice-page-btn" onclick="Agent.noticesPage(' + (_noticesPage + 1) + ')" ' +
        (_noticesPage >= _noticesTotalPages ? 'disabled' : '') + '>下一页 ›</button>';
    }
  }

  async function noticesPage(page) {
    if (page < 1 || page > _noticesTotalPages || page === _noticesPage) return;
    await loadNotices(page);
  }

  async function noticesReadAll() {
    try {
      const resp = await Auth.fetchPost('/api/agent/notices/read-all', {});
      const d = await resp.json();
      updateNoticesBadge(d.unread_count || 0);
      // 就地全部标记已读（不整页重拉 → 不打断用户当前查看的位置）
      _notices.forEach(function (n) { n.read = true; });
      renderNotices();
    } catch (e) { /* 静默 */ }
  }

  async function noticeMarkRead(nid) {
    try {
      const resp = await Auth.fetchPost('/api/agent/notices/' + nid + '/read', {});
      const d = await resp.json();
      upsertNotice({ id: nid, read: true });  // 就地合并：仅改 read
      updateNoticesBadge(d.unread_count);
      renderNotices();
    } catch (e) { /* 静默 */ }
  }

  async function noticeReply(nid) {
    var inp = document.querySelector('.agent-notice-reply-input[data-reply-id="' + nid + '"]');
    var reply = inp ? inp.value.trim() : '';
    if (!reply) {
      if (inp) inp.focus();
      return;
    }
    var btn = document.querySelector('.agent-notice-btn[data-reply-btn="' + nid + '"]');
    if (btn) { btn.disabled = true; btn.textContent = '处理中…'; }
    try {
      const resp = await Auth.fetchPost('/api/agent/notices/' + nid + '/reply', { reply: reply });
      const d = await resp.json();
      // 就地更新该条（成功→done 置灰并显示小满回复；失败→回 open 显示失败原因 + 未读）
      upsertNotice(d.notice);
      updateNoticesBadge(d.unread_count);
      renderNotices();
      toast(d.ok ? '待办已处理' : '处理失败：' + (d.message || ''), d.ok ? 'success' : 'error');
    } catch (e) {
      toast('回复失败: ' + (e.message || '待办已过期或回复无效'), 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '回复'; }
    }
  }

  async function noticeDismiss(nid) {
    try {
      const resp = await Auth.fetchPost('/api/agent/notices/' + nid + '/dismiss', {});
      const d = await resp.json();
      // 就地合并：忽略 → dismissed（已处理，不计未读；保留回复/结果历史）
      upsertNotice({ id: nid, status: 'dismissed', read: true });
      updateNoticesBadge(d.unread_count);
      renderNotices();
    } catch (e) { /* 静默 */ }
  }

  window.Agent = {
    switchTab: switchTab,
    load: load,
    loadProfile: loadProfile,
    loadArticles: loadArticles,
    loadSources: loadSources,
    toggleSourcesForm: toggleSourcesForm,
    addSource: addSource,
    toggleSource: toggleSource,
    deleteSource: deleteSource,
    newSession: newSession,
    deleteSession: deleteSession,
    send: send,
    toggleOnline: toggleOnline,
    noticesReadAll: noticesReadAll,
    noticesPage: noticesPage,
    noticeMarkRead: noticeMarkRead,
    noticeReply: noticeReply,
    noticeDismiss: noticeDismiss,
  };
})();
