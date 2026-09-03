/* ═══════════════════════════════════════════════════════════════
   pet.js — 小满 LIVE2D 桌宠（看板娘）主模块

   架构（三层）：
     - 控制层（本文件）：状态机 + 唯一轮询源 + 交互
       状态来源：GET /api/agent/status（30s）→ 机器可读 state（后端已加：
       offline / leave / working / slack），本地瞬时态 thinking 由 agent.js
       发 CustomEvent('xm:thinking') 叠加。轮询结果广播 CustomEvent('xm:status')
       （agent.js 订阅更新角色页状态 pill，自身不再轮询）。
     - 场景层：CSS 驱动的小桌/笔记本（敲键盘/盯屏/代码滚动/Zzz），见 pet.css
     - 渲染层：PixiJS + pixi-live2d-display（LIVE2D），资产自托管于
       /static/live2d/；资产缺失或 WebGL 不可用时自动降级（不报错、不影响主体）

   挂载：dashboard.js showApp()/showLoginPage() 派发 CustomEvent('xm:auth')，
   本模块据此 mount/unmount（管理员角色门控，与"角色/工作日程"同权限）。
   ═══════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  // ═══════════ 配置（资产到位后改 MODEL_JSON 指向所选模型即可）═══
  var CFG = {
    pollMs: 30000,            // 状态轮询周期
    adminOnly: false,         // 可见范围：false=任何登录用户（默认）；true=仅管理员（与角色页同权限）
    minWidth: 900,            // <900px 自动收起为小圆点
    dragThreshold: 6,         // px：超过视为拖拽（否则视为点击）
    vendor: {
      pixi:    '/static/live2d/vendor/pixi.min.js',   // PixiJS（两版运行时共用）
      // Cubism4 运行时（默认；模型入口 *.model3.json）
      cubism4Core: '/static/live2d/vendor/live2dcubismcore.min.js',
      l2d4:        '/static/live2d/vendor/pixi-live2d-display.min.js',
      // Cubism2 运行时（live2d-widget-model-* 生态，如 Pio/Shizuku；模型入口 *.model.json）
      cubism2Core: '/static/live2d/vendor/live2d.min.js',
      l2d2:        '/static/live2d/vendor/pixi-live2d-display-cubism2.min.js',
    },
    // 所选模型入口：以 .model3.json 结尾 → 自动用 Cubism4；
    // 以 .model.json 结尾 → 自动用 Cubism2（live2d-widget 生态，脚本 -AddNpm 拉取）
    modelJson: '/static/live2d/model/model.json',
    stageW: 300, stageH: 204, // 与 pet.css 的 canvas 区域一致
  };

  // ═══════════ 台词库（人设语气；仅状态播报/日常，不含投资指令）═══
  var LINES = {
    slack: [
      '摸鱼中…今天又是谁在 ETF 里偷跑？',
      '收盘了才敢说的悄悄话：我也在盯大盘…',
      '要不要聊聊天？我最近在读宏观周报～',
    ],
    leave: [
      '小满请假了，有事留言，回来再回～',
      '呼…今天休息，复盘笔记明天补！',
    ],
    offline: [
      '小满进程没在跑，去把 agent 启动一下吧～',
      '（离线状态）喊我一声，我马上醒！',
    ],
    working_type: [
      '正在写笔记，别打扰我敲键盘～',
      '素材好多，等我整理完这篇…',
    ],
    working_code: [
      '在跑巡检脚本，代码哗哗地过…',
      '抓到一个可疑信号，正在排查！',
    ],
    working_data: [
      '盯盘中，这曲线我得看清楚…',
      '早盘数据正在加载，稍等哦～',
    ],
    head: [
      '诶？摸头算不算内幕消息？',
      '别摸啦，发型都乱了！',
      '（眯眼）今天心情不错，准你摸一下',
    ],
    body: [
      '呀！吓我一跳～',
      '找我有事？点角色页可以和我聊天哦',
    ],
  };

  // ═══════════ 状态 ═══════════
  var state = {
    mounted: false,
    status: null,            // 最近一次 /api/agent/status 原始数据
    key: 'unknown',          // offline | leave | slack | working
    posture: 'type',         // working 细分：type | code | data
    thinking: false,
    renderer: 'idle',        // idle | loading | ready | failed
    model: null,             // Live2DModel（ready 后）
    app: null,
    idleTimer: null,
    bubbleTimer: null,
    miniAuto: false,         // 因窄屏自动收起
    sessionHidden: false,    // 用户点 × 隐藏（本会话）
  };

  // ═══════════ DOM 助手 ═══════════
  function $(id) { return document.getElementById(id); }
  var el = {
    pet: null, stage: null, canvas: null, fallback: null, scene: null,
    bubble: null, dot: null, mini: null, zzz: null,
  };
  function cacheEls() {
    el.pet = $('xm-pet');
    el.stage = $('xm-pet-stage');
    el.canvas = $('xm-pet-canvas');
    el.fallback = $('xm-pet-fallback');
    el.scene = $('xm-pet-scene');
    el.bubble = $('xm-pet-bubble');
    el.zzz = $('xm-pet-zzz');
    el.dot = $('xm-pet-dot');
    el.mini = $('xm-pet-mini');
  }

  // ═══════════ 场景层装配（小桌 + 笔记本骨架；动画全在 CSS）═══
  function buildScene() {
    if (!el.scene || el.scene.getAttribute('data-built')) return;
    var keys = '';
    for (var i = 0; i < 8; i++) keys += '<span class="xm-key"></span>';
    el.scene.innerHTML =
      '<div class="xm-desk">' +
        '<div class="xm-laptop">' +
          '<div class="xm-screen">' +
            '<div class="xm-screen-art">' +
              '<div class="xm-art-code"><span></span><span></span><span></span><span></span></div>' +
              '<div class="xm-art-data"><i></i><i></i><i></i><i></i><i></i><i></i></div>' +
              '<span class="xm-caret"></span>' +
            '</div>' +
          '</div>' +
          '<div class="xm-keyboard">' + keys + '</div>' +
        '</div>' +
        '<div class="xm-desk-top"></div>' +
      '</div>';
    el.scene.setAttribute('data-built', '1');
  }

  // ═══════════ 状态机：状态推导 + UI 应用 ═══════════
  function deriveKey(s) {
    if (!s.alive) return 'offline';
    if (s.attendance === 'leave') return 'leave';
    if (s.current_task) return 'working';
    return 'slack';
  }

  function derivePosture(s) {
    var tid = (s.current_task && s.current_task.task_id) || '';
    if (/morning_analysis|intraday_|evening_review|weekly_portfolio/.test(tid)) return 'data';
    if (/req_implement|bug_|logic_inspect|strategy_scan|experience_health|pending_remind/.test(tid)) return 'code';
    return 'type';
  }

  function applyStatus(s) {
    state.status = s;
    state.key = deriveKey(s);
    state.posture = s.current_task ? derivePosture(s) : 'type';
    paint();
  }

  function paint() {
    if (!el.pet) return;
    // thinking 为本地瞬时态，优先级最高；结束后回退到最近状态
    var key = state.thinking ? 'thinking' : state.key;
    el.pet.setAttribute('data-state', key);
    el.pet.setAttribute('data-posture', state.posture);
    // 隐藏时恢复显示（若处于收起态则保持，由按钮控制）
    if (state.thinking) {
      showBubble('…', true);
      setModelIdle(false);
    } else if (state.key === 'leave' || state.key === 'offline') {
      setModelIdle(false);
    } else if (state.key === 'working') {
      setModelIdle(true, 22000, 40000);
    } else {
      setModelIdle(true, 8000, 16000);
    }
  }

  // ═══════════ 气泡 ═══════════
  function showBubble(text, isThinking) {
    if (!el.bubble) return;
    clearTimeout(state.bubbleTimer);
    el.bubble.textContent = text;
    el.bubble.classList.toggle('xm-bubble-thinking', !!isThinking);
    el.bubble.hidden = false;
    if (isThinking) return;               // 思考中常驻，由 thinking 结束事件隐藏
    state.bubbleTimer = setTimeout(function () { hideBubble(); }, 4200);
  }
  function hideBubble() {
    if (el.bubble) el.bubble.hidden = true;
  }

  function pick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

  function stateLine() {
    var k = state.key;
    if (k === 'working') {
      var list = LINES['working_' + state.posture] || LINES.working_type;
      var name = (state.status && state.status.current_task && state.status.current_task.name) || '';
      return (name ? '小满正忙着「' + name + '」… ' : '') + pick(list);
    }
    return pick(LINES[k] || LINES.slack);
  }

  // ═══════════ 渲染层：探测 / 加载 / 控制（全 try-catch 静默降级）═══
  function assetExists(url) {
    return fetch(url, { method: 'HEAD', cache: 'no-store' })
      .then(function (r) { return r.ok; })
      .catch(function () { return false; });
  }
  function loadScript(url) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = url;
      s.onload = resolve;
      s.onerror = function () { reject(new Error('load fail: ' + url)); };
      document.head.appendChild(s);
    });
  }
  function showFallback() {
    if (el.fallback) el.fallback.hidden = false;
  }
  // 按模型入口扩展名选择运行时：*.model3.json → Cubism4；*.model.json → Cubism2
  // （Cubism2 资产生态 = live2d-widget-model-*：Pio / Shizuku / Hibiki 等官方示例模型）
  function runtimeFiles() {
    var v = CFG.vendor;
    if (/\.model\.json$/i.test(CFG.modelJson)) {
      return { kind: 'cubism2', files: [v.pixi, v.cubism2Core, v.l2d2] };
    }
    return { kind: 'cubism4', files: [v.pixi, v.cubism4Core, v.l2d4] };
  }

  function ensureRenderer() {
    if (state.renderer === 'ready' || state.renderer === 'loading') return;
    state.renderer = 'loading';
    showFallback();   // 加载期先显示占位，避免空白（就绪后由 initLive2D 隐藏）
    var rt = runtimeFiles();
    var files = rt.files.concat([CFG.modelJson]);
    Promise.all(files.map(assetExists))
      .then(function (ok) {
        if (ok.indexOf(false) !== -1) {
          state.renderer = 'failed';
          showFallback();
          console.info('[xm-pet] 资产缺失（static/live2d 未装 ' + rt.kind
            + ' 运行时或模型）→ 使用 🌾 占位。下载脚本见 scripts/fetch_live2d_assets.ps1');
          return;
        }
        console.info('[xm-pet] 资产齐全（' + rt.kind + '），加载运行时…');
        // 顺序：pixi → core → pixi-live2d-display（后者初始化需 core 全局）
        return loadScript(files[0]).then(function () { return loadScript(files[1]); })
          .then(function () { return loadScript(files[2]); });
      })
      .then(function () {
        if (state.renderer !== 'loading') return;   // 上面 failed 分支已置位
        initLive2D();
      })
      .catch(function () { state.renderer = 'failed'; showFallback(); });
  }

  function initLive2D() {
    try {
      if (typeof PIXI === 'undefined' || !PIXI.live2d) { state.renderer = 'failed'; showFallback(); return; }
      var host = el.canvas;
      if (!host) { state.renderer = 'failed'; return; }
      var app = new PIXI.Application({
        width: CFG.stageW,
        height: CFG.stageH,
        backgroundAlpha: 0,
        antialias: true,
        autoStart: true,
      });
      host.appendChild(app.view);
      state.app = app;
      PIXI.live2d.Live2DModel.from(CFG.modelJson).then(function (model) {
        state.model = model;
        state.renderer = 'ready';
        if (el.fallback) el.fallback.hidden = true;
        console.info('[xm-pet] LIVE2D 模型加载成功：' + CFG.modelJson);
        layoutModel();
        model.on('hit', function (areas) { onModelHit(areas); });
        // 视线跟随鼠标（模型原生支持时启用）
        try { model.autoInteract = true; } catch (e) { /* ignore */ }
        paint();   // 按当前状态补一次动作调度
      }).catch(function () { state.renderer = 'failed'; showFallback(); });
      resizeRenderer();
    } catch (e) {
      state.renderer = 'failed';
      showFallback();
    }
  }

  function layoutModel() {
    var m = state.model;
    if (!m || !state.app) return;
    try {
      var w = el.canvas ? el.canvas.clientWidth || CFG.stageW : CFG.stageW;
      var h = el.canvas ? el.canvas.clientHeight || CFG.stageH : CFG.stageH;
      var scale = (h * 0.98) / m.height;
      m.scale.set(scale, scale);
      m.anchor.set(0.5, 1);          // 底部居中 → 坐/站在场景桌后
      m.position.set(w / 2, h);
      resizeRenderer();
    } catch (e) { /* ignore */ }
  }

  function resizeRenderer() {
    if (!state.app || !el.canvas) return;
    try {
      var w = el.canvas.clientWidth || CFG.stageW;
      var h = el.canvas.clientHeight || CFG.stageH;
      if (w > 0 && h > 0) state.app.renderer.resize(w, h);
      if (state.model) {
        var scale = (h * 0.98) / state.model.height;
        state.model.scale.set(scale, scale);
        state.model.position.set(w / 2, h);
      }
    } catch (e) { /* ignore */ }
  }

  // 动作/表情：模型自带动作组有限，全部 best-effort（资产阶段可细化）
  function modelMotion(group, idx) {
    var m = state.model;
    if (!m) return;
    try { m.motion(group, idx == null ? 0 : idx); } catch (e) { /* ignore */ }
  }
  function modelExpression(name) {
    var m = state.model;
    if (!m) return;
    try { m.expression(name); } catch (e) { /* ignore */ }
  }

  // Idle 调度（节流：slack 8-16s 一次 / working 22-40s 一次 / 其余停）
  function setModelIdle(on, min, max) {
    clearTimeout(state.idleTimer);
    state.idleTimer = null;
    if (!on || !state.model || state.renderer !== 'ready') return;
    var delay = min + Math.random() * (max - min);
    state.idleTimer = setTimeout(function () {
      if (state.model && state.renderer === 'ready') {
        try { modelMotion('Idle', Math.floor(Math.random() * 6)); } catch (e) { /* ignore */ }
      }
      setModelIdle(true, min, max);
    }, delay);
  }

  // 摸头/身体局部反应（hit 区域名由模型 model3.json 定义）
  function onModelHit(areas) {
    var list = (areas || []).map(String).join(' ');
    if (/head/i.test(list)) {
      showBubble(pick(LINES.head));
      modelMotion('TapHead');
      modelExpression('happy');
    } else if (/body|chest|face/i.test(list)) {
      showBubble(pick(LINES.body));
      modelMotion('TapBody');
    }
  }

  // ═══════════ 拖拽 / 点击 ═══════════
  var drag = { on: false, sx: 0, sy: 0, ox: 0, oy: 0, moved: false };

  function placeAt(x, y) {
    if (!el.pet) return;
    el.pet.style.left = Math.round(x) + 'px';
    el.pet.style.top = Math.round(y) + 'px';
    el.pet.style.right = 'auto';
    el.pet.style.bottom = 'auto';
  }
  function persistPos() {
    if (!el.pet) return;
    try {
      localStorage.setItem('xm-pet-pos', JSON.stringify({
        x: el.pet.offsetLeft, y: el.pet.offsetTop,
      }));
    } catch (e) { /* ignore */ }
  }
  function applyStoredPos() {
    if (!el.pet) return;
    try {
      var raw = localStorage.getItem('xm-pet-pos');
      if (!raw) return;
      var p = JSON.parse(raw);
      if (typeof p.x === 'number' && typeof p.y === 'number') placeAt(p.x, p.y);
    } catch (e) { /* ignore */ }
  }

  function bindInteractions() {
    if (!el.pet || el.pet.getAttribute('data-bound')) return;
    el.pet.setAttribute('data-bound', '1');

    // 拖拽用 window 级监听（不用 setPointerCapture：capture 会把 pointerup 重定向到
    // 容器，Pixi 的 canvas 将收不到 pointerup → 摸头 hit 反应失效）
    function onDown(e) {
      if (e.target.closest('.xm-pet-btn')) return;   // 按钮不触发拖拽
      drag.on = true;
      drag.moved = false;
      drag.sx = e.clientX; drag.sy = e.clientY;
      drag.ox = el.pet.offsetLeft; drag.oy = el.pet.offsetTop;
      el.pet.classList.add('dragging');
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp);
      window.addEventListener('pointercancel', onUp);
    }
    function onMove(e) {
      if (!drag.on) return;
      var dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
      if (Math.abs(dx) + Math.abs(dy) > CFG.dragThreshold) drag.moved = true;
      if (!drag.moved) return;
      var nx = drag.ox + dx;
      var ny = drag.oy + dy;
      var maxX = window.innerWidth - (el.pet.offsetWidth || 300);
      var maxY = window.innerHeight - (el.pet.offsetHeight || 330);
      nx = Math.max(0, Math.min(nx, maxX));
      ny = Math.max(0, Math.min(ny, maxY));
      placeAt(nx, ny);
    }
    function onUp() {
      if (!drag.on) return;
      drag.on = false;
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
      el.pet.classList.remove('dragging');
      if (drag.moved) { persistPos(); return; }      // 拖过 → 不算点击
      // 未拖动 → 点击：模型就绪时局部互动走模型 hit 事件（摸头/身体反应）；
      // 降级（无模型）时任意点击弹状态气泡。
      if (state.renderer !== 'ready') showBubble(stateLine());
    }
    el.pet.addEventListener('pointerdown', onDown);

    $('xm-pet-btn-min').addEventListener('click', function () { minimize(); });
    $('xm-pet-btn-hide').addEventListener('click', function () { hidePet(); });
    el.mini.addEventListener('click', function () { summon(); });
  }

  function minimize() {
    if (!el.pet) return;
    state.sessionHidden = false;
    hideBubble();
    el.pet.classList.add('is-min');
    el.mini.classList.add('show');
  }
  function hidePet() {
    state.sessionHidden = true;
    minimize();
  }
  function summon() {
    state.sessionHidden = false;
    state.miniAuto = false;
    if (el.pet) el.pet.classList.remove('is-min');
    if (el.mini) el.mini.classList.remove('show');
  }
  function autoCollapse(on) {
    if (on) { if (!el.pet.classList.contains('is-min')) { state.miniAuto = true; minimize(); } }
    else if (state.miniAuto) { state.miniAuto = false; summon(); }
  }

  // ═══════════ 轮询（唯一状态源）═══════════
  async function tick() {
    if (!state.mounted) return;
    try {
      var resp = await Auth.fetchGet('/api/agent/status');
      if (!resp.ok) return;
      var s = await resp.json();
      window.__xmStatusCache = { t: Date.now(), data: s };
      applyStatus(s);
      try {
        document.dispatchEvent(new CustomEvent('xm:status', { detail: s }));
      } catch (e) { /* ignore */ }
    } catch (e) {
      // 401 已由 Auth 处理（切登录页 → xm:auth false → unmount）；网络抖动忽略
    }
  }

  // ═══════════ 挂载 / 卸载 ═══════════
  function maybeMount() {
    // 注意：auth.js 用 `const Auth` 声明 → 全局词法绑定，不在 window 上，须用裸 Auth
    if (typeof Auth === 'undefined' || !Auth.isLoggedIn()) {
      // 页面加载瞬间 Auth 尚未 init（token 未读）属预期，不打日志；
      // 真正的"登录了仍失败"由 xm:auth 事件分支的 mounted 日志暴露
      return;
    }
    var u = Auth.getUser();
    if (CFG.adminOnly && (!u || u.role !== 'admin')) {
      console.info('[xm-pet] 未挂载：CFG.adminOnly=true 且当前角色非 admin');
      return;
    }
    if (state.mounted) return;
    state.mounted = true;
    cacheEls();
    if (!el.pet) {
      state.mounted = false;
      console.warn('[xm-pet] DOM 中找不到 #xm-pet 容器 → 页面是旧缓存 HTML，请 Ctrl+Shift+R 强刷');
      return;
    }
    buildScene();
    bindInteractions();
    applyStoredPos();
    if (state.sessionHidden) { el.pet.classList.add('is-min'); el.mini.classList.add('show'); }
    else { el.pet.classList.remove('is-min'); el.mini.classList.remove('show'); }
    el.pet.setAttribute('aria-hidden', 'false');
    autoCollapse(window.innerWidth < CFG.minWidth);
    tick();                                    // 立即拉一次
    state.timer = setInterval(tick, CFG.pollMs);
    ensureRenderer();                          // 探测并（可选）加载 LIVE2D
    if (state.app) { try { state.app.start(); } catch (e) { /* ignore */ } }   // 重新登录后恢复渲染
    window.addEventListener('resize', onResize);
  }

  function unmount() {
    if (!state.mounted) return;
    state.mounted = false;
    clearInterval(state.timer);
    clearTimeout(state.idleTimer);
    window.removeEventListener('resize', onResize);
    if (state.app) { try { state.app.stop(); } catch (e) { /* ignore */ } }    // 暂停渲染循环
    if (el.pet) { el.pet.classList.add('is-min'); el.pet.setAttribute('aria-hidden', 'true'); }
    if (el.mini) el.mini.classList.remove('show');
    hideBubble();
  }

  function onResize() {
    autoCollapse(window.innerWidth < CFG.minWidth);
    resizeRenderer();
  }

  // ═══════════ 事件接线 ═══════════
  function bindEvents() {
    document.addEventListener('xm:auth', function (e) {
      var authed = !!(e.detail && e.detail.authed);
      if (authed) {
        maybeMount();
        // 登录/自动登录事件后的挂载结果（定位"登录了却没出现"的关键日志）
        console.info('[xm-pet] xm:auth(authed) → mounted=' + state.mounted
          + ' loggedIn=' + (typeof Auth !== 'undefined' ? Auth.isLoggedIn() : 'no-Auth')
          + ' hasDom=' + !!document.getElementById('xm-pet'));
      } else {
        unmount();
      }
    });
    document.addEventListener('xm:thinking', function (e) {
      if (!state.mounted) return;
      state.thinking = !!(e.detail && e.detail.on);
      if (state.thinking) { clearTimeout(state.idleTimer); }
      else { hideBubble(); }
      paint();
    });
  }

  // 启动：pet.js 最后加载；若用户已带 token 自动登录（dashboard.js DOMContentLoaded
  // 内 showApp() 派发 xm:auth），此监听必然先于事件注册完毕。
  cacheEls();
  bindEvents();
  // 兜底：若页面加载时已登录（事件可能先于本脚本派发——实际不会，但双保险）
  if (typeof Auth !== 'undefined' && Auth.isLoggedIn()) maybeMount();

  // 调试出口
  window.Pet = {
    getState: function () { return state; },
    forceTick: tick,
  };
})();
