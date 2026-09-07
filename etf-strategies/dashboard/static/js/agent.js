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
      loadSources();
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

  function renderProfile(p) {
    const box = document.getElementById('agent-profile');
    const chips = function (arr, cls) {
      return (arr || []).map(function (t) {
        return '<span class="xm-chip ' + cls + '">' + esc(t) + '</span>';
      }).join('');
    };

    // 侧栏「关于我」= 人设卡「基本」节精简
    const basicLi = (p.basic || []).map(function (b) {
      return '<li class="xm-basic-item"><b>' + esc(b.k) + '</b>' + esc(b.v) + '</li>';
    }).join('');

    const sites = (p.sites || []).map(function (s) {
      return '<a class="xm-site" href="' + esc(s.url) + '" target="_blank" rel="noopener">' +
        '<span class="xm-site-name">' + esc(s.name) + '</span>' +
        '<span class="xm-site-kind">' + esc(s.kind || '') + '</span></a>';
    }).join('');

    // 右侧「做过的事」：每条一行（类别 / 干了啥 / 时间 / token）
    const actRows = (p.activity || []).map(function (a) {
      const title = a.url
        ? '<a class="xm-act-link" href="' + esc(a.url) + '" target="_blank" rel="noopener">' + esc(a.title) + '</a>'
        : '<span class="xm-act-title">' + esc(a.title) + '</span>';
      const range = a.ended
        ? esc(a.at || '') + ' → ' + esc(a.ended || '')
        : esc(a.at || '') + ' · <span class="xm-act-ing">进行中</span>';
      return '<li class="xm-act-item' + (a.ended ? '' : ' ongoing') + '">' +
        '<span class="xm-act-label">' + esc(a.label) + '</span>' +
        '<span class="xm-act-main">' + title +
          (a.meta ? '<span class="xm-act-meta">' + esc(a.meta) + '</span>' : '') +
        '</span>' +
        '<span class="xm-act-date">' + range + '</span>' +
        '<span class="xm-act-tokens" title="该活动的真实 token 用量（需 dsh 暴露 usage 后接入；暂无通道 → 未计量）">' +
          (a.tokens == null ? '—' : esc(String(a.tokens))) +
        '</span>' +
        '</li>';
    }).join('');
    const actHead =
      '<div class="xm-act-head">' +
        '<h3 class="em-title">🌱 做过的事</h3>' +
        '<span class="xm-act-note">token 列：真实 usage 待接入，暂不估算</span>' +
      '</div>';

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
          (sites
            ? '<section class="xm-card">' +
                '<h3 class="em-title">🌐 爱逛的地方</h3>' +
                '<div class="xm-sites">' + sites + '</div>' +
              '</section>'
            : '') +
        '</aside>' +
        '<main class="xm-main">' +
          '<section class="xm-card xm-card-activity">' +
            actHead +
            (actRows ? '<ul class="xm-act">' + actRows + '</ul>' : '<p class="muted">还没有自主活动记录——等她去阅读、写文章、逛站点吧～</p>') +
          '</section>' +
        '</main>' +
      '</div>';
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
  };
})();
