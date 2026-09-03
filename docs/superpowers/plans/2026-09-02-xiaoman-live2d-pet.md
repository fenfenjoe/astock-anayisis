# 小满第三轮优化计划 — Q 版 LIVE2D 桌宠（看板娘）

> 日期：2026-09-02 | 流程：dev-workflow（brainstorming → writing-plans → TDD → executing-plans → design-critique）
> 前置：Dashboard v2.1 单页（FastAPI + dashboard.html + 原生 JS/CSS）、小满角色页与 `/api/agent/status` 已上线
> 决策（用户已确认）：**D1 形象路线 = 真 Live2D（开源模型自托管）｜ D2 展示范围 = 全局右下角 fixed 悬浮 ｜ D3 交互 = 点击气泡 + 可拖拽 + 最小化/隐藏 + 局部互动反应（全选）**
>
> 执行状态（2026-09-02）：
> - ✅ 后端微改：scheduler `current_task` 补 `task_id`；`/api/agent/status` 加机器可读 `state`（offline/leave/working/slack）——测试增补，**全量 429 passed**
> - ✅ 前端骨架：`dashboard.html` 挂载点 + `pet.css`（场景层全套动画）+ `pet.js`（状态机/轮询单源/交互/渲染层降级抽象）；`agent.js` 轮询收敛为订阅 `xm:status` + 思考态联动；`dashboard.js` 登录门控事件
> - ✅ 回归加固（2026-09-02 续）：design-critique 反模式自检并修复（加载期 fallback 占位、按钮 `:active` 态）；新增 `tests/test_pet_frontend.py`（模板挂载 GET / 冒烟、ID 契约、data-state/posture CSS 全覆盖、跨模块事件契约、vendor 布局一致）——**全量 435 passed / 2 skipped**
> - ✅ 浏览器级验收（2026-09-02 无头 Chrome harness，降级模式=无资产/无网）：working(姿态 data) → 场景构建 → 点击气泡 → thinking → leave(Zzz) → offline → 最小化/召回，**全链路零 JS 异常**；下载/预览脚本补 UTF-8 BOM 修复 GBK 乱码
> - ⛔ **资产阻塞（环境沙箱断网）**：LIVE2D 运行时+模型无法代下。已备 `scripts/fetch_live2d_assets.ps1`（一键下载，支持 `-AddModel` 增量拉取任一 GitHub 模型目录）+ `scripts/fetch_live2d_preview.ps1`（预览/截图），在有外网机器执行后 git 提交 → 试渲染 → **用户拍板模型** → 设 `pet.js` 顶部 `CFG.modelJson` → 渲染层验收

## 一、目标

给小满做一个 **Q 版 LIVE2D 桌宠**，常驻 Dashboard 右下角（`position: fixed`，页面滚动不位移）：

1. **状态驱动动画**：根据小满真实状态切换动画/场景 —— 工作（对着电脑敲键盘/盯数据）、摸鱼、请假、离线、思考中。
2. **桌宠式交互**：点击冒台词气泡、可拖拽换位（记忆位置）、可最小化/隐藏、摸头等局部互动反应。
3. **零外网依赖**：运行时与模型全部自托管在 `/static`（沿用本项目"字体/echarts/marked 全部本地化"铁律）。

## 二、现状盘点（事实锚点）

| 项 | 现状 | 对本方案的影响 |
|---|---|---|
| 状态 API | `GET /api/agent/status` → `{alive, heartbeat_age_seconds, dsh_ready, attendance: 'on'\|'leave', current_task, mood:{label,icon}, published_on, last_rss_fetch_at}` | 桌宠状态源现成；**缺机器可读的 state 枚举** |
| current_task | `scheduler.current_task()` 返回 `{name, started_at}`（`_mark_running` 未存 task_id） | 无法按任务类型细分"工作姿态"→ **需小改** |
| 轮询 | agent.js 仅在进入角色页后 30s 轮询 `loadStatus()`，更新 `#agent-mood` pill | 全局桌宠需要**独立于角色页**的轮询 → 轮询权收敛到 pet.js |
| 页面结构 | 单页 6 个 view（`dashboard.html`），`#app-main` 登录后显示；header sticky z-100 | 桌宠容器挂 body 末尾，z 高于内容低于登录遮罩 |
| 权限 | token 含 `role`；`nav-admin`（角色/日程）仅 admin（dashboard.js `role==='admin'`） | 桌宠建议同权限门控（默认仅 admin） |
| 设计基调 | Tech Noir 骨架 + 小满蜜橘/琥珀暖色 accent（agent.css：`--xm-accent: oklch(0.78 0.15 60)`） | 桌宠舞台/场景层复用该 token 家族，不另起炉灶 |
| 构建约束 | 无打包器，原生 script 标签；国内网络，禁外链 CDN | 所有依赖 vendored 为本地静态文件 |
| 人设 | 18± 元气少女，名字源于节气「小满」；对话禁止投资建议词 | 台词库按人设写；气泡内容仅状态播报/日常，不涉及投资指令 |

