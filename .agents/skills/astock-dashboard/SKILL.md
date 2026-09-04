---
name: astock-dashboard
description: >
  AStock ETF Dashboard 项目知识库（FastAPI + Vue2 SPA + 小满Agent）。
  当用户询问dashboard项目结构、前端页面/路由、API接口、小满Agent配置、
  数据库schema（cache.db/agent.db）、Tech Noir设计系统、桌宠Live2D、
  "进入后台"导航、"角色"页聊天/文章、"工作日程"调度器等时使用。
  涵盖 etf-strategies/dashboard/ 和 etf-strategies/agent/ 全量代码。
---

# AStock ETF Dashboard 项目知识

## 项目概览

A股ETF量化策略回测系统，含 FastAPI Web Dashboard + 拟人 Agent「小满」。
- **后端**: FastAPI (`etf-strategies/dashboard/app.py`)
- **前端**: Vue 2 风格 SPA (`templates/dashboard.html` 529行) + 模块化 JS
- **Agent**: 独立常驻进程 `python -m agent`，基于 `dsh --profile xiaoman`
- **设计**: Tech Noir（科技暗黑，OKLCH 色域，brand hue 210°）

---

## 目录结构

```
etf-strategies/
├── dashboard/                    # Web Dashboard
│   ├── app.py                    # FastAPI 主应用 + lifespan
│   ├── db.py                     # cache.db schema (K线/策略/持仓/报告/用户)
│   ├── api_agent.py              # 小满 Agent API (/api/agent/*)
│   ├── api_daily.py              # 每日复盘/持仓/资产/信号/调度 API
│   ├── auth.py                   # JWT + bcrypt + 登录限流
│   ├── scheduler.py              # 定时任务引擎 (20s tick)
│   ├── templates/dashboard.html  # SPA HTML
│   └── static/
│       ├── css/                  # dashboard.css (Tech Noir), agent.css (暖色), pet.css
│       ├── js/                   # dashboard.js, daily.js, agent.js, auth.js, pet.js
│       └── vendor/               # echarts.min.js, marked.min.js
├── agent/                        # 小满 Agent 常驻进程
│   ├── __main__.py               # 入口
│   ├── config.py                 # RSS源/发文节奏/合规
│   ├── db.py                     # agent.db schema (会话/消息/文章/观点/知识)
│   ├── dsh_runner.py             # dsh LLM 调用封装
│   ├── personas/xiaoman/persona.md  # 小满人设卡
│   └── core/                     # persona.py, memory.py, knowledge.py, behavior.py, lifecycle.py
│       └── channels/web.py       # Web渠道：聊天directive组装
└── .dsh/profiles/xiaoman/        # dsh profile 配置
```

---

## 页面与路由

Dashboard 是 SPA，通过 topnav 切换视图，CSS class `view-active` 控制显示。

### 主页模式（所有用户可见）
| View ID | 导航标签 | 说明 |
|---------|---------|------|
| `view-strategies` | 📊 策略全景 | 策略表/KPI卡片/详情面板 |
| `view-portfolio` | 💰 持仓/资产 | 持仓表格/交易录入 |
| `view-signals` | 📡 每日信号 | 每日交易信号 |
| `view-reports` | 📄 报告 | 每日复盘报告 |

### 后台模式（仅 admin 可见）
| View ID | 导航标签 | 说明 |
|---------|---------|------|
| `view-scheduler` | 🗓️ 工作日程 | 调度任务/运行日志 |
| `view-agent` | 💬 角色 | 小满聊天+文章动态 |

### 模式切换流程
- `switchMode()` (`dashboard.js:1484`)
- `applyModeUI(mode)` 给 `#topnav` 加/移除 `mode-admin` class
- CSS 控制 nav-home/nav-admin 的显示
- 进入admin默认跳 `view-scheduler`（`dashboard.js:1493`）
- `switchView()` (`daily.js:52`) 切换 view + 懒加载

---

## API 接口

