# 拟人 Agent「小满」MVP 实施计划

> 日期：2026-08-27 | 流程：dev-workflow（brainstorming ✅ → writing-plans ✅ → TDD ✅ → executing-plans ✅ → code-review ✅）
> 状态：**实施完成** — 全部步骤落地，`etf-strategies/tests` 全量回归 355 passed / 1 skipped（含新增 agent 测试 53 项）
> 依据：`docs/superpowers/specs/2026-08-27-persona-agent-design.md`（决策点 D1–D6 已确认）

## 0. 已确认决策（brainstorming 产出）

| 项 | 决策 |
|---|---|
| 美学方向 | **Tech Noir 骨架 + 小满暖色延伸**（深色/字体/网格沿用 dashboard.css，角色页加蜜橘-琥珀 accent） |
| LLM | **DeepSeek 官方 API**（OpenAI 兼容，`DEEPSEEK_API_KEY` 环境变量，model `deepseek-chat`，SSE 流式） |
| DB | 独立 `agent/data/agent.db`（WAL），五表：sessions/messages/articles/opinions/knowledge + metadata |
| RSS | 公共 RSSHub 实例（默认 `https://rsshub.app`，config 可换），标准库 `xml.etree` 解析（零新依赖） |
| 常驻 | `python -m agent` 独立进程；dashboard 只读 agent.db + 健康探针，不宿主 |
| 数据纪律 | 涉 A 股数据一律 `a-stock-data`；文章/回答标注数据时点与来源 |

## 1. 目标与验收（方案文档 §8）

1. dashboard「💬 角色」页出现：聊天 tab（SSE 流式）+ 文章 tab（列表/详情）
2. agent 常驻进程独立存活：dashboard 重启角色不丢；heartbeat 探针 + 状态页可见
3. 每日 1 篇外部财经内容学习总结文章（RSS 素材 → LLM 生成 → 自检 → 入库），带数据时点/来源标注
4. 观点库可检索历史观点且前后自洽（人设卡 + opinions 一致性校验）
5. 涉 A 股数据来自 a-stock-data
6. `etf-strategies/tests` 全量通过（新增 agent 测试）

## 2. 文件清单

```
etf-strategies/
├── agent/
│   ├── __init__.py            # 版本/导出
│   ├── __main__.py            # python -m agent 常驻入口
│   ├── config.py              # 配置：RSS 源/LLM/发文节奏/DB 路径（可被测试覆盖）
│   ├── db.py                  # agent.db：五表 + metadata + CRUD（WAL 同 dashboard 模式）
│   ├── core/
│   │   ├── __init__.py
│   │   ├── persona.py         # 人设卡加载(persona.md)/system prompt 注入/观点自洽校验
│   │   ├── memory.py          # 会话记忆/观点库 opinions/偏好 preferences
│   │   ├── knowledge.py       # RSS 拉取+解析+去重入库；素材检索（按新鲜度/未消费）
│   │   ├── llm.py             # DeepSeek API 适配：chat_stream()（SSE）/ chat()（非流式）
│   │   ├── behavior.py        # 纯函数：should_publish()/pick_topic()/draft_pipeline 编排
│   │   └── lifecycle.py       # 常驻主循环：RSS 轮询→发文调度→heartbeat；看门狗
│   ├── personas/xiaoman/
│   │   └── persona.md         # 人设卡（单一事实源）
│   └── channels/
│       ├── __init__.py
│       └── web.py             # 聊天上下文组装 / 文章呈现数据（供 dashboard API 调用）
├── dashboard/
│   ├── api_agent.py           # 新 router：chat sessions/messages(SSE)/articles/status
│   ├── app.py                 # include_router(agent_router)（1 行）
│   ├── templates/dashboard.html  # nav 加「💬 角色」+ <div id="view-agent">（两个 tab）
│   └── static/
│       ├── css/agent.css      # 暖色延伸：--accent 蜜橘/琥珀、聊天气泡、文章排版
│       └── js/agent.js        # 聊天 UI(SSE)+文章列表/详情（复用 marked）
└── tests/
    ├── test_agent_db.py
    ├── test_agent_persona.py
    ├── test_agent_knowledge.py
    ├── test_agent_llm.py
    ├── test_agent_behavior.py
    └── test_agent_api.py
```

