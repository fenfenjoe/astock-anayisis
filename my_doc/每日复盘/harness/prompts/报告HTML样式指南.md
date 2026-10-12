# 早盘/复盘报告 HTML 样式指南（v1.0）

> **用途**：早盘分析 / 复盘分析产出 `早盘报告.html` / `复盘报告.html` 时遵循的**统一视觉规范**。
> 与 Dashboard 的 Tech Noir 暗色设计系统一致（品牌色相 210°，OKLCH 色域）。
> 报告内嵌 `<style>`，自包含、零外部依赖，可直接在 Dashboard「报告」页与浏览器中打开。
>
> **核心设计目标（对应本次需求）**：
> 1. **重点突出**——关键结论/信号/评分用卡片、徽章、色条，一眼可抓，不做流水账。
> 2. **信息降噪**——把大段文字改造成 KPI 卡、评分条、彩色表格、标签，直观不啰嗦。
> 3. **层次清晰**——每个模块有编号标题，模块内先结论后细节，结论置顶。

---

## 一、HTML 骨架（必须遵守）

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>早盘报告 · 2026-09-22</title>
<style> …本指南第二/三节的样式（可直接复制模板）… </style>
</head>
<body>
<div class="rp-report">
  <header class="rp-hero">
    <div class="rp-hero-title">🌅 早盘分析报告</div>
    <div class="rp-hero-meta">数据时点：2026-09-22 08:50 ｜ 交易日：周二</div>
  </header>
  <section class="rp-kpi"> …KPI 卡片组… </section>
  <main> …各模块… </main>
</div>
</body>
</html>
```

> ⚠️ 只输出**完整的 HTML 文档**（含 `<style>` 与 `<body>`），不要输出 markdown 或纯文本混排。
> ⚠️ 所有类名必须以 `rp-` 为前缀，避免与 Dashboard 全局样式冲突。

---

## 二、设计 Token（暗色 · Tech Noir）

```css
.rp-report {
  /* 背景与文本 */
  --rp-bg:      #0e1117;                 /* 最深背景 */
  --rp-surface: #161b22;                 /* 卡片背景 */
  --rp-border:  #2a3140;                 /* 边框（带蓝灰） */
  --rp-text:    #edf2f7;                 /* 主文本 */
  --rp-text-2:  #a8b3c4;                 /* 次文本 */
  --rp-text-3:  #6b7686;                 /* 弱文本 */
  /* 语义色 */
  --rp-blue:    #5ea2f7;                 /* 品牌蓝 */
  --rp-cyan:    #6fd3e8;                 /* 数据青 */
  --rp-green:   #4cd98b;                 /* 正/可达/建仓 */
  --rp-red:     #f2655c;                 /* 负/风险/回避 */
  --rp-amber:   #f2b544;                 /* 警告/关注/中性偏多 */
  --rp-purple:  #b48ae0;                 /* 强调紫（做T/事件） */
  /* 排版 */
  font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei UI', 'Microsoft YaHei', 'Noto Sans SC', sans-serif;
  font-size: 14px; line-height: 1.6; color: var(--rp-text);
  max-width: 1000px; margin: 0 auto; padding: 20px;
  background: var(--rp-bg);
}
```

---

## 三、组件库（复制即用）

### 1. KPI 卡片组（报告最顶部，一眼看大盘）

```html
<div class="rp-kpi">
  <div class="rp-kpi-card" data-tone="up">
    <div class="rp-kpi-label">大盘方向</div>
    <div class="rp-kpi-value">高开震荡偏多</div>
    <div class="rp-kpi-sub">A50 +0.6% · CNH 7.05</div>
  </div>
  <div class="rp-kpi-card" data-tone="down">
    <div class="rp-kpi-label">核心矛盾</div>
    <div class="rp-kpi-value">半导体高位分歧</div>
    <div class="rp-kpi-sub">外盘强 vs 内需弱</div>
  </div>
  <div class="rp-kpi-card" data-tone="warn">
    <div class="rp-kpi-label">信号数</div>
    <div class="rp-kpi-value">P0×2 · P1×4</div>
    <div class="rp-kpi-sub">今日 6 条待执行</div>
  </div>
