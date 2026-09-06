# static/live2d/ — 小满 LIVE2D 桌宠资产目录

> 自托管铁律：运行时与模型全部本地化，无任何外链 CDN（国内不可达/阻塞风险）。
> 本目录由 `scripts/fetch_live2d_assets.ps1`（需有外网的机器执行）或手工放置生成，入 git。

## 目录布局

```
static/live2d/
├── vendor/
│   ├── pixi.min.js                            # PixiJS v6.5.10（MIT；v6 浏览器 UMD 在 dist/browser/ 下）
│   ├── pixi-live2d-display.min.js             # Cubism4 运行时 UMD（MIT，需先加载 pixi + core）
│   ├── live2dcubismcore.min.js                # Live2D Cubism4 Core（官方 SDK 分发，随应用免费）
│   ├── pixi-live2d-display-cubism2.min.js     # Cubism2 运行时 UMD（MIT）
│   └── live2d.min.js                          # Live2D Cubism2 Core（旧 SDK 分发）
└── model/
    ├── Senko/…                                # ✅ 当前选用（Q 版坐姿橘发狐娘，moc3 v2，Idle/Tap/Taphead/Tick_5）
    ├── Haru/…                                 # Cubism4 官方免费示例（制服少女，8 表情+Idle/TapBody）——官方保底
    ├── Natori/…                               # 官方免费示例（Cubism4）——候选
    └── live2d-widget-model-koharu/…           # Cubism2 候选：Koharu 小春（Q 版吉祥物，切回时用）
```

> 当前 `pet.js` 的 `CFG.modelJson` 指向
> `/static/live2d/model/Senko/senko.model3.json`（Cubism4，自动走 cubism4 运行时）。
> 切官方 Haru：`model/Haru/Haru.model3.json`；切 Cubism2 Koharu：
> `model/live2d-widget-model-koharu/assets/koharu.model.json`。
> pet.js 双运行时按扩展名自适应，动作组名做了多生态回退（Tap/Taphead/Tick_5/TapHead/TapBody/idle），
> 换模型一般无需改代码；无表情的模型表情联动自动跳过。

## Q 版选型结论（2026-09-05 实测）

| 模型 | 来源 | moc3 版本 | 结论 |
|---|---|---|---|
| **Senko 仙狐** | hacxy/l2d-models `models/Senko_Normals`（脚本默认下载） | **v2** | ✅ 选用：Q 版三头身坐姿、暖橘毛色与小满蜜橘 accent 呼应；动作丰富（Idle + Tap 互动 + Taphead 唱歌/睡觉 + Tick_5 睡觉），无表情文件（联动自动降级），hit 区仅 head |
| Mao（官方 Q 版兽耳少女） | Live2D/CubismWebSamples `Samples/Resources/Mao` | **v5** | ❌ 不可用：moc3 v5 需 Cubism 5/6 Core；实测 Cubism 6.0 Core 虽能解析 moc，但与 pixi-live2d-display@0.4 框架 ABI 不兼容（`doDrawModel` 崩溃）。**core 必须保持 4.2（npm `live2dcubismcore@1.0.2`），切勿升级** |
| Rice（官方） | CubismWebSamples `Samples/Resources/Rice` | v3 | 正常比例立绘 + 冷色调，不符 Q 版/暖橘人设，未选用（脚本 `-AddRepo` 可重新拉取） |
| Haru/Natori | 官方 | v1 | 正常比例，在 360px 舞台显小；保留为授权最干净的官方保底 |

> Senko 尺寸适配：原生 bounds 3505×3003（宽>高的坐像），`CFG.fitFactor=1.08`（bounds 内角色
> 头顶约 16% 留白，再大会裁耳尖）；状态联动映射：working→Tap 手势 + 小桌场景层，
> slack→Idle 偶尔 Taphead 唱歌，leave→Tick_5 睡觉 + CSS zzz，thinking→Tap + "…"气泡。

## 接入（选定模型后）

1. 把选中的模型目录保留为 `model/<name>/…`（含 `.model3.json` / `.moc3` / `textures/` / `motions/` / `expressions/`）。
2. `dashboard/static/js/pet.js` 顶部：

```js
modelJson: '/static/live2d/model/<name>/<xxx>.model3.json',
```

