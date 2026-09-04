---
name: frontend-design
description: 前端设计系统 — 在写代码前确定美学方向（brutalist/editorial/retro-futuristic/SaaS/暗色OLED等），强制排版配对+色彩系统+动效策略+背景纹理，阻断通用AI美学套路（Inter字体/紫色渐变/卡片套卡片）。适用于任何需要UI界面、前端页面、Dashboard、落地页、设计系统的场景。触发条件：用户提到"设计""UI""界面""页面""前端""美化""样式""CSS""组件""Dashboard""落地页"等关键词，或要求构建/修改前端界面时。
origin: custom
version: 1.0.0
triggers:
  - "设计"
  - "UI"
  - "界面"
  - "前端"
  - "页面"
  - "美化"
  - "样式"
  - "CSS"
  - "Dashboard"
  - "落地页"
  - "landing page"
  - "组件设计"
  - " redesign"
  - "make it look"
  - "aesthetic"
---

# Frontend Design — 设计优先的前端开发

**核心原则：设计思考先行，代码实现后行。** 永远不要在没确定美学方向的情况下开始写 CSS。

---

## 一、设计流程（强制顺序）

### 第 1 步：确定美学方向

在写任何代码之前，**必须先选择一个明确的美学方向**。以下为可选方向：

| 方向 | 特征 | 适用场景 |
|------|------|---------|
| **Brutalist（粗野主义）** | 原始/粗线条、黑白为主、大面积块状、等宽字体、显式边框 | 开发者工具、技术博客、反传统品牌 |
| **Editorial（编辑风）** | 优雅衬线体、宽松留白、网格系统、大标题、图文并茂 | 媒体/出版、奢侈品牌、深度内容站 |
| **Retro-Futuristic（复古未来）** | 霓虹色、扫描线、CRT效果、像素字体、暗色背景 | 游戏、Web3、科技艺术项目 |
| **SaaS Modern（现代SaaS）** | 清晰层级、品牌主色+灰阶、圆角卡片、系统字体、高效信息密度 | B2B产品、后台管理、企业门户 |
| **Dark OLED（暗色OLED）** | 纯黑底 `#000`、最小化发光、高对比文本、P3广色域点缀 | 夜间模式、代码编辑器、暗色主题产品 |
| **Organic/Nature（有机自然）** | 暖色调、圆润形状、自然纹理、衬线+手写体混合、柔和阴影 | 健康/环保品牌、生活方式产品 |
| **Minimalist Swiss（瑞士极简）** | Helvetica/无衬线、网格系统、红/黑/白调色板、极少装饰 | 高端品牌、建筑/设计工作室 |
| **Neon Brutalism（霓虹粗野）** | 粗野骨架+霓虹点缀、强烈对比、几何 harsh、单色+单荧光 | Gen Z品牌、音乐/创意网站、独立产品 |
| **Tech Noir（科技暗黑）** | 深蓝/黑渐变、科技蓝点缀、细线图标、数据可视化感、Fira/IBM字体 | AI/数据产品、科技大屏、量化Dashboard |
| **Editorial Elegance（编辑优雅）** | 大号衬线标题、35/65非对称布局、定制调色板、文化感字体 | 高端内容站、个人品牌、设计机构 |

**输出要求：** 确定方向后，用 1-2 句话向用户确认美学选择，然后进入第 2 步。

### 第 2 步：构建设计 Token 系统

基于选定的美学方向，定义以下设计 Token（使用 CSS 自定义属性或 Tailwind v4 `@theme`）：

