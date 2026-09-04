---
name: ui-ux-pro-max
description: UI/UX设计系统生成器 — 240+视觉风格、127种字体配对、99条UX准则，自动匹配产品类型生成完整设计系统（色彩/排版/间距/圆角/阴影/动效），内置无障碍检查（WCAG AA+）和响应式断点策略。触发条件：需要生成完整设计系统、建立产品视觉语言、或用户明确要求"设计系统""design system""style guide"时。与frontend-design配合：frontend-design负责美学方向选择，本skill负责系统化落地。
origin: custom
version: 1.0.0
triggers:
  - "设计系统"
  - "design system"
  - "style guide"
  - "设计规范"
  - "设计语言"
  - "design token"
  - "主题系统"
  - "品牌规范"
---

# UI/UX Pro Max — 设计系统生成器

从产品类型出发，自动生成完整、可落地的设计系统。**本技能与 `frontend-design` 协作：frontend-design 定美学方向，本技能做系统化工程落地。**

---

## 一、产品类型 → 设计系统自动匹配

首先确定产品类型（如果用户未明确，根据上下文推断并确认）：

| 类型 | 典型场景 | 推荐风格 |
|------|---------|---------|
| **Fintech Dashboard** | 股票/量化/交易面板 | Tech Noir + 数据密度优先 |
| **B2B SaaS** | 企业管理/CRM/后台 | SaaS Modern + 清晰层级 |
| **Developer Tool** | API管理/CLI工具/DevOps | Brutalist + 暗色OLED |
| **E-commerce** | 电商/零售 | 品牌色主导 + 大产品图 |
| **Content/Media** | 博客/媒体/出版 | Editorial + 排版优先 |
| **Health/Wellness** | 健康/医疗/健身 | Organic + 柔和配色 |
| **Social/Community** | 社交/社区/论坛 | 活泼色 + 圆润形状 |
| **AI/ML Product** | AI应用/数据标注/模型管理 | Tech Noir + 渐变点缀 |
| **Landing Page** | 产品落地页/营销 | 品牌表达 + 英雄区叙事 |
| **Mobile App** | 移动端优先 | 大触控目标 + 底部导航 |
| **Web3/Crypto** | DApp/NFT/DeFi | Retro-Futuristic / Neon Brutalism |

---

## 二、设计 Token 完整生成

### 2.1 色彩系统（OKLCH 优先）

产生完整的颜色 Token，覆盖亮/暗双模式：

```css
/* === 亮色模式 === */
:root {
  --brand-50:  oklch(0.98 0.01 [hue]);
  --brand-100: oklch(0.95 0.02 [hue]);
  --brand-200: oklch(0.90 0.04 [hue]);
  --brand-300: oklch(0.83 0.07 [hue]);
  --brand-400: oklch(0.75 0.10 [hue]);
  --brand-500: oklch(0.65 0.13 [hue]);  /* 主色 */
  --brand-600: oklch(0.55 0.11 [hue]);
  --brand-700: oklch(0.45 0.09 [hue]);
  --brand-800: oklch(0.35 0.07 [hue]);
  --brand-900: oklch(0.25 0.04 [hue]);
  --brand-950: oklch(0.15 0.02 [hue]);

  --surface-1: oklch(1.00 0.00 [hue]);
  --surface-2: oklch(0.97 0.01 [hue]);
  --surface-3: oklch(0.93 0.02 [hue]);

  --text-primary:   oklch(0.15 0.01 [hue]);
  --text-secondary: oklch(0.45 0.02 [hue]);
  --text-tertiary:  oklch(0.65 0.02 [hue]);

  --success: oklch(0.65 0.18 145);
  --warning: oklch(0.75 0.16 85);
  --danger:  oklch(0.60 0.20 25);
  --info:    oklch(0.65 0.15 240);

  --border-1: oklch(0.88 0.01 [hue]);
  --border-2: oklch(0.80 0.02 [hue]);
}

/* === 暗色模式 === */
[data-theme="dark"] {
  --surface-1: oklch(0.12 0.01 [hue]);
  --surface-2: oklch(0.17 0.02 [hue]);
  --surface-3: oklch(0.22 0.02 [hue]);
  --text-primary:   oklch(0.93 0.01 [hue]);
  --text-secondary: oklch(0.70 0.02 [hue]);
  --text-tertiary:  oklch(0.50 0.02 [hue]);
  --border-1: oklch(0.22 0.02 [hue]);
  --border-2: oklch(0.30 0.03 [hue]);
}
```