3. 预览/截图：`scripts/fetch_live2d_preview.ps1`（生成 `preview.html` 单页逐个渲染，无头浏览器截图对比画风）。

## 渲染层与场景层的分工（重要）

官方免费模型自带动画组有限（Idle / TapHead 等），**没有"敲键盘/盯盘"动作**。
因此"工作语义"由 `pet.css` 的场景层动画承担（小桌/笔记本/键盘律动/屏幕滚动），
Live2D 只负责角色本体姿态（Idle motion / 表情 / 视线）。两层叠加 = 桌宠办公画面。
若未来想要"独一无二的小满脸/专属动作"，需美术用 Live2D Cubism Editor 制作（付费/外协），
渲染层接口（`CFG.modelJson`）无需改动。

## 授权（务必读）

| 资产 | 许可 | 义务 |
|---|---|---|
| pixi.js / pixi-live2d-display | MIT | 保留版权声明即可 |
| live2dcubismcore.min.js | Live2D Cubism SDK（Proprietary，免费随应用分发） | 随应用分发，见 SDK 条款 |
| 官方示例模型（Haru/Natori 等） | [Live2D Sample Material Terms](https://www.live2d.com/eula/live2d-sample-model-terms_en.html) | **随应用分发需署名 "Character © Live2D Inc."**；不得把模型文件单独再分发/转售；不得用于违法用途 |
| Senko 仙狐（当前主用） | 社区配布（hacxy/l2d-models 收录），角色为《贤惠幼妻仙狐小姐》同人模型 | 非官方授权角色，**仅限本地/个人工具使用，不得商用或随产品公开发布**；若未来产品公开分发需更换为官方 Sample 模型（Haru/Natori） |
| 社区/画师模型 | 各自条款不一 | 逐个核对：是否可商用、是否需要署名/联系作者；不确定不用 |

## 三档模型来源（画风/授权权衡）

1. **官方免费（首选，授权最干净）**：[Live2D sample-data](https://www.live2d.com/en/download/sample-data/)、
   [Live2D/CubismWebSamples](https://github.com/Live2D/CubismWebSamples)（Cubism4，直接可加载）。
   注意：以半身立绘风为主，无严格 Q 版三头身。
2. **社区 Cubism4 模型（Q 版主攻，画风杂）**：`hacxy/l2d-models`、`HoshiKurea/live2d_modules`、
   `111111efe/live2d-widget-models`、npm `oml2d-models` 等。逐一下载核对 license。
3. **画师配布**：BOOTH「無料配布」等（`.model3.json` 结构与网页版同构）。授权更散，慎用。

> 官方 Q 版吉祥物（Pio/Koharu 等）为 Cubism 2/3 格式，与 pixi-live2d-display 的 Cubism4
> 分支不兼容。本项目已接入 Cubism2 运行时（pet.js 双运行时自适应，见下节）。

## live2d-widget 生态（Cubism2，2026-09-02 起兼容）

[stevenjoezhang/live2d-widget](https://github.com/stevenjoezhang/live2d-widget)（看板娘组件）的资产生态是
**Cubism2 格式**（`*.model.json` + `.moc`），与 pixi-live2d-display 的 Cubism4 分支不兼容。
pet.js 已升级为**双运行时自适应**：`CFG.modelJson` 以 `.model3.json` 结尾 → 自动用 Cubism4；
以 `.model.json` 结尾 → 自动加载 Cubism2 核心（`live2d.min.js`）+ cubism2 插件。因此该生态模型可直接使用。

**Cubism2 候选：Koharu（小春）** — Live2D 官方 Q 版吉祥物（Koharu & Haruto 成对），Q 萌小只，
最贴"小满 Q 版元气少女"人设；npm 包 `live2d-widget-model-koharu`（xiazeyu 维护，模型本体为
Live2D 官方 Sample Material Terms 再分发，随应用商用需署名 "Character © Live2D Inc."）。
资产已下载，改一行 `CFG.modelJson` 即可切回（Koharu 仅 idle 动作、无表情/无 hit 区域）。

> 当前主用 **Cubism4 Senko 仙狐**（Q 版坐姿、暖橘色调、动作组丰富，见上方"Q 版选型结论"）；
> 官方 Haru（表情/点击区域完整、授权最干净）与 Cubism2 Koharu 作为备选保留。
> 选型备注（2026-09-05 实测）：npm 上**不存在** `live2d-widget-model-pio` 包，xiazeyu/live2d-widget-models
> 仓库也无 Pio 目录；同生态可用角色：koharu（Q 版官方吉祥物）、shizuku（经典看板娘少女）、
> haruto（Q 版男性）、hibiki/izumi/chitose 等。一条命令拉取（联网机）：

```
powershell -ExecutionPolicy Bypass -File scripts\fetch_live2d_assets.ps1 -AddNpm live2d-widget-model-koharu
```

脚本会顺带下载 Cubism2 运行时，并打印模型入口路径；把它填进 `pet.js` 的 `CFG.modelJson` 即可。
> Cubism2 核心 `live2d.min.js` 取自 stevenjoezhang/live2d-widget 旧 tag `v0.9.2`（新版 master 已重构、
> 根目录无此文件）；Cubism4 core 官方站 cubism.live2d.com 国内常超时，脚本改用 npm 再分发包
> `live2dcubismcore@1.0.2` 优先、官方站兜底。PixiJS v6 的浏览器 UMD 在 `dist/browser/pixi.min.js`
> （`dist/pixi.min.js` 自 v6 起已移除，脚本已修正）。

## GitHub 候选仓库清单（2026-09-02 检索；选型前逐仓确认两件事）

> **筛选两步**：① 该目录必须含 `*.model3.json`（Cubism4 才能被 pixi-live2d-display 加载；
> `.model.json`/`.moc` 是 Cubism2，不能用）；② 读 LICENSE/README 确认可免费使用。
> 先列清单再点名下装（联网机执行）：
> ```
> powershell -ExecutionPolicy Bypass -File scripts\fetch_live2d_assets.ps1 -ListModels -AddRepo <owner/repo> -Branch <分支>
> powershell -ExecutionPolicy Bypass -File scripts\fetch_live2d_assets.ps1 -AddRepo <owner/repo> -Branch <分支> -SubPath <上面列出的目录> -As <本地名>
> ```

| 候选 | 仓库 | 说明 |
|---|---|---|
| ① 官方保底（少女向） | [Live2D/CubismWebSamples](https://github.com/Live2D/CubismWebSamples)（`Samples/Resources/Haru|Natori|Hiyori|Mark`） | 脚本已内置 Haru+Natori；授权最干净（Sample Material Terms） |
| ② 官方吉祥物（近 Q 版） | [Koharu・Haruto 官方示例页](https://www.live2d.com/ko/learn/sample/koharu-haruto/) | 官方 mascot 系、偏 Q；需打开确认提供 Cubism4 zip（含 .moc3） |
| ③ l2d 生态静态模型库 | [hacxy/l2d-models](https://github.com/hacxy/l2d-models)（[README 模型清单](https://raw.githubusercontent.com/hacxy/l2d-models/main/README.md)） | 为 oml2d/l2d（PixiJS 系）维护 → 多为 Cubism4 可爱少女，直击需求 |
| ④ oml2d 官方模型包 | npm `oml2d-models`（[jsdelivr 直览目录](https://cdn.jsdelivr.net/npm/oml2d-models@0.7.0/README.md)） | 与 pixi-live2d-display 同栈，模型几乎必为 Cubism4 |
| ⑤ 综合收藏（多格式混合） | [maintell/Live2d-model](https://github.com/maintell/Live2d-model) | 大杂烩，按"筛选两步"挑 Cubism4 目录 |
| ⑥ WebGAL 维护分支 demo | [OpenWebGAL/pixi-live2d-display-webgal](https://github.com/OpenWebGAL/pixi-live2d-display-webgal) | 活跃维护的渲染分支，参考其自带 demo 模型 |
| ⑦ Cubism2 旧系（一般不选） | Eikanya/Live2d-model、galnetwen/live2d、111111efe/live2d-widget-models、HoshiKurea/live2d_modules | 多为 `.model.json`(Cubism2)，需转格式才能用 |

## 故障与降级

- 资产缺失 / WebGL 不可用 / 加载失败：`pet.js` 自动降级为「🌾」占位形态，
  Dashboard 主体与其它功能不受影响（所有渲染操作 try-catch 静默）。
- 减小体积：模型可压缩纹理；运行时只有 pixi 偏大（~500KB gzip），首屏不加载（登录后按需）。