```
必须定义的 Token：
├── 色彩系统
│   ├── --brand-hue          → 品牌色相（0-360，OKLCH 空间）
│   ├── --surface-1/2/3      → 背景层级（由浅到深 or 由深到浅）
│   ├── --text-1/2/3         → 文本层级（主/次/辅助）
│   ├── --accent-1/2         → 强调色（呼应品牌色相 ±30°）
│   └── --border             → 边框色
├── 排版系统
│   ├── --font-heading       → 标题字体（最多2种）
│   ├── --font-body          → 正文字体（1种）
│   ├── --font-mono          → 代码/数据字体（1种）
│   └── --font-scale         → 字号比例（1.25 major-third 或 1.333 perfect-fourth）
├── 间距系统
│   ├── --space-unit         → 基础间距单位（4px 或 8px）
│   └── --content-width      → 内容最大宽度
├── 圆角系统
│   ├── --radius-sm/md/lg    → 组件圆角
│   └── --radius-full        → 全圆角（药丸/Pill）
└── 动效系统
    ├── --easing-base        → 默认缓动（推荐 cubic-bezier(0.16,1,0.3,1)）
    ├── --duration-fast/normal/slow → 动效时长
    └── --motion-intensity    → 动效强度：subtle / moderate / expressive
```

### 第 3 步：排版配对规则

**禁止使用 Inter、Arial、系统默认字体作为标题字体。** 以下为经过验证的配对：

| 标题字体 | 正文字体 | 风格 |
|---------|---------|------|
| Playfair Display | Lora/Source Serif | 编辑/奢侈/优雅 |
| DM Serif Display | DM Sans/Inter | 现代编辑/品牌站 |
| Space Grotesk | Inter/System UI | 科技/SaaS/现代 |
| Clash Display | Satoshi/General Sans | Gen Z/新锐品牌 |
| Bebas Neue | Roboto/Open Sans | 强有力/运动/英雄区 |
| Syne | Space Grotesk | 实验性/创意工作室 |
| Fraunces | Commissioned | 温暖有机/生活方式 |
| IBM Plex Serif | IBM Plex Sans | 技术严谨/数据产品 |
| Cormorant Garamond | Proza Libre | 高端文化/出版 |
| Outfit | Plus Jakarta Sans | 现代SaaS/产品设计 |

**规则：**
- 标题字体和正文字体必须有**明显对比**（衬线 vs 无衬线，或宽体 vs 常规）
- 等宽字体用于代码/数据：JetBrains Mono / Fira Code / Geist Mono
- 中文字体优先：Noto Serif SC（衬线）/ Noto Sans SC（无衬线）

### 第 4 步：色彩规则

```
硬性规则：
1. 禁止纯黑 #000（暗色主题除外，且仅用于背景）
2. 禁止纯灰 #808080 系列 —— 灰色必须带色相偏移（如蓝灰、紫灰、暖灰）
3. 禁止紫色→蓝色渐变（AI 最大 cliché）
4. 文本禁止用灰色直接放在彩色背景上
5. 品牌色在 OKLCH 空间选取，保证 P3 色域可用

推荐工具思维：
- 主色从品牌色相出发，用 OKLCH 派生完整调色板
- 辅助色 = 品牌色相 ± 30°（类比色）或 ± 180°（互补色，慎用）
- 灰阶 = 品牌色相 + 极低饱和度（chroma 0.01-0.03）
```

### 第 5 步：背景与纹理

**AI 生成的页面最常见的缺陷是"白茫茫一片"的纯色背景。** 必须添加视觉层次：

```
轻量方案（CSS 即可，不增加加载体积）：
1. 噪点纹理：SVG feTurbulence → 叠加在背景上，opacity 0.03-0.06
2. 网格点阵：radial-gradient 圆点网格，间距 20-40px
3. 渐变光晕：大型模糊 radial-gradient 光斑（品牌色，opacity 0.1-0.2），position 固定
4. 细线网格：linear-gradient 十字线，适合数据Dashboard
5. 纸质纹理：多重复合 subtle 渐变 + 噪点

重量方案（需评估性能）：
6. Canvas/WebGL 粒子背景
7. Lottie 动画装饰
8. Three.js 3D 场景
```

### 第 6 步：动效策略

