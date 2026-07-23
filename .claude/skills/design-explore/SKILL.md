---
name: design-explore
description: 设计变体探索与参数化调节 — 5套精选主题（Nordic Minimal/Neon Brutalism/Organic Growth/Tech Noir/Editorial Elegance），每个主题含完整色彩+字体+布局+动效配方；可调参数旋钮：设计变异度（safe→experimental）、动效强度（subtle→cinematic）、视觉密度（sparse→dense）。适用于：用户说"试试不同风格""给几个方案""换个感觉""太保守了大胆一点""太花哨了收敛一些"时，或需要为同一产品快速出多个设计方向时。
origin: custom
version: 1.0.0
triggers:
  - "换个风格"
  - "方案"
  - "变体"
  - "variation"
  - "alternative"
  - "大胆"
  - "保守"
  - "太花哨"
  - "太单调"
  - "收敛"
  - "好几个版本"
  - "探索"
  - "explore"
---

# Design Explore — 设计变体探索

5 套精选主题配方 + 3 个可调参数旋钮，快速探索设计空间。

---

## 一、5 套主题配方

### 主题 1：Nordic Minimal（北欧极简）

"少即是多"——温暖、克制、永恒。

- **色彩**：暖白底 + 灰蓝品牌 + 陶土点缀（禁止高饱和/渐变）
- **字体**：Sohne / Space Grotesk（标题）+ Inter（正文），细体优先
- **布局**：大留白（padding ≥ 48px）、单列流、不对称负空间
- **动效**：极 subtle，仅基本过渡（200-300ms）
- **适用**：生活方式品牌、高端SaaS、设计工作室

### 主题 2：Neon Brutalism（霓虹粗野）

原始力量 + 数字霓虹——强烈、不妥协。

- **色彩**：暗蓝灰底 + 霓虹绿品牌 + 霓虹粉强调，可见边框必须
- **字体**：Bebas Neue（标题全大写）+ Space Mono（正文等宽）
- **布局**：显式边框（2-3px solid）、尖锐直角、35/65非对称、元素重叠
- **动效**：硬切、hover色块翻转、打字机效果、禁止fade
- **适用**：Web3、音乐/创意网站、Gen Z品牌

### 主题 3：Organic Growth（有机生长）

自然、温暖、手工感。

- **色彩**：暖米色底 + 森林绿品牌 + 蜂蜜黄强调 + 陶土点缀（全暖色调）
- **字体**：Fraunces / Lora（标题衬线）+ Commissioner / Source Serif（正文）
- **布局**：流动曲线（border-radius ≥ 16px）、SVG 曲线分隔、卡片 pill 级圆润
- **动效**：CSS spring 物理缓动、元素"生长"出现（scale 0.9→1）
- **适用**：健康/环保、生活方式、手工品牌

### 主题 4：Tech Noir（科技暗黑）

精密、数据驱动、未来感。

- **色彩**：深蓝黑底 + 科技蓝品牌 + 青蓝点缀（蓝色系主导，3层surface）
- **字体**：IBM Plex Sans / Geist + JetBrains Mono（tabular-nums）
- **布局**：高数据密度、多栏网格、细线分隔（1px）、侧边栏面板、8px grid
- **动效**：functional only — 数据刷新闪烁、数值count-up、100-200ms
- **适用**：量化交易面板、数据分析、AI产品、B2B后台

### 主题 5：Editorial Elegance（编辑优雅）

以文字为王——华丽、从容、文化感。

- **色彩**：纸白底 + 墨水黑品牌 + 胭脂红强调（90%黑白灰+10%强调）
- **字体**：Playfair Display（标题衬线）+ Lora（正文）+ small-caps 辅助
- **布局**：35/65非对称、drop-cap、行距1.6-1.8、内容宽度680-720px
- **动效**：页面fade-in、图片微视差、链接hover下划线滑入
- **适用**：深度媒体、奢侈品牌、个人品牌、出版

---

## 二、3 个参数旋钮

### 旋钮 1：设计变异度
| 级别 | 布局 | 色彩 | 字体 | 动效 |
|------|------|------|------|------|
| **safe** | 标准网格 | 单品牌色+灰阶 | 系统常见字体 | 基础hover |
| **moderate** | 不对称不极端 | +1辅助色 | 有特征标题+标准正文 | 入场动画+微交互 |
| **experimental** | 破坏网格/重叠 | 撞色/霓虹/极端对比 | 小众字体/极端字重 | 粒子/3D/视差 |

### 旋钮 2：动效强度
| 级别 | 过渡时长 | 典型动效 |
|------|---------|---------|
| **subtle** | 100-200ms | 仅hover/active |
| **moderate** | 200-400ms | +入场stagger +滚动reveal |
| **expressive** | 400-800ms | +视差 +SVG +逐字动画 |
| **cinematic** | 800ms+ | +Three.js +粒子 +音频同步 |

### 旋钮 3：视觉密度
| 级别 | 信息/视口 | padding | h1字号 | 适用 |
|------|----------|---------|--------|------|
| **sparse** | 1-2 | ≥48px | ≥3rem | 品牌站/落地页 |
| **moderate** | 3-5 | 24-32px | 2.25rem | 产品页/SaaS |
| **dense** | 6+ | 12-16px | 1.5rem | 数据面板/交易终端 |

---

## 三、用户反馈 → 自动调节

| 用户说 | 调节 |
|--------|------|
| "太保守了" | 变异度 ↗ moderate/experimental |
| "太死板了" | 动效 ↗ moderate/expressive |
| "太花哨了" | 动效 ↘ moderate/subtle |
| "太挤了" | 密度 ↘ sparse |
| "不够有冲击力" | 三个旋钮同时 ↗ 一档 |
| "太复杂了" | 三个旋钮同时 ↘ 一档 |

---

## 四、快速生成 3 个方案

```
A：safe + subtle + moderate → "标准产品感"
B：moderate + moderate + moderate → "平衡有风格"  
C：experimental + expressive + sparse → "大胆突破"
```