</div>
```

```css
.rp-kpi { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin: 14px 0 22px; }
.rp-kpi-card { background: var(--rp-surface); border: 1px solid var(--rp-border); border-left: 4px solid var(--rp-blue); border-radius: 10px; padding: 12px 14px; }
.rp-kpi-card[data-tone="up"]   { border-left-color: var(--rp-green); }
.rp-kpi-card[data-tone="down"] { border-left-color: var(--rp-red); }
.rp-kpi-card[data-tone="warn"] { border-left-color: var(--rp-amber); }
.rp-kpi-label { font-size: 12px; color: var(--rp-text-3); letter-spacing: 1px; }
.rp-kpi-value { font-size: 18px; font-weight: 700; margin: 4px 0 2px; }
.rp-kpi-sub   { font-size: 12px; color: var(--rp-text-2); }
```

### 2. 模块标题（编号 + 色条）

```html
<div class="rp-section-title"><span class="rp-section-num">01</span> 宏观研判</div>
```

```css
.rp-section-title { display: flex; align-items: center; gap: 10px; font-size: 17px; font-weight: 700; margin: 26px 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--rp-border); }
.rp-section-num { display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 8px; background: var(--rp-blue); color: #0e1117; font-size: 13px; font-weight: 800; }
```

### 3. 徽章 / 标签（结论、信号、评分快速着色）

```html
<span class="rp-badge up">🟢 建仓</span>
<span class="rp-badge warn">🟡 关注</span>
<span class="rp-badge down">🔴 回避</span>
<span class="rp-badge info">ℹ️ 提示</span>
```

```css
.rp-badge { display: inline-flex; align-items: center; gap: 4px; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
.rp-badge.up   { background: rgba(76, 217, 139, .15); color: var(--rp-green); border: 1px solid rgba(76,217,139,.4); }
.rp-badge.warn { background: rgba(242, 181, 68, .15); color: var(--rp-amber); border: 1px solid rgba(242,181,68,.4); }
.rp-badge.down { background: rgba(242, 101, 92, .15); color: var(--rp-red);   border: 1px solid rgba(242,101,92,.4); }
.rp-badge.info { background: rgba(94, 162, 247, .15); color: var(--rp-blue); border: 1px solid rgba(94,162,247,.4); }
```

### 4. 重点结论框（结论置顶、可多色）

```html
<div class="rp-callout" data-tone="green">
  <b>今日核心判断：</b>高开震荡偏多，权重托底，题材分化。重点看半导体能否续强 + 北向是否延续流入。
</div>
```

```css
.rp-callout { border: 1px solid var(--rp-border); border-left: 5px solid var(--rp-blue); background: var(--rp-surface); border-radius: 8px; padding: 12px 16px; margin: 12px 0; }
.rp-callout[data-tone="green"] { border-left-color: var(--rp-green); }
.rp-callout[data-tone="red"]   { border-left-color: var(--rp-red); }
.rp-callout[data-tone="amber"] { border-left-color: var(--rp-amber); }
.rp-callout[data-tone="purple"]{ border-left-color: var(--rp-purple); }
```

### 5. 评分条（把 1-5 分变成可视化横条，替代纯文字）

```html
<div class="rp-score-row">
  <span class="rp-score-name">入场时机 <i>×1.5</i></span>
  <div class="rp-score-track"><div class="rp-score-fill" style="width: 80%"></div></div>
  <span class="rp-score-num">4.0</span>
</div>
```

```css
.rp-score-row { display: flex; align-items: center; gap: 10px; margin: 6px 0; }
.rp-score-name { flex: 0 0 120px; font-size: 13px; color: var(--rp-text-2); }
.rp-score-name i { color: var(--rp-text-3); font-style: normal; font-size: 11px; }
.rp-score-track { flex: 1; height: 8px; border-radius: 999px; background: var(--rp-border); overflow: hidden; }
.rp-score-fill  { height: 100%; border-radius: 999px; background: linear-gradient(90deg, var(--rp-blue), var(--rp-cyan)); }
.rp-score-num   { flex: 0 0 36px; text-align: right; font-weight: 700; font-family: 'Cascadia Code', 'JetBrains Mono', monospace; }
```

### 6. 彩色表格（评分表/信号表/时间表通用）

```html
<table class="rp-table">
  <thead><tr><th>板块</th><th>关联ETF</th><th>综合</th><th>建议</th><th>核心逻辑</th></tr></thead>
  <tbody>
    <tr class="rp-row-up"><td>半导体</td><td>512480</td><td>4.2</td><td><span class="rp-badge up">建仓</span></td><td>外盘映射强+资金流入</td></tr>
    <tr class="rp-row-warn"><td>创新药</td><td>159992</td><td>3.4</td><td><span class="rp-badge warn">关注</span></td><td>消息催化待确认</td></tr>
    <tr class="rp-row-down"><td>光伏</td><td>515790</td><td>2.6</td><td><span class="rp-badge down">回避</span></td><td>技术位弱+情绪冷</td></tr>
  </tbody>
</table>
```

```css
.rp-table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 13px; }
.rp-table th { background: var(--rp-surface); color: var(--rp-text-2); text-align: left; padding: 8px 10px; border: 1px solid var(--rp-border); font-weight: 600; }
.rp-table td { padding: 8px 10px; border: 1px solid var(--rp-border); }
.rp-table tr:hover td { background: rgba(94,162,247,.06); }
.rp-row-up td:first-child { border-left: 3px solid var(--rp-green); }
.rp-row-warn td:first-child { border-left: 3px solid var(--rp-amber); }
.rp-row-down td:first-child { border-left: 3px solid var(--rp-red); }
```

### 7. 时间轴（核心关注时间表/做T窗口）

```html
<div class="rp-timeline">
  <div class="rp-tl-item"><span class="rp-tl-time">09:30</span><span class="rp-tl-dot"></span><div class="rp-tl-body"><b>开盘验证</b><div>看高开幅度，确认方向</div></div></div>
  <div class="rp-tl-item"><span class="rp-tl-time">10:30</span><span class="rp-tl-dot"></span><div class="rp-tl-body"><b>方向确认</b><div>加仓窗口观察</div></div></div>
</div>
```

```css
.rp-timeline { margin: 10px 0 10px 4px; }
.rp-tl-item { display: flex; gap: 12px; padding: 6px 0; position: relative; }
.rp-tl-time { flex: 0 0 52px; text-align: right; font-family: 'Cascadia Code', monospace; font-size: 12px; color: var(--rp-cyan); }
.rp-tl-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--rp-blue); margin-top: 4px; flex: none; }
.rp-tl-body { flex: 1; font-size: 13px; }
```

### 8. 风险清单 / 待办（每条一个色点）

```html
<ul class="rp-risks">
  <li data-tone="red">半导体若冲高回落，持仓可能回撤 2%+，设置止损位。</li>
  <li data-tone="amber">北向若大幅流出，警惕权重补跌。</li>