```
按场景选择动效强度：

Subtle（后台/数据产品）：
- 仅 hover 过渡（150-200ms）
- 页面切换 fade（200ms）
- 禁止弹跳/弹性缓动

Moderate（SaaS/产品）：
- hover 微缩放（1.02x）+ 阴影提升
- 入场动画：列表 stagger（每个元素延迟 50-80ms）
- 滚动触发：元素 reveal（opacity + translateY 20px）
- 使用 spring 物理缓动（stiffness 100, damping 20）

Expressive（品牌站/创意）：
- 视差滚动（多层级）
- 文字入场动画（逐字/逐行）
- SVG 路径绘制
- 鼠标跟随效果
- 页面切换有意义的变形过渡

禁止的动效：
- 弹跳缓动（bounce easing）—— 除非刻意为之
- 无限循环的 scale 脉冲 —— 看起来像广告
- 过长的入场动画（>500ms）—— 阻碍交互
```

---

## 二、反模式检测清单

在完成前端代码后，**必须**自检以下项目：

| # | 反模式 | 检查方式 |
|---|--------|---------|
| 1 | 是否使用了 Inter/系统默认作为**唯一**字体？ | → 需添加有特征的标题字体 |
| 2 | 是否存在紫色→蓝色渐变？ | → 替换为品牌色渐变或纯色 |
| 3 | 是否存在纯灰（#808080 系列）？ | → 灰色加色相偏移 |
| 4 | 是否存在彩色背景上的灰色文本？ | → 使用 rgba(255,255,255,0.7) 或对应浅色 |
| 5 | 是否"卡片套卡片"（card inside card）？ | → 最多一层卡片嵌套 |
| 6 | 背景是否纯色无纹理？ | → 添加至少一种背景纹理 |
| 7 | 是否缺少 hover/active/focus 状态？ | → 补全交互三态 |
| 8 | 暗色模式下是否有纯白 #fff 文本？ | → 降为 rgba(255,255,255,0.85) |
| 9 | 移动端是否信息密度过低（一屏只显示一个卡片）？ | → 调整移动端布局 |
| 10 | 是否缺少 loading/empty/error 状态？ | → 补全 UI 状态矩阵 |

---

## 三、输出模板

每次生成前端代码时，在代码前附上：

```markdown
## 设计决策

- **美学方向**：[选择的方向]
- **色彩**：品牌色 OKLCH(..., ..., ...)，辅助色 ...
- **排版**：标题 [字体名] + 正文 [字体名]
- **动效强度**：subtle / moderate / expressive
- **背景处理**：[具体的纹理/效果描述]

## 反模式自检

- [ ] 字体配对有对比 ✓
- [ ] 无紫色渐变 ✓
- [ ] 灰色带色相 ✓
- [ ] 无卡片套卡片 ✓
- [ ] 背景有纹理 ✓
- [ ] 交互三态补全 ✓
- [ ] 移动端适配 ✓
- [ ] UI状态矩阵完整 ✓
```

---

## 四、框架适配

根据不同技术栈自动调整输出：

| 框架 | Token 方案 | 动效方案 | 字体加载 |
|------|-----------|---------|---------|
| React/Next.js + Tailwind v4 | `@theme` 块 + OKLCH | Framer Motion / tailwind-animate | next/font |
| Vue/Nuxt + UnoCSS | `uno.config.ts` + OKLCH | @vueuse/motion / built-in Transition | @nuxt/fonts |
| Vanilla HTML/CSS | CSS 自定义属性 | CSS @keyframes + Intersection Observer | @fontsource / Google Fonts CDN |
| React + Styled Components | ThemeProvider + OKLCH | framer-motion | @fontsource |
| Astro | CSS 自定义属性 + design-tokens | CSS-only / Astro View Transitions | @fontsource |

---

**记住：用户不是在问"帮我写个好看点的按钮"——他们是在问"帮我建立整个产品的视觉语言"。用设计系统的思维回应，不要只给零散的 CSS 片段。**