### Agent 相关 (`api_agent.py`, prefix `/api/agent`)
| 方法 | 路径 | 功能 |
|------|------|------|
| GET | /status | 小满状态(alive/attendance/mood/current_task) |
| POST | /sessions | 新建会话 |
| GET | /sessions | 会话列表(按updated_at DESC) |
| DELETE | /sessions/{sid} | 删除会话 |
| GET | /sessions/{sid}/messages | 加载历史消息 |
| POST | /sessions/{sid}/messages | 发送消息→SSE流式回复 |
| GET | /articles | 文章/动态列表 |
| GET | /articles/{aid} | 文章详情 |
| GET | /sources | 素材源列表 |
| POST | /sources | 添加素材源(website/manual) |
| DELETE | /sources/{sid} | 删除素材源 |
| POST | /sources/{sid}/toggle | 启用/停用 |

### 其他 API
- `/api/strategies`, `/api/signals`, `/api/charts`, `/api/backtest` — 策略相关
- `/api/portfolio`, `/api/daily-signals`, `/api/reports` — 持仓/信号/报告
- `/api/scheduler` — 调度器管理

---

## 数据库

### agent.db (`etf-strategies/agent/data/agent.db`)
| 表 | 用途 | 关键字段 |
|----|------|---------|
| agent_sessions | 聊天会话 | id, persona, title, updated_at |
| agent_messages | 消息 | session_id(FK), role(user/assistant), content, sources(JSON) |
| agent_articles | 文章 | title, content, kind(article/post), topics(JSON), sources(JSON) |
| agent_opinions | 观点库 | topic, opinion, article_id |
| agent_knowledge | RSS/搜索素材 | source, title, url(UNIQUE), content, consumed |
| agent_metadata | KV元数据 | key, value(heartbeat/published_on) |
| agent_sources | 自定义素材源 | name, url, kind(website/manual), enabled |

### cache.db (`etf-strategies/dashboard/data/cache.db`)
存储 K线/策略指标/信号/持仓/用户/报告等Dashboard数据。

支持 `DB_MODE=memory` — 纯内存SQLite + TOS云快照备份。

---

## 小满 Agent

### 人设 (`personas/xiaoman/persona.md`)
- 名源：二十四节气「小满」— 小满胜万全
- 形象：少女(18+)，元气、好奇、偶尔毒舌
- 语气：口语化、有活力、善用比喻、专业感切换自然
- 红线：不构成投资建议、不给确定性买卖指令

### 配置 (`agent/config.py`)
- `PERSONA_ID = "xiaoman"`
- `DSH_TIMEOUT_SECONDS = 120`
- `PUBLISH_HOUR = 17`, `PUBLISH_MINUTE = 30`（每日发文时间）
- `MAX_ARTICLES_PER_DAY = 1`
- `TICK_SECONDS = 300`（轮询间隔）
- `FORBIDDEN_VERBS = ("买入","卖出","加仓","清仓","建仓","止损","止盈","赶紧买","赶紧卖")`

### 聊天流程
```
前端发送消息 → POST /api/agent/sessions/{sid}/messages
  → agent_db.message_add(sid, "user", content)
  → web.chat_task(sid, content) 组装 directive:
     知识素材(knowledge_unconsumed limit 5) + 会话历史(build_chat_context limit 30) + 用户消息
  → dsh_runner.run_task(task) 调用 dsh --profile xiaoman headless
  → agent_db.message_add(sid, "assistant", output, sources)
  → SSE 全文返回 → 前端打字机渲染(marked.parse + typewriter动画)
```

### 素材采集
- RSS通道：通过RSSHub拉取 财联社/华尔街见闻/知乎热榜/雪球热帖（仅标题+链接+摘要）
- 自定义站点：`collect_custom_sources()` 发directive让LLM逛站找文章 → JSON入库
- 手动喂URL：kind=manual 直接入库 agent_knowledge

---

## 设计系统

### Tech Noir 主色调 (`dashboard.css`)
- 背景：`oklch(0.06-0.12)` 多层深浅
- 品牌蓝：`--accent-blue: oklch(0.72 0.16 215)`
- 数据青：`--accent-cyan: oklch(0.75 0.13 195)`
- 正绿/负红：`oklch(0.68/0.60)` 145°/25°
- 警告琥珀：`oklch(0.74 0.14 80)`

### 小满暖色调 (`agent.css`)
- `--xm-accent: oklch(0.78 0.15 60)` 蜜橘
- `--xm-accent-2: oklch(0.72 0.12 90)` 琥珀
