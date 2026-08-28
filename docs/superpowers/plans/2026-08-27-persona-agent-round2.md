# 小满第二轮优化计划（素材源增强 + OpenViking 隔离 + 文章→动态）

> 日期：2026-08-27 | 流程：dev-workflow | 状态：**①②③ 完成**（全量测试 375 passed / 1 skipped）；OpenViking 待 provider 配置
> 决策：三项全做（用户确认）
> 前置：dsh 化已完成（xiaoman profile，web_search/web_fetch 可用，实测读网页成功）

## ① 素材源增强（自定义链接/站点）

目标：用户给链接/站点，小满自己浏览找文章当素材。

- **即时**：聊天丢 URL → 小满当场 fetch 浏览（dsh 能力，零开发，已可用）
- **手动喂**：`POST /api/agent/sources`（kind=manual，单条 URL）→ 入库 `agent_knowledge`（source=manual）
- **常驻站点源**：新表 `agent_sources`（name/url/kind=website/enabled）→ 采集 directive：
  `dsh --profile xiaoman "浏览以下站点，挑 2-3 篇好文章，输出 JSON 数组"` → Python 解析 → `knowledge_upsert`（source=站点名）
- 调度：lifecycle tick 加"自定义源采集"（每日 1 次，RSS 之后）

## ② OpenViking 启用与隔离

- 前置：`pip install openviking` + `openviking-server init`（需 embedding provider：火山/OpenAI/Ollama；DeepSeek 无 embedding API）
- xiaoman profile 装 `@openviking/dsh-memory-plugin`
- **隔离**：dsh_runner 起小满任务时注入 env `OPENVIKING_PEER_ID=xiaoman` + `OPENVIKING_RECALL_PEER_SCOPE=actor`（报告 Agent headless 不设 → 默认 peer）→ 记忆互不混淆
- 验证：小满 `viking_remember` → `viking_search` 闭环；报告任务搜不到小满记忆

> ✅ **已就绪**：openviking-server 0.4.16 已装（--user）；doctor 全 PASS（embedding=volcengine ep-20260826110807-kvhsh，VLM=doubao-seed-2-0-mini）；xiaoman profile 已装 @openviking/dsh-memory-plugin ^0.2.1；隔离 env 已注入 dsh_runner（默认 XIAOMAN_OV_ENV）；server 可启动（127.0.0.1:1933）。
> ⛔ **阻塞**（2026-08-28 实测）：火山方舟 embedding endpoint `ep-20260826110807-kvhsh` **月度配额超限（429 AccountQuotaExceeded）**，重置时间 **2026-09-04**。server 能起、viking 请求能到达，但 embedding 调用即 429，session 创建失败。→ **等待 9/4 重置后启用**，或换 provider（火山其他 endpoint / OpenAI 兼容 / 本地 Ollama）。

## ③ 文章 → 动态

- 数据：`agent_articles` 加 `kind` 列（article/post），SQLite ALTER TABLE 迁移（幂等）
- 行为：`run_post_pipeline`（发动态：短文本 50-200 字，事件触发/每日 1-3 条，dsh directive）
- API：articles 支持 `?kind=` 过滤；列表返回 kind
- 前端：tab 改「我的动态」→ 时间线（动态短条 + 文章卡混合，时间倒序）

## 风险

| 风险 | 应对 |
|---|---|
| OpenViking 网络/provider 不可用 | 试装；卡住则隔离方案落文档，①②③不受阻 |
| 采集 directive 输出非 JSON | 解析容错（提取 ```json 块 / 逐条正则兜底），失败下次重试 |
| ALTER TABLE 迁移 | init_db 幂等检测列存在 |