## 三、总体架构（三层分离）

```
┌────────────────────────────────────────────────┐
│  控制层  static/js/pet.js                       │  ← 状态机（唯一轮询者）+ 交互 + 台词
│    · 30s 轮询 /api/agent/status → state 推导     │     通过 CustomEvent('xm:status') 广播
│    · 监听 'xm:thinking'（聊天 streaming）        │     （agent.js 订阅更新状态 pill，删自身轮询）
│    · 拖拽/点击/hit 区域/最小化/隐藏 事件          │
├────────────────────────────────────────────────┤
│  场景层  容器 DOM + SVG 小舞台（pet.css 动画）    │  ← 敲键盘/盯屏/Zzz 等"语义动画"在这层做
│    小桌 + 笔记本(屏幕/键盘) + 状态小灯 + 气泡     │     （Live2D 模型没有"敲键盘"motion，语义由场景层表达）
├────────────────────────────────────────────────┤
│  渲染层  PixiJS + pixi-live2d-display + Cubism   │  ← 真 Live2D 模型（少女/Q 版 2-3 选 1）
│    模型本体动画：Idle/表情/视线跟随/摸头反应       │     静态资源全 vendored 于 static/live2d/
└────────────────────────────────────────────────┘
```

**为什么"敲键盘"动画要拆两层做（关键设计）**：官方免费 Live2D 模型只自带通用 motion 组（Idle/点头/挥手等），没有"打字/盯 K 线"动作。所以工作语义由**场景层 SVG 动画**（键盘键帽律动高亮、屏幕滚字/曲线波动）承担，渲染层负责角色本体姿态（播放 Idle 中较"专注"的 motion + 切表情 + 视线朝屏幕）。两层叠加即呈现"小满对着电脑工作"的桌宠画面，且不依赖付费定制模型。

## 四、技术选型与资产（自托管，全部入 git）

