# 小满全面 dsh 化迁移计划（方案 A）

> 日期：2026-08-27 | 流程：dev-workflow | 状态：**实施完成**（全量测试 357 passed / 1 skipped；真实冒烟通过）
> 决策：用户确认「直接做 A：全面 dsh 化」——小满 Agent 底层改用 dsh，key 单点。
> 前置：`docs/superpowers/specs/2026-08-27-persona-agent-design.md`（D1–D6）+
>       `docs/superpowers/plans/2026-08-27-persona-agent-mvp.md`（已实施，本次为架构迁移）

## 0. 调研结论（2026-08-27 实测/源码）

| 项 | 结论 |
|---|---|
| headless 模式 | `dsh --profile <p> "<task>"` 执行任务打印最终回复退出；**无流式、无 --resume**（源码确认） |
| profile 机制 | = `package.json`（`dsh.profile.bundles` 声明插件组合）+ `cordis.patch.yml`（配置覆盖）；bundles 从全局解析，无需 pnpm 安装 |
| 人设注入 | `system-prompt` 插件 `config.persona`（dsh-base/cordis.patch.yml 默认 `''`，可 patch 覆盖） |
| 默认 LLM | `agent-default-model`: provider `deepseek-official` / model `deepseek-v4-flash`；`llm-deepseek` apiKeyEnv 默认 `DEEPSEEK_API_KEY`（credentials 文件或环境变量） |
| key 单点 | 本地：`~/.dsh/.credentials.yaml`；Docker：环境变量 `DEEPSEEK_API_KEY`（dsh 支持 ambient env） |
| 冷启动 | ~0.63s（boot），完整任务另加 LLM 时间 |
| 生态复用 | skills（含 a-stock-data）、web_search、session 持久化、fs 工具均在 base 组合内 |

## 1. 目标架构（两个 Agent 同构）

```
Agent 1（报告/信号）: dsh --profile headless "<报告任务>"        ← 现状不动（scheduler 已有 _exec_dsh）
Agent 2（小满）     : dsh --profile xiaoman "<directive>"        ← 新 profile

etf-strategies/agent/（Python 编排壳保留，职责收窄）
├── dsh_runner.py    # 新：subprocess 调 dsh --profile xiaoman → 整段文本（替代 llm.py）
├── db.py            # 保留：agent.db = dsh 的长期记忆仓库（会话/文章/观点/知识）
├── core/
│   ├── behavior.py  # 改造：compose 用 dsh directive；llm_fn 默认 = dsh_runner（注入点不变）
│   ├── knowledge.py # 保留：RSS 采集入库（确定性 IO 归 Python，dsh 只思考）
│   ├── memory.py    # 保留：会话历史组装（注入 directive）
│   ├── persona.py   # 保留：persona.md 作为人设源文档（供生成 profile patch + 校验）
│   └── lifecycle.py # 保留：常驻 tick（RSS 节流 + 17:30 发文调度）
├── channels/web.py  # 改造：聊天 directive 组装（历史 + 用户消息 → dsh task）
└── personas/xiaoman/persona.md  # 保留（人设单一事实源）
```

## 2. 关键设计

- **聊天**：`POST /api/agent/sessions/{id}/messages` → 存 user → 组装 directive（人设由 dsh profile 注入，task 只含历史+用户消息）→ `dsh --profile xiaoman` → 整段回复 → 存 assistant → **SSE 一次事件返回全文**（保留通道，前端打字机模拟流式）
- **发文**：lifecycle tick（17:30 + 当日未发 + 素材≥3）→ 组装 directive（"基于今日素材写学习笔记"）→ dsh → behavior.validate_article 自检 → article/opinion 入库 + 消费素材
- **采集**：仍由 Python knowledge.py 完成（RSSHub → agent.db），dsh 不碰采集 IO
- **key 单点**：删除 llm.py 直连通道与 envfile.py fallback；一切 LLM 走 dsh（本地 credentials / Docker 环境变量）
- **Docker**：Dockerfile 增加 `npm i -g @deepseek-ai/dsh`；agent 容器 `DEEPSEEK_API_KEY` 由 compose 注入；dsh_runner 在容器内找全局 dsh

## 3. 文件变更清单

| 操作 | 文件 | 说明 |
|---|---|---|
| 新建 | `~/.dsh/profiles/xiaoman/{package.json, pnpm-workspace.yaml, cordis.patch.yml}` | Agent 2 实例；persona 注入 system-prompt |
| 新建 | `etf-strategies/agent/dsh_runner.py` | subprocess 封装：命令构造/超时/非零退出/输出提取 |
| 改造 | `agent/core/behavior.py` | compose_article 默认 llm_fn → dsh_runner；directive 模板 |
| 改造 | `agent/channels/web.py` | chat directive 组装（历史+用户消息） |
| 改造 | `dashboard/api_agent.py` | 聊天改 dsh_runner；SSE 一次返回全文 |
| 删除 | `agent/core/llm.py`、`agent/envfile.py` | 直连通道退役 |
| 改造 | 前端 `static/js/agent.js` | SSE 单事件 → 打字机逐字渲染 |
| 测试 | `tests/test_agent_dsh.py`（新）、`test_agent_behavior/api.py`（mock dsh_runner）、删 `test_agent_llm/envfile.py` | |
| 改造 | `Dockerfile`、`docker-compose.yml` | 装 dsh、注入 DEEPSEEK_API_KEY |

## 4. 实施步骤（TDD）

1. 建 xiaoman profile + 冒烟 `dsh --profile xiaoman "<最小任务>"`（验证人设注入与 LLM 通）
2. TDD `dsh_runner.py`（mock subprocess：命令、超时 120s、非零退出、stdout 提取）
3. 改造 `behavior.py` + `channels/web.py`（directive 组装，llm_fn 注入点不变）
4. 改造 `api_agent.py`（dsh_runner + SSE 单事件）；前端打字机
5. 删 `llm.py`/`envfile.py`；测试适配（删 llm/envfile 测试，新增 dsh 测试，behavior/api mock dsh_runner）
6. 冒烟真跑一次聊天 directive（花少量 token 验证链路）
7. 全量回归 + code-review

## 5. 风险

| 风险 | 应对 |
|---|---|
| dsh 冷启动 + LLM 时间（聊天单轮 2-5s） | 前端打字机掩盖；接受（非流式是方案 A 已知代价） |
| headless 输出含无关文本（思考过程？） | 源码确认"print the final assistant message"；dsh_runner 提取最终回复段 |
| 子进程并发（多用户同时聊） | 每轮独立 subprocess 天然隔离；dashboard 端串行（单用户场景） |
| Docker 内 dsh 安装体积 | dsh 全局装一次；与 claude code 并存 |
| 真实冒烟花 token | 用最小 prompt（"回答：在"）验证链路 |