</ul>
```

```css
.rp-risks { list-style: none; padding: 0; margin: 10px 0; }
.rp-risks li { display: flex; gap: 8px; padding: 6px 0; border-bottom: 1px dashed var(--rp-border); font-size: 13px; }
.rp-risks li::before { content: "●"; color: var(--rp-red); font-size: 10px; margin-top: 5px; }
.rp-risks li[data-tone="amber"]::before { color: var(--rp-amber); }
```

---

## 四、排版与信息密度规则

| 规则 | 说明 |
|------|------|
| **结论置顶** | 每个模块第 1 句/第 1 卡给出结论，再给依据；禁止"先铺垫后给答案" |
| **KPI 前置** | 报告顶部必须有 KPI 卡片组（大盘方向/核心矛盾/信号数等 3-4 张） |
| **少段落** | 连续纯文字段落 ≤3 行；超过就改用卡片/表格/列表/评分条 |
| **数字着色** | 涨跌/盈亏/评分数字用 `+绿 -红`；中性用默认色 |
| **徽章优先** | 建仓/关注/回避、P0/P1、触发/未触发等结论一律用 `.rp-badge` 或彩色表格行 |
| **评分可视** | 1-5 分评分：正文用评分条 `.rp-score-row` 或表格着色行，不堆纯数字 |
| **中文字体** | 一律用指南内置字体栈（系统无衬线），不引入外链字体 |
| **自包含** | 禁止外链图片/脚本/字体；全部样式内嵌 `<style>` |

---

## 五、文件命名与存放

- 早盘：`my_doc/每日复盘/reports/{yyyyMMdd}/早盘报告.html`
- 复盘：`my_doc/每日复盘/reports/{yyyyMMdd}/复盘报告.html`
- 与同名 `.md` 共存：`.md` 供自动化链路解析（staging 重建/信号复盘），`.html` 供 Dashboard 展示，内容必须一致（同一份分析的两份呈现）。

---

## 六、禁止事项

- ❌ 禁止输出纯黑 `#000` 背景 + 纯白正文的无层次排版（必须用本节背景分层）。
- ❌ 禁止紫色→蓝色渐变占满全屏（只允许局部小面积强调）。
- ❌ 禁止灰底灰字（弱文本必须带色相：蓝灰 `#6b7686` 等）。
- ❌ 禁止把 markdown 语法（`##`/`**`/`|` 表格）混进 HTML 文档。
- ❌ 禁止 `<script>`、事件属性、外链资源（报告是静态展示，零 JS）。
- ❌ 禁止卡片套卡片超过一层（KPI 卡片内不再嵌套卡片）。
