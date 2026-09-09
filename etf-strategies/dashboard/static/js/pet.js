/* ═══════════════════════════════════════════════════════════════
   pet.js — 小满 LIVE2D 桌宠（看板娘）主模块

   架构（三层）：
     - 控制层（本文件）：状态机 + 唯一轮询源 + 交互
       状态来源：GET /api/agent/status（30s）→ 机器可读 state（后端已加：
       offline / leave / working / slack），本地瞬时态 thinking 由 agent.js
       发 CustomEvent('xm:thinking') 叠加。轮询结果广播 CustomEvent('xm:status')
       （agent.js 订阅更新角色页状态 pill，自身不再轮询）。
     - 场景层：已移除（不再展示小桌/笔记本/键盘等 CSS 驱动动画）
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
    // 当前选用：Senko 仙狐（社区 Cubism4，moc3 v2）— Q 版坐姿橘发狐娘，
    // 暖橘毛色与小满蜜橘 accent 呼应；动作组 Idle/Tap/Taphead/Tick_5
    // （含 Singing 唱歌、Sleeping 睡觉趣味动作），无表情（表情联动自动跳过）
    modelJson: '/static/live2d/model/Senko/senko.model3.json',
    stageW: 360, stageH: 254, // 与 pet.css 的 canvas 区域一致（舞台 360x300 减场景让位）
    fitFactor: 1.08,          // 模型高占舞台比（bounds 内角色头顶约 16% 留白，1.08 不裁耳）
  };

  // ═══════════ 台词库（人设语气；仅状态播报/日常，不含投资指令）═══
  var LINES = {
    greet: [
      '小满就位！盯盘、写笔记，随时喊我～',
      '我在哦，点"角色"页就能找我聊天～',
    ],
    slack: [
      '摸鱼中…今天又是谁在 ETF 里偷跑？',
      '收盘了才敢说的悄悄话：我也在盯大盘…',
      '要不要聊聊天？我最近在读宏观周报～',
      '忙完啦，喝口水…你那边行情怎么样？',
    ],
    leave: [
      '小满请假了，有事留言，回来再回～',
      '呼…今天休息，复盘笔记明天补！',
    ],
    sleep: [
      'Zzz…夜深了，小满先睡，明早 6 点见～',
      '呼呼…梦里还在看 K 线…（梦话）',
      '关灯睡觉！行情明天再聊～',
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
    working_read: [
      '阅读时间…这份研报有点东西，别吵我～',
      '正在啃长文，读完给你划重点！',
      '安静看书中…这段宏观分析值得细品。',
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
    key: 'unknown',          // offline | leave | sleep | slack | working
    lastKey: null,           // 上一次 key（状态切换沿检测）
    posture: 'type',         // working 细分：type | code | data | read（read=阅读，不显示场景动画）
    thinking: false,
    renderer: 'idle',        // idle | loading | ready | failed
    model: null,             // Live2DModel（ready 后）
    app: null,
    idleTimer: null,
    bubbleTimer: null,
    greetTimer: null,
    sleepTimer: null,        // 作息钟边界定时器（22:00 / 06:00 立即翻转）
    moods: null,             // 表情分类结果 { happy, surprise }
    greeted: false,          // 本会话已打招呼
    miniAuto: false,         // 因窄屏自动收起
    sessionHidden: false,    // 用户点 × 隐藏（本会话）
    ro: null,                // 画布容器 ResizeObserver（尺寸沉降后重新布局）
  };

  function isCollapsed() {
    return !el.pet || el.pet.classList.contains('is-min');
  }

  // ═══════════ DOM 助手 ═══════════
  function $(id) { return document.getElementById(id); }
  var el = {
    pet: null, stage: null, canvas: null, fallback: null, scene: null,
    bubble: null, mini: null, zzz: null, modes: null,
  };
  function cacheEls() {
    el.pet = $('xm-pet');
    el.stage = $('xm-pet-stage');
    el.canvas = $('xm-pet-canvas');
    el.fallback = $('xm-pet-fallback');
    el.scene = $('xm-pet-scene');
    el.bubble = $('xm-pet-bubble');
    el.zzz = $('xm-pet-zzz');
    el.mini = $('xm-pet-mini');
    el.modes = $('xm-pet-modes');
  }

  function buildScene() {}

  // ═══════════ 状态机：状态推导 + UI 应用 ═══════════
  // 作息钟：22:00–次日 06:00 为睡眠时间（强制 sleep；进程未跑的 offline 不遮蔽）
  function isSleepHour(d) {
    d = d || new Date();
    var h = d.getHours();
    return h >= 22 || h < 6;
  }

  function deriveKey(s) {
    // 状态来源唯一化：手动切换已落库后端（/api/agent/state），桌宠只跟随后端
    var k;
    if (!s || !s.alive || s.state === 'offline') k = 'offline';
    else if (s.state) k = s.state;
    else if (s.attendance === 'leave') k = 'leave';
    else if (s.current_task) k = 'working';
    else k = 'slack';
    // 睡眠时间：工作/摸鱼/请假都去睡（offline 保留——那是进程没跑，需提示）
    if (k !== 'offline' && isSleepHour()) k = 'sleep';
    return k;
  }

  function recompute() {
    var s = state.status || {};
    state.key = deriveKey(s);
  }

  function applyStatus(s) {
    var prevKey = state.key;
    state.status = s;
    recompute();
    paint();
    if (prevKey && prevKey !== state.key) onKeyChange(prevKey, state.key);
  }

  // ── 状态切换沿：气泡播报 + 动作/表情联动 ──
  function onKeyChange(prev, k) {
    if (isCollapsed()) return;
    if (k === 'working') {
      announce(stateLine(), 5200);
      modelMotionAny(['Tap', 'TapBody', 'Idle', 'idle'], Math.floor(Math.random() * 2));
      modelResetExpression();
    } else if (k === 'slack') {
      if (prev === 'working' || prev === 'thinking') announce(pick(LINES.slack), 4800);
      modelResetExpression();
    } else if (k === 'sleep') {
      announce(pick(LINES.sleep), 5200);
      // 入睡：Senko Tick_5=Sleeping（zzz 由 CSS 叠加）；无此动作组则 Idle
      modelMotionAny(['Tick_5', 'TapBody', 'Idle', 'idle'], 0);
    } else if (k === 'leave') {
      announce(pick(LINES.leave), 5200);
      // 请假休息：Senko Tick_5=Sleeping（zzz 动画由 CSS 叠加）；其它模型用手势
      modelMotionAny(['Tick_5', 'TapBody', 'Idle', 'idle'], 0);
      modelMood('happy');
    } else if (k === 'offline') {
      announce(pick(LINES.offline), 5200);
    }
  }

  // ── 手动改后端状态（随机/阅读/摸鱼，全部走 /api/agent/state）──
  async function manualState(action) {
    var tips = {
      random: '随机一个状态，看看我接下来干嘛～',
      reading: '切到阅读啦（读文章由常驻进程调度执行）',
      slack: '摸鱼中～有正事再叫我',
    };
    showBubble(tips[action] || '切换状态中…');
    try {
      var resp = await Auth.fetchPost('/api/agent/state', { action: action });
      var j = await resp.json().catch(function () { return {}; });
      if (!resp.ok) {
        showBubble('切换失败：' + ((j && j.detail) || ('HTTP ' + resp.status)));
        return;
      }
      // 手动切换已落库后端 → 桌宠永远跟随后端状态（下次轮询即校准）
      paintModeButtons();
      var lbl = (j.state && j.state.label) || '';
      showBubble(lbl + (j.state && j.state.changed === false ? '（本来就是）' : '，已切换'));
    } catch (e) {
      showBubble('切换失败：' + e.message);
    }
    tick();
  }

  // 按钮高亮跟随后端真实状态：阅读=正处于阅读态；摸鱼=当前在非工作池；随机是瞬时动作不常亮
  function paintModeButtons() {
    if (!el.modes) return;
    var cur = (state.status && state.status.current_state) || '';
    var btns = el.modes.querySelectorAll('.xm-pet-mode');
    for (var i = 0; i < btns.length; i++) {
      var m = btns[i].getAttribute('data-mode');
      var on = (m === 'reading' && cur === 'reading') ||
               (m === 'slack' && state.key === 'slack');
      btns[i].classList.toggle('is-active', on);
    }
  }

  // ── 作息钟边界：到 22:00 / 06:00 立即重算（不等 30s 轮询）──
  function scheduleSleepFlip() {
    clearTimeout(state.sleepTimer);
    var now = new Date();
    var next = new Date(now);
    var h = now.getHours();
    if (h < 6) next.setHours(6, 0, 5, 0);          // 今早 06:00 起床
    else if (h < 22) next.setHours(22, 0, 5, 0);    // 今晚 22:00 入睡
    else next.setHours(30, 0, 5, 0);                // 次日 06:00（setHours 自动跨天）
    state.sleepTimer = setTimeout(function () {
      if (state.mounted) {
        var prevKey = state.key;
        recompute();
        paint();
        if (prevKey && prevKey !== state.key) onKeyChange(prevKey, state.key);
      }
      scheduleSleepFlip();
    }, next - now);
  }

  function paint() {
    if (!el.pet) return;
    // thinking 为本地瞬时态，优先级最高；结束后回退到最近状态
    var key = state.thinking ? 'thinking' : state.key;
    el.pet.setAttribute('data-state', key);
    paintModeButtons();
    // 隐藏时恢复显示（若处于收起态则保持，由按钮控制）
    if (state.thinking) {
      showBubble('…', true);
      setModelIdle(false);
    } else if (key === 'leave' || key === 'offline') {
      setModelIdle(false);
    } else if (key === 'sleep') {
      setModelIdle(true, 20000, 32000);    // 睡眠：定时重播 Sleeping 动作
    } else if (key === 'working') {
      setModelIdle(true, 22000, 40000);
    } else {
      setModelIdle(true, 8000, 16000);
    }
  }

  // ═══════════ 气泡 ═══════════
  function showBubble(text, isThinking, dwell) {
    if (!el.bubble) return;
    clearTimeout(state.bubbleTimer);
    el.bubble.textContent = text;
    el.bubble.classList.toggle('xm-bubble-thinking', !!isThinking);
    el.bubble.hidden = false;
    if (isThinking) return;               // 思考中常驻，由 thinking 结束事件隐藏
    state.bubbleTimer = setTimeout(function () { hideBubble(); }, dwell || 4200);
  }
  // 状态/日常播报：收起或离线气泡？收起态不打扰
  function announce(text, dwell) {
    if (isCollapsed()) return;
    if (state.thinking) return;           // 思考中的"…"气泡优先
    showBubble(text, false, dwell);
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
        // 布局基准取 internalModel 的布局尺寸（与姿势/首帧渲染时机无关）：
        // model.width/height 走 getBounds()，在模型尚未完成首帧更新或容器尚未布局时
        // 可能偏小甚至为 0 → scale 被放大 → 角色超出画布、头顶被裁（刷新后偶发"看不到头"）。
        var im0 = model.internalModel || {};
        state.origW = im0.width || model.width;
        state.origH = im0.height || model.height;
        app.stage.addChild(model);   // 必须入舞台才会渲染
        state.renderer = 'ready';
        if (el.fallback) el.fallback.hidden = true;
        console.info('[xm-pet] LIVE2D 模型加载成功：' + CFG.modelJson
          + '（原生 ' + Math.round(state.origW) + 'x' + Math.round(state.origH) + '）');
        layoutModel();
        // 首帧后再布局一次：resolve 瞬间容器 clientHeight 可能仍为 0（fixed 容器尚未沉降），
        // 二次布局用真实尺寸自愈，避免按 254 兜底值缩放导致头顶被裁。
        requestAnimationFrame(function () { layoutModel(); });
        // 容器尺寸变化（字体加载、布局沉降、收起/展开、缩放）时重新布局
        if (typeof ResizeObserver !== 'undefined' && el.canvas && !state.ro) {
          try {
            state.ro = new ResizeObserver(function () { layoutModel(); });
            state.ro.observe(el.canvas);
          } catch (e) { state.ro = null; }
        }
        model.on('hit', function (areas) { onModelHit(areas); });
        // 视线跟随鼠标（模型原生支持时启用）
        try { model.autoInteract = true; } catch (e) { /* ignore */ }
        classifyMoods();
        paint();   // 按当前状态补一次动作调度
        // 就位打招呼（延后一点，等模型第一帧渲染）
        if (!state.greeted && !isCollapsed()) {
          state.greeted = true;
          clearTimeout(state.greetTimer);
          state.greetTimer = setTimeout(function () {
            if (state.mounted && !state.thinking) {
              modelMood('happy');
              announce(pick(LINES.greet), 5200);
            }
          }, 1400);
        }
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
      // 基准高度优先取 internalModel.height（布局尺寸，稳定且与姿势无关），
      // 退回加载时记录的原生高度，最后才用 getBounds 的 m.height。
      var im = m.internalModel || {};
      var origH = im.height || state.origH || m.height;
      // 尺寸未就绪（0/NaN）时不布局，等下一帧或 ResizeObserver 再试，
      // 否则 scale=Infinity/巨大 → 模型被放大到只剩脚、头顶飞出画布。
      if (!origH || !isFinite(origH) || origH <= 0) return;
      var scale = (h * (CFG.fitFactor || 0.98)) / origH;   // 以原生尺寸为基准，底部居中
      if (!isFinite(scale) || scale <= 0) return;
      m.scale.set(scale, scale);
      m.anchor.set(0.5, 1);
      m.position.set(w / 2, h);
      if (w > 0 && h > 0) state.app.renderer.resize(w, h);
    } catch (e) { /* ignore */ }
  }

  function resizeRenderer() {
    if (!state.app || !el.canvas) return;
    try {
      var w = el.canvas.clientWidth || CFG.stageW;
      var h = el.canvas.clientHeight || CFG.stageH;
      if (w > 0 && h > 0) state.app.renderer.resize(w, h);
      if (state.model) layoutModel();
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

  // 表情名跨生态不一：Cubism4 官方模型（Haru）为 F01–F08 无 'happy'，
  // 有语义名优先用语义名，否则从模型定义的表情里随机一个；无表情（Cubism2 Koharu）则跳过
  function modelExpressionAny(preferred) {
    var m = state.model;
    if (!m) return;
    try {
      // pixi-live2d-display 0.4：表情管理器挂在 motionManager 下
      var im = m.internalModel || {};
      var em = im.expressionManager
        || (im.motionManager && im.motionManager.expressionManager);
      var defs = (em && em.definitions) || [];
      var names = defs.map(function (d) { return d.Name || d.name; }).filter(Boolean);
      if (!names.length) return;
      var pick = names.indexOf(preferred) >= 0
        ? preferred
        : names[Math.floor(Math.random() * names.length)];
      m.expression(pick);
    } catch (e) { /* ignore */ }
  }

  // 不同生态动作组名大小写不一：Cubism4 官方模型为 'Idle'/'TapHead'，
  // Cubism2 live2d-widget 生态为小写 'idle' → 依次尝试，第一个命中即停
  function modelMotionAny(groups, idx) {
    var m = state.model;
    if (!m) return;
    for (var i = 0; i < groups.length; i++) {
      try {
        var r = m.motion(groups[i], idx == null ? 0 : idx);
        if (r) return;
      } catch (e) { /* ignore */ }
    }
  }

  // ── 表情语义分类：Cubism4 表情为 F01…F0x 无语义名，读表情参数打分 ──
  // happy   = 嘴角上扬（ParamMouthForm 大）或笑到眯眼
  // surprise= 张嘴 + 睁眼（思考/惊讶共用）
  function classifyMoods() {
    var m = state.model;
    state.moods = {};
    if (!m) return;
    try {
      var im = m.internalModel || {};
      var em = im.expressionManager || (im.motionManager && im.motionManager.expressionManager);
      if (!em || !em.expressions || !em.expressions.length) return;
      var defs = em.definitions || [];
      em.expressions.forEach(function (ex, i) {
        var name = (defs[i] && (defs[i].Name || defs[i].name)) || null;
        if (!name) return;
        var smile = 0, openMouth = 0, closedEye = 0;
        (ex._parameters || []).forEach(function (p) {
          if (p.id === 'ParamMouthForm') smile = p.value;
          if (p.id === 'ParamMouthOpenY') openMouth = p.value;
          if (p.id === 'ParamEyeLOpen' || p.id === 'ParamEyeROpen') {
            closedEye += (1 - Math.min(1, Math.max(0, p.value))) / 2;
          }
        });
        if (smile > 0.55 || (closedEye > 0.55 && smile > 0)) {
          if (!state.moods.happy) state.moods.happy = name;
        } else if (openMouth > 0.55 && closedEye < 0.4) {
          if (!state.moods.surprise) state.moods.surprise = name;
        }
      });
      console.info('[xm-pet] 表情分类：' + JSON.stringify(state.moods));
    } catch (e) { state.moods = {}; }
  }
  function modelMood(mood) {
    var m = state.model;
    if (!m || !state.moods || !state.moods[mood]) return false;
    try { m.expression(state.moods[mood]); return true; } catch (e) { return false; }
  }
  function modelResetExpression() {
    var m = state.model;
    if (!m) return;
    try {
      var im = m.internalModel || {};
      var em = im.expressionManager || (im.motionManager && im.motionManager.expressionManager);
      if (em && em.stopAllExpressions) em.stopAllExpressions();
    } catch (e) { /* ignore */ }
  }

  // 行为调度（节流）：slack —— 待机动作 + 偶尔自言自语；
  // working —— 待机与手势动作穿插（伸懒腰/比划），偶尔播报进度；其余状态停
  function setModelIdle(on, min, max) {
    clearTimeout(state.idleTimer);
    state.idleTimer = null;
    if (!on || !state.model || state.renderer !== 'ready') return;
    var delay = min + Math.random() * (max - min);
    state.idleTimer = setTimeout(function () {
      if (state.model && state.renderer === 'ready' && !isCollapsed()) {
        if (state.thinking) {
          /* 思考中：保持"…"，不打扰 */
        } else if (state.key === 'sleep') {
          // 睡眠：重播睡觉动作（Senko Tick_5=Sleeping），保持安睡不说话
          modelMotionAny(['Tick_5', 'Idle', 'idle'], 0);
        } else if (state.key === 'working') {
          if (Math.random() < 0.45) {
            modelMotionAny(['Tap', 'TapBody', 'Idle', 'idle'], Math.floor(Math.random() * 2));
          } else {
            modelMotionAny(['Idle', 'idle'], Math.floor(Math.random() * 3));
          }
          if (Math.random() < 0.3) announce(stateLine(), 4600);
        } else if (state.key === 'slack') {
          // 摸鱼偶尔哼歌：Senko Taphead[0]=Singing；Haru TapHead 同理
          if (Math.random() < 0.22) {
            modelMotionAny(['Taphead', 'TapHead', 'Idle', 'idle'], 0);
          } else {
            modelMotionAny(['Idle', 'idle'], Math.floor(Math.random() * 3));
          }
          if (Math.random() < 0.32) {
            announce(pick(LINES.slack), 5000);
            if (Math.random() < 0.5) modelMood('happy');   // 自言自语时偶尔笑一下
          }
        }
      }
      setModelIdle(true, min, max);
    }, delay);
  }

  // 摸头/身体局部反应（hit 区域名由模型 model3.json 定义）
  function onModelHit(areas) {
    state.hitFired = true;
    var list = (areas || []).map(String).join(' ');
    if (/head/i.test(list)) {
      showBubble(pick(LINES.head));
      // Senko 摸头 → Taphead 组（Singing/Sleeping）；Haru → TapHead；都无则 Idle
      modelMotionAny(['Taphead', 'TapHead', 'Tap', 'TapBody', 'Idle', 'idle'],
                     Math.floor(Math.random() * 2));
      modelMood('happy') || modelExpressionAny('happy');
    } else if (/body|chest|face/i.test(list)) {
      showBubble(pick(LINES.body));
      modelMotionAny(['Tap', 'TapBody', 'Taphead', 'TapHead', 'Idle', 'idle'],
                     Math.floor(Math.random() * 2));
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
      if (e.target.closest('.xm-pet-btn, .xm-pet-mode')) return;   // 按钮不触发拖拽
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
      if (state.thinking) return;                    // 思考中不打断"…"气泡
      // 未拖动 → 点击：模型就绪时局部互动走模型 hit 事件（摸头/身体反应）；
      // 降级（无模型）时任意点击弹状态气泡。
      if (state.renderer !== 'ready') { showBubble(stateLine()); return; }
      // Cubism2 老模型常未定义 hit_areas → hit 事件不触发；180ms 内无反应则兜底弹台词
      state.hitFired = false;
      setTimeout(function () {
        if (!state.hitFired && state.mounted) showBubble(stateLine());
      }, 180);
    }
    el.pet.addEventListener('pointerdown', onDown);

    $('xm-pet-btn-min').addEventListener('click', function () { minimize(); });
    $('xm-pet-btn-hide').addEventListener('click', function () { hidePet(); });
    el.mini.addEventListener('click', function () { summon(); });
    // 状态手动切换：随机 / 阅读 / 摸鱼（走 /api/agent/state，落库后端并记入"做过的事"）
    if (el.modes) {
      el.modes.addEventListener('click', function (e) {
        var btn = e.target.closest('.xm-pet-mode');
        if (!btn) return;
        manualState(btn.getAttribute('data-mode'));   // random | reading | slack
      });
    }
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
    scheduleSleepFlip();                       // 作息钟：22:00 / 06:00 边界自动翻转
    ensureRenderer();                          // 探测并（可选）加载 LIVE2D
    if (state.app) { try { state.app.start(); } catch (e) { /* ignore */ } }   // 重新登录后恢复渲染
    window.addEventListener('resize', onResize);
  }

  function unmount() {
    if (!state.mounted) return;
    state.mounted = false;
    clearInterval(state.timer);
    clearTimeout(state.idleTimer);
    clearTimeout(state.sleepTimer);
    if (state.ro) { try { state.ro.disconnect(); } catch (e) { /* ignore */ } state.ro = null; }
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
      var on = !!(e.detail && e.detail.on);
      if (on === state.thinking) return;
      state.thinking = on;
      if (on) {
        clearTimeout(state.idleTimer);
        // 思考沿：困惑表情 + 手势动作（best-effort；Senko 无表情→仅动作）
        if (state.renderer === 'ready') {
          if (!modelMood('surprise')) modelExpressionAny('surprise');
          modelMotionAny(['Tap', 'TapBody', 'Taphead', 'TapHead', 'Idle', 'idle'],
                         Math.floor(Math.random() * 2));
        }
      } else {
        hideBubble();
        modelResetExpression();
      }
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