## 3. 实施步骤（每步 TDD：先失败测试 → 实现 → 通过）

| # | 步骤 | 测试文件 | 实现文件 | 说明 |
|---|------|---------|---------|------|
| 1 | agent 包骨架 + config + db 五表 CRUD | test_agent_db.py | agent/db.py, agent/config.py | 抄 dashboard/db.py 的 get_conn/WAL 模式；五表 + metadata(heartbeat/每日发文状态) |
| 2 | 人设卡 + 观点自洽 | test_agent_persona.py | core/persona.py, personas/xiaoman/persona.md | persona.md 按方案 §2.1 写；一致性校验=检索 opinions 冲突 |
| 3 | 知识源：RSS 解析/入库/检索 | test_agent_knowledge.py | core/knowledge.py | fixture XML（财联社/知乎样张），不真联网；按 link 去重；检索=未消费+新鲜度 |
| 4 | LLM 适配（mock 网络） | test_agent_llm.py | core/llm.py | requests mock：流式 SSE 解析 + 非流式；无 key 报清晰错误 |
| 5 | 记忆：会话/观点库 | （并入 db/persona 测试） | core/memory.py | 薄封装：会话上下文读取、观点提取写入 |
| 6 | 行为引擎（纯函数） | test_agent_behavior.py | core/behavior.py | should_publish（交易日+当日未发+素材新鲜）、pick_topic（去重/优先级）、草稿自检规则（免责声明/来源标注/非整篇复制） |
| 7 | 常驻主循环 | （手工验证+状态接口） | core/lifecycle.py, __main__.py | tick：RSS 增量→发文调度→heartbeat 写 metadata；可注入 clock 便于测试 |
| 8 | web 渠道 + dashboard API | test_agent_api.py | channels/web.py, dashboard/api_agent.py | TestClient：会话 CRUD、SSE 聊天（mock llm）、文章列表/详情、status（heartbeat） |
| 9 | 前端：nav + view-agent + agent.css + agent.js | （design-critique 自检） | dashboard.html, static/css/agent.css, static/js/agent.js | 聊天（气泡/SSE/会话切换）+ 文章（列表/详情/marked）；完成后 design-critique 44 条反模式自检 |
| 10 | 集成 + 全量回归 + code-review | pytest 全量 | app.py 1 行 | 全量测试；自查清单（命名/边界/错误处理/数据纪律）；涉金融逻辑无（不含信号计算） |

## 4. 关键设计约定

- **SSE 聊天流**：`POST /api/agent/chat/sessions/{id}/messages` → 组装上下文（人设卡+会话+观点库+知识检索）→ llm 流式 → `data: {delta}` 事件 → 结束异步落库 + 提取观点
- **每日发文**：behavior 判定（交易日 17:30 后 + metadata 当日未发）→ knowledge 取素材 → llm 草稿 → 自检（非投资建议声明/来源标注/观点自洽）→ articles 入库
- **健康探针**：lifecycle 每 tick 写 `metadata['agent_heartbeat']`；`GET /api/agent/status` 读它判断进程存活
- **测试隔离**：agent 测试用 `tmp_path` 指向独立 db；llm/knowledge 测试 mock 网络，不真调 API/不真联网
- **RSS 源配置**（config.py，可改）：财联社电报 `cls/telegraph`、华尔街见闻 `wallstreetcn/live`、知乎 `zhihu/hotlist`、雪球 `xueqiu/hots`（路由名以 RSSHub 为准，测试用本地 fixture）

## 5. 风险与应对

| 风险 | 应对 |
|---|---|
| 公共 RSSHub 不可达/限流 | config 多实例可切换 + tick 容错（失败不中断、下次重试） |
| DEEPSEEK_API_KEY 缺失 | llm 抛清晰错误；status 接口暴露"llm 未配置"状态 |
| SSE 在 uvicorn/TestClient 差异 | 用 TestClient 流式读（starlette 支持）；前端 EventSource/readable stream 双实现 |
| 常驻进程与 dashboard 双写 agent.db | WAL 模式 + 短事务；chat 写消息与 lifecycle 写文章互不阻塞 |