### 2.2 排版 Token

```css
:root {
  --text-xs: 0.75rem; --text-sm: 0.875rem; --text-base: 1rem;
  --text-lg: 1.125rem; --text-xl: 1.25rem; --text-2xl: 1.5rem;
  --text-3xl: 1.875rem; --text-4xl: 2.25rem; --text-5xl: 3rem; --text-6xl: 3.75rem;
  --weight-normal: 400; --weight-medium: 500; --weight-semibold: 600; --weight-bold: 700;
  --leading-tight: 1.2; --leading-normal: 1.5; --leading-relaxed: 1.7;
  --tracking-tight: -0.02em; --tracking-normal: 0; --tracking-wide: 0.05em;
}
```

### 2.3 间距 + 阴影

```css
--space-1: 0.25rem; --space-2: 0.5rem; --space-3: 0.75rem;
--space-4: 1rem; --space-6: 1.5rem; --space-8: 2rem;
--space-12: 3rem; --space-16: 4rem; --space-24: 6rem;

--shadow-sm: 0 1px 2px rgba(0,0,0,0.06);
--shadow-md: 0 4px 6px -1px rgba(0,0,0,0.07);
--shadow-lg: 0 10px 15px -3px rgba(0,0,0,0.08);
--shadow-xl: 0 20px 25px -5px rgba(0,0,0,0.10);
```

---

## 三、UX 准则精选

### 触控与交互
1. 最小触控目标 44×44px（移动端 48×48px）
2. Hover/Active/Focus 三态可见（颜色变化 ≥ 3:1）
3. 点击区域 > 视觉元素（padding 补足到 44px）
4. 100ms 响应，超过 1s 需要 loader
5. 焦点环必须有（`:focus-visible`，2px 偏移）

### 信息架构
1. 三秒法则 — 3 秒内理解页面主要内容
2. 渐进披露 — 先核心，次要展开
3. F型/Z型扫描 — 文本 F 型，营销 Z 型
4. 每组 ≤ 7±2 项（Miller 定律）
5. 视觉层级 ≤ 3 层

### 无障碍（WCAG AA+）
1. 正文对比度 ≥ 4.5:1，大文本 ≥ 3:1
2. 非颜色传达信息（不只靠红色表示错误）
3. 尊重 `prefers-reduced-motion`
4. 语义化 HTML（button 不是 div）
5. Alt 文本有意义

---

## 四、响应式断点

```css
/* 移动优先 — Base: < 640px 无需媒体查询 */
@media (min-width: 640px)  { /* sm */ }
@media (min-width: 768px)  { /* md */ }
@media (min-width: 1024px) { /* lg */ }
@media (min-width: 1280px) { /* xl */ }
@media (min-width: 1536px) { /* 2xl */ }
```

移动端原则：单列布局 / 触控目标 ≥ 48px / 底部操作栏 / 表格→卡片

---

## 五、组件状态矩阵

每个交互组件必须覆盖：
**Default → Hover → Active → Focus → Disabled → Loading → Empty → Error → Success → Edge Cases**

---

## 六、输出格式

1. 产品类型判断 + 设计策略概述
2. 视觉风格推荐（3个选项，附理由）
3. 字体配对推荐（2个选项）
4. 完整 CSS Token 文件（亮色 + 暗色）
5. 关键组件设计规范（按钮/输入框/卡片/导航/表格）
6. 响应式策略
7. 无障碍检查清单

---

**本技能产出的是"设计工程规范"。所有 Token 必须可直接复制使用。**