| 组件 | 选型 | 说明/来源 | License |
|---|---|---|---|
| 渲染库 | [pixi-live2d-display](https://github.com/guansss/pixi-live2d-display) + [PixiJS](https://github.com/pixijs/pixijs) | 程序化控制模型（`motion()/expression()/on('hit')`），vanilla 友好，无打包器可用 UMD dist | MIT |
| Cubism 运行时 | `live2dcubismcore.min.js`（Cubism 4/5 core） | 官方 CDN 下载一次后 vendored；`https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js` | Live2D Proprietary（随应用分发免费） |
| 模型（2-3 候选选 1） | 官方免费示例模型，**少女/Q 版向优先** | 保底可用：[CubismWebSamples](https://github.com/Live2D/CubismWebSamples) 内 Cubism4 模型（Haru / Natori 等少女系）；更 Q 的官方吉祥物系（Pio/Koharu 等）需核实是否有 Cubism4 格式，无则放弃或降级 | [Live2D Sample Material Terms](https://www.live2d.com/eula/live2d-sample-model-terms_en.html)：可随应用免费商用，**需署名 Live2D、不得单独再分发模型文件** |
| 备选方案（不采用，仅记录） | [stevenjoezhang/live2d-widget](https://github.com/stevenjoezhang/live2d-widget) | Cubism2 一键看板娘，但对外暴露的控制面不足以做状态机细分/自定义场景 → 不选 | — |

**模型选型流程（Step 0）**：本地把 2~3 个候选模型各渲染 1 屏截图对比，用户当场拍板——画风是主观项，不进自动化。

**署名义务**：README「致谢」+ 桌宠 About 气泡/设置处加一行 `Character © Live2D Inc.`（合规且零成本）。

## 五、状态机设计

### 5.1 状态枚举（后端微改后提供）

后端 `agent_status()` 新增机器可读字段 `state`（向后兼容，`mood` 等原字段不动）：

| state | 推导 | 备注 |
|---|---|---|
| `offline` | `alive == False` | 进程未运行，优先于一切 |
| `leave` | `alive && attendance=='leave'` | 请假中 |
| `working` | `alive && attendance=='on' && current_task` | 上班且正在做任务 |
| `slack` | `alive && attendance=='on' && !current_task` | 摸鱼中 |

前端另有**本地瞬时态**（不进后端）：`thinking`（聊天 streaming 中，agent.js 发 `xm:thinking` 事件）→ 临时打断 idle，优先级最高、结束即回退。

### 5.2 状态 → 动画映射表

| 状态 | 角色本体（渲染层） | 场景层动画 | 气泡文案示例（点击触发） |
|---|---|---|---|
| `working` | 切"专注"Idle motion + 视线朝屏幕；随机小动作降频 | **小桌+笔记本亮起**：屏幕滚字/曲线波动；工作细分见 5.3 | 「正在跑早盘分析，别打扰我盯盘～」「写复盘呢，数据先对一下」 |
| `slack` | 播放 Idle 随机动作（正常频率），视线跟随鼠标 | 无工作台或只留半杯奶茶装饰 | 「摸鱼中…今天 ETF 又是谁在偷跑？」 |
| `leave` | 定格 + 降饱和（CSS filter） | 趴桌睡觉剪影 + 飘 `Z z z` | 「小满请假了，有事留言，回来再回～」 |
| `offline` | 定格灰阶（grayscale）+ 停止一切 motion | 状态灯灰 ⚪ | 「小满进程没在跑，先去启动 agent 吧」 |
| `thinking`（瞬时） | 暂停 idle 循环，眼睛看输入框方向 | 「…」三点气泡 | （不弹气泡，仅视觉） |

### 5.3 任务类型 → 工作姿态（working 细分）

后端 `_mark_running` 补存 `task_id` 后，`current_task` 携带 `task_id`，前端按下表归并（未知 id → 默认"通用敲键盘"）：

| task_id 前缀/关键字 | 工作姿态 | 场景层表现 |
|---|---|---|
| `morning_analysis` / `intraday_*` / `evening_review` / `weekly_portfolio` | **盯数据/看盘** | 屏幕内迷你 K 线/数字滚动 |
| `req_implement` / `bug_*` / `logic_inspect` / `strategy_scan_weekly` / `experience_health` | **敲代码/巡检** | 键盘键帽律动 + 屏幕跑代码行 |
| 其它 / 未知 | **通用打字** | 键盘律动 + 光标闪烁 |

> 映射表放 `pet.js` 常量（含关键词兜底），不动后端文案；后端只补 `task_id` 透传。

## 六、场景与视觉设计（design 决策）

按 frontend-design 规范输出设计决策，实现后过 design-critique 44 条反模式自检：

- **美学方向**：维持产品 Tech Noir 骨架，桌宠舞台做"深色剪影 + 蜜橘光晕"的暖色延伸（复用 `agent.css` 的 `--xm-accent` 等 token，不新建色系）。
- **舞台布局**：容器默认右下角（`right: 20px; bottom: 16px`），本体 ~ 240×300 canvas + 下缘小舞台（桌/笔记本 SVG，同宽 ~ 320px）；z-index 设在内容层与登录遮罩之间（登录遮罩之上不显示宠物）。
- **配色**：桌/笔记本用 `--bg-surface-2` 系 + `--border` 描边；键盘/屏幕高亮用 `--xm-accent` 蜜橘与琥珀；状态小灯沿用绿/灰语义色。**无紫色渐变、无纯灰**。
- **动效强度**：本体 idle 属于 delight 层，允许 expressive，但遵守节流（每 8~15s 才随机一次小动作，不无限高频）；`prefers-reduced-motion: reduce` 时停用一切循环动画（模型定格 + 场景层静态）。
- **字体**：气泡沿用现有字体栈，不新增外链字体（零外网渲染铁律）。
- **背景处理**：桌宠悬浮于内容之上，舞台底部加一圈极淡蜜橘 `radial-gradient` 光晕区分层级，不挡内容点击（`pointer-events` 只在容器上）。
- **移动端**：`<900px` 或触屏默认收起为小圆点（保留点击展开），避免遮挡与性能损耗。

## 七、交互设计

| 交互 | 行为 | 实现要点 |
|---|---|---|
| 点击身体（hit 'Body'） | 弹台词气泡（按当前 state 选文案，3~5s 消失）+ 轻微点头 | pixi-live2d-display `model.on('hit', ...)`；气泡是 DOM 层 |
| 摸头（hit 'Head'） | 播放模型 TapHead 类 motion（存在则播）+ 开心表情（存在则切）+ 专属台词 | 模型 motion 组/表情先运行时探测，缺则静默降级 |
| 拖拽 | 按住容器拖到任意位置，松手存 `localStorage['xm-pet-pos']`，刷新恢复；边界 clamp | Pointer Events；拖拽期间禁用点击误触 |
| 最小化 | 收起为 ~48px 小圆点按钮（🌾），点击还原 | CSS 状态 class 切换 |
| 隐藏 | 本页会话内隐藏（刷新恢复；不做持久隐藏，避免"找不回来"） | `localStorage['xm-pet-hidden']='1'` 仅存内存级变量亦可，文档写清楚 |
| 思考联动 | agent.js `send()` 期间发 `document.dispatchEvent(new CustomEvent('xm:thinking',{detail:{on:true|false}}))`，pet.js 订阅 | agent.js 改动 ≤10 行 |
| 权限门控 | 仅 `role==='admin'` 显示（与角色/日程一致）；非 admin 不加载不轮询 | dashboard.js 登录回调里判定后调 `Pet.mount()` |
| 无障碍 | 全部按钮可聚焦（键盘可达）；reduced-motion 降级 | 复用 agent.css 的 focus-visible 模式 |

## 八、后端微改（2 处，向后兼容）

1. `dashboard/scheduler.py`
   - `_mark_running(task_id, name, started_at)` → 存储里带 `task_id`；`current_task()` 返回 `{task_id, name, started_at}`。
2. `dashboard/api_agent.py`
   - `agent_status()` 新增顶层 `state`（见 5.1 推导），其余字段不动。

## 九、前端改动清单（文件级）

| 文件 | 改动 |
|---|---|
| `dashboard/static/live2d/vendor/pixi.min.js` | **新增**（vendored） |
| `dashboard/static/live2d/vendor/pixi-live2d-display(.umd).js` | **新增**（vendored） |
| `dashboard/static/live2d/vendor/live2dcubismcore.min.js` | **新增**（vendored，官方 CDN 下载一次） |
| `dashboard/static/live2d/model/<candidate>/…` | **新增**（model3.json + textures/motions/expressions） |
| `dashboard/static/css/pet.css` | **新增**：容器/舞台/键盘屏幕动画/气泡/Zzz/小圆点/reduced-motion |
| `dashboard/static/js/pet.js` | **新增**：渲染初始化、状态机、轮询、交互、台词库、拖拽 |
| `dashboard/templates/dashboard.html` | 引入 pet.css/pet.js；body 末尾加 `<div id="xm-pet">` 舞台骨架（小桌+笔记本 SVG 模板） |
| `dashboard/static/js/agent.js` | ① 删自身 30s 轮询，改订阅 `xm:status` 更新 pill（保留首次直拉兜底）；② `send()` 发 `xm:thinking` 事件 |
| `dashboard/static/js/dashboard.js` | 登录成功后按 role 调 `Pet.mount()`；登出/401 时 `Pet.unmount()` |

> 脚本加载顺序：`auth.js → dashboard.js → daily.js → agent.js → pet.js`；pet.js 全部延迟到登录成功后动态挂载（不阻塞首屏、失败静默隐藏）。

## 十、实施步骤（TDD 门禁）

| Step | 内容 | 产出/验证 |
|---|---|---|
| 0 | 资产就绪：下载 pixi/live2d-display/cubismcore + 2~3 候选模型到 static/live2d/，本地起 dashboard 各渲染 1 屏 | 截图对比，**用户拍板模型**（画风主观项） |
| 1 | 后端微改：scheduler 补 task_id；api_agent 加 state | `pytest tests/test_agent_api.py` 增补：state 推导（offline/leave/working/slack）+ current_task 带 task_id |
| 2 | 渲染层：pet.js 内 Pixi 应用 + 模型加载 + resize/透明背景 + 视线跟随 | 浏览器可见模型静置于右下角，滚动不位移 |
| 3 | 状态机：轮询 `/api/agent/status` → state → 动画分发（5.2/5.3）；`xm:status` 广播 + agent.js 订阅重构 | 手工切"上班/请假/任务"验证四态切换；角色页 pill 与桌宠同步 |
| 4 | 场景层：小桌 + 笔记本 SVG + working 敲键盘/盯屏动画 + leave 的 Zzz + 状态灯 | 视觉验收（设计决策见 §六） |
| 5 | 交互：气泡台词、摸头/点击 hit、拖拽记忆、最小化、隐藏、thinking 联动 | 手工清单（见 §十一） |
| 6 | 打磨：design-critique（44 条反模式）+ reduced-motion + 移动端收起 + 登录遮罩层级 | 自检清单通过 |
| 7 | 收尾：README 角色表补桌宠说明 + Live2D 署名；全量 pytest | 全绿；验收清单勾完 |

## 十一、测试与验收

**自动化（pytest）**：
- `test_agent_api.py` 增：`/api/agent/status` 含 `state`；`_state()` 四态推导（mock `heartbeat_age_seconds` 与 `current_task`）。
- scheduler 增：`current_task()` 返回含 `task_id`（monkeypatch `_mark_running` 后断言）。

**浏览器手工验收清单**：
- [ ] 右下角悬浮、滚动/切 view 不位移；登录前不出现
- [ ] 上班+任务 → 开电脑敲键盘/盯数据；任务结束 → 摸鱼；请假 → 趴睡 Zzz；kill agent 进程 → 灰态 ⚪
- [ ] 角色页聊天中 → 桌宠"思考中"；结束恢复
- [ ] 点击冒气泡（文案随状态）；摸头有反应；拖拽换位刷新后保留；最小化/隐藏正常
- [ ] 状态 pill（角色页）与桌宠展示一致（单一轮询源）
- [ ] reduced-motion 下无循环动画；宽 <900px 自动收起；无控制台报错
- [ ] 断网/静态资源缺失 → 桌宠静默隐藏，Dashboard 主体不受影响

## 十二、风险与回退

| 风险 | 应对 |
|---|---|
| 官方模型画风不合"小满 Q 版"预期 | Step 0 多候选预览后拍板；最坏回退 = §四"备选方案"或文档化 SVG 伪 Live2D（不阻塞其它优化） |
| 体积：运行时+模型 ~1-3MB | 首屏不加载（登录后按需）；本地网络无感知；可后续换更小模型/压缩纹理 |
| Cubism core 国内下载不稳定 | 仅一次下载后 vendored 入 git；实施时可用代理 |
| Live2D 授权误解 | 仅用官方 Sample Material 免费模型 + 随应用分发 + 署名；README 声明 |
| 轮询重构回归（pill 不同步） | 单一轮询源 + `xm:status` 广播 + agent.js 首次直拉兜底；验收清单覆盖 |
| 旧浏览器 WebGL 不可用 | `WebGL` 探测失败 → 静默隐藏（同资源缺失路径） |

## 十三、工作量估算（人日）

| 项 | 估 |
|---|---|
| Step 0 资产准备 + 模型试渲染/拍板 | 0.5–1 |
| Step 1 后端微改 + 测试 | 0.3 |
| Step 2–3 渲染层 + 状态机 + 轮询重构 | 1–1.5 |
| Step 4 场景层（键盘/盯屏/Zzz） | 0.5–1 |
| Step 5–6 交互 + 打磨 + 无障碍 | 0.5–1 |
| Step 7 文档/署名/全量回归 | 0.3 |
| **合计** | **约 3–5 人日** |

## 十四、参考

- pixi-live2d-display：https://github.com/guansss/pixi-live2d-display
- PixiJS：https://github.com/pixijs/pixijs
- Live2D CubismWebSamples（官方免费模型）：https://github.com/Live2D/CubismWebSamples
- Live2D 官方示例模型许可（Sample Material Terms）：https://www.live2d.com/eula/live2d-sample-model-terms_en.html
- 备选（未采用）stevenjoezhang/live2d-widget：https://github.com/stevenjoezhang/live2d-widget
