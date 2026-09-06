# 小满 Live2D 桌宠挑选 & 安装指南

给 Dashboard 用户：想换一只新的桌宠看板娘？按下面三步走即可。

---

## 第一步：去这些地方挑模型

桌宠支持两种模型格式，**优先选 Cubism 4（`*.model3.json`）**，画质和物理效果更好；Cubism 2（`*.model.json`）也能用，是旧格式。

> ⚠️ **兼容性红线（必读）**：本项目使用 Cubism Core **4.2.2**，只支持 **moc3 v1–v3**（Cubism 3/4 导出）的模型。**Cubism 5/6 导出的新模型（moc3 v4/v5）用不了**，加载会崩溃。挑模型时看文件里有没有 `.model3.json` + `.moc3`，下载后直接试装，能跑就对了。

### 推荐来源

| # | 来源 | 网址 | 说明 |
|---|---|---|---|
| 1 | Live2D 官方免费样例 | https://www.live2d.com/en/download/sample-data/ | Haru / Natori / Hiyori / Mark 等，授权干净，可商用（需署名 `Character © Live2D Inc.`）。但多为正常头身，放进小桌宠舞台偏小。 |
| 2 | hacxy/l2d-models（社区精选） | https://github.com/hacxy/l2d-models/tree/main/models | **首选**。`models/` 目录下有大量 Q 版模型（仙狐 Senko、Pio、Wanko 小狗、chino、bilibili 22/33 娘、HK416 等），点进目录能看到 `.model3.json`。注意同人角色仅限个人本地使用。 |
| 3 | Live2D 官方 GitHub 样例 | https://github.com/Live2D/CubismWebSamples | 与 #1 同源，可直接浏览文件目录。 |
| 4 | live2d-widget 生态（Cubism 2） | https://www.npmjs.com/search?q=live2d-widget-model | 旧格式存量多，如 koharu 小春、shizuku、shizuku 换装、haruto 等，适合怀旧。 |

### 选人小建议
- **选 Q 版 / 三头身 / 坐姿**：桌宠舞台很小（360×254），正常头身人物会显得特别小。
- **暖色调更搭**：Dashboard 是暗色 + 蜜橘色主题，金发/橙红系最和谐（比如仙狐）。
- **有动作组更好**：模型带 `Tap`、`TapHead`、`Tick_5`（睡觉）这类动作组，互动更丰富；没有也不影响使用。

---

## 第二步：下载模型

下载到本地有两种方式，**推荐用项目自带的脚本一键拉取**（会自动放到正确位置）。

### 方式 A：一键脚本（推荐）

在**仓库根目录**打开 PowerShell，执行：

```powershell
# 先列出 hacxy/l2d-models 里所有可用模型目录（只看不下）
powershell -ExecutionPolicy Bypass -File scripts\fetch_live2d_assets.ps1 `
  -ListModels -AddRepo hacxy/l2d-models -Branch main

# 下载看中的模型（示例：Pio）
powershell -ExecutionPolicy Bypass -File scripts\fetch_live2d_assets.ps1 `
  -AddRepo hacxy/l2d-models -Branch main -SubPath models/Pio -As Pio
```

下载成功后，模型会出现在：
```
etf-strategies/dashboard/static/live2d/model/Pio/
```

### 方式 B：手动下载

如果脚本拉不到（网络问题），就手动下：
1. 打开上面的来源网址，进入模型目录；
2. 把整个目录（含 `.model3.json`、`.moc3`、纹理图、动作组等）下载下来；
3. 解压到 `etf-strategies/dashboard/static/live2d/model/<你起的名字>/`，保证 `<名字>/` 下直接能看到 `*.model3.json`。

---

## 第三步：安装 / 切换模型

只需改**一行配置**。

打开文件 [pet.js](../etf-strategies/dashboard/static/js/pet.js)，找到顶部的 `CFG` 对象，把 `modelJson` 改成新模型的清单路径：

```js
var CFG = {
  // 把这一行换成你的新模型路径
  modelJson: '/static/live2d/model/Pio/pio.model3.json',

  stageW: 360,
  stageH: 254,
  fitFactor: 1.08,   // 人物大小：调大=变大，注意别裁掉头顶/耳朵
  // ...
};
```

保存后，浏览器**按 Ctrl+F5 强制刷新** Dashboard 页面，新桌宠就出现了（无需重启服务）。

### 调整大小

如果人物在舞台里太小或太大，改 `fitFactor`：
- 太小 → 调大（如 `1.15`）
- 太大/头顶被裁 → 调小（如 `1.0`）
- 每次改完 Ctrl+F5 看效果。

---

## 验证清单

切换后检查：
1. 控制台出现 `[xm-pet] LIVE2D 模型加载成功：...`，**没有红色报错**；
2. 人物在舞台里居中、不裁切，Idle 动作自然循环；
3. 点击人物有反馈（动作 + 台词）；桌宠上方的状态按钮（自动/▶工作/☕摸鱼/💤睡觉）各态显示正常。

如果加载失败或画面崩溃，多半是模型版本过高（moc3 v4/v5），换一个 Cubism 3/4 的模型即可。

---

## 授权提醒

- 官方样例（Haru 等）：可商用，需署名 `Character © Live2D Inc.`。
- 社区原创免费模型（Senko、Pio 等）：按原发布条款，多数可个人使用。
- **同人角色**（动漫/游戏 IP）：仅限自己本地玩玩，**不要随产品公开分发或商用**。
