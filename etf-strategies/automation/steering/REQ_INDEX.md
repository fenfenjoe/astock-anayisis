# ETF 策略优化需求索引

> 最后更新: 2026-09-09

## 状态汇总

| 状态 | 数量 |
|------|------|
| OPEN | 1 |
| IN_PROGRESS | 0 |
| IMPLEMENTED | 1 |
| CLOSED | 0 |
| ADOPTED | 0 |
| REJECTED | 0 |

## 需求列表

| ID | 标题 | 优先级 | 影响范围 | 状态 | 创建日期 |
|----|------|--------|---------|------|---------|
| REQ-001 | 数据刷新流程防护 — 收盘后强制补全当日 bar + 非活跃/持仓标的定期刷新 | P1 | 数据质量 | OPEN | 2026-09-03 |
| REQ-002 | 用户待办回复页面 — 落地为聊天页「📌 提示与待办」（提示不需回复；待办回复后按类型回调执行；聊天 tab 未读小红点）| P3 | 社交平台/经验闭环 | IMPLEMENTED | 2026-09-08 |

> REQ-002 实施记录（2026-09-09）：
> 形态从"独立回复页面"改为**融入聊天页**（用户确认）：聊天主区上方独立面板展示提示/待办，
> 聊天 tab 右上小红点=未读数。
> 已交付：`agent_notices` 表（文件/云双后端）+ CRUD；`agent/core/notices.py` 生成器
> （Cookie 待办 `cookie_provide` + 复盘完成提示）与回复回调 dispatch；`/api/agent/notices*` API；
> 前端面板 + 小红点。内置 2 类生成器已接；Harness 各任务的 prompt 生成后续接入。
> 2026-09-09 追加（用户反馈迭代）：
> - 展示排序：未处理（未读且 open）在前、已处理（已阅/已回复/已忽略）在后；分页防堆积（默认每页 10）
> - 待办状态机：`open(未处理) → done(处理成功)`；回调失败回 `open` 并展示小满的失败原因
>   （`result` 字段：成功=小满回复，失败=失败原因；失败后 read_at 清空 → 小红点重新提醒，可重试）
> - 忽略（dismissed）：用户手动忽略 → 不再提示、不计未读
> - 前端状态变更**就地更新**（不整页重拉），已处理项即时置灰并展示小满回复/失败原因
> 2026-09-09 BUG-FIX（真实环境复现 500）：
> - 云后端 `agent_notices.todo_data` 是 JSONB，cloud_db 未解析 → 回复待办时
>   `todo_data.get("platform_id")` 抛 `AttributeError: 'str' object has no attribute 'get'` → 500。
>   修复：`cloud_db._JSON_FIELDS` 加 `todo_data`；`notices._handle_cookie_provide` 兼容字符串 todo_data。
> - `cloud_db.update` 剥离 None → 无法把 read_at 置 NULL（失败重置未读失效）。修复：update 保留 None
>   （PostgREST null = SQL NULL），调用方显式传 None 即清空该列。
> - 均已加回归测试（test_cloud_db / test_agent_notices），全量 514 passed。
> 2026-09-09 追加（RSS 可达性 + 知乎/雪球改 Cookie 逛）：
> - RSS 探测修复：`_probe_rsshub` 改为多实例 fallback（之前只试 RSSHUB_INSTANCES[0] 导致
>   第一实例不可达就误判整源不可达）；`rsshub.app` 官方实例大陆不可达已移除，
>   换成实测可用实例（pseudoyu/slarker/ktachibana/rssforever）。财联社/华尔街见闻恢复可达。
> - 知乎/雪球从 RSS 改 Cookie 访问（与微博/小红书一致，"访问即阅读"）：kind=cookie、
>   playable=True、cookie_keys（知乎 z_c0/d_c0；雪球 xq_a_token/xq_r_token/u）；
>   `_probe_cookie` 加端点（知乎 api/v4/me 200；雪球 hot listV2 需 JSON Content-Type）；
>   playwright_collector 加 `_zhihu_hot_items`/`_xueqiu_hot_items`；
>   状态机逛状态泛化（config.browse_state_to_platform），新增逛知乎/逛雪球状态；
>   Cookie 待办生成器自动覆盖知乎/雪球（无 Cookie 时向用户询问，回复回调落库+重探测）。
> - 全量 526 passed（+12 新测试）。
> 2026-09-09 追加（面板无滚动条）：
> - 默认每页 5 条（后端 `list_notices` 默认 page_size 10→5；前端 `_NOTICES_PAGE_SIZE` 同步），
>   面板不出现纵向滚动条（列表不再 max-height+overflow-y，随内容自适应高度，分页兜底）。
> - 长内容自适应：`.agent-notice-content`/`.agent-notice-replied`/`.agent-notice-result`/
>   `.agent-notice-title` 加 `overflow-wrap: anywhere` + 卡片/容器 `min-width: 0`，
>   长 Cookie 串自动换行，消除横向滚动条。

---

## 使用说明

1. 在 `open/` 下按 `REQ_TEMPLATE.md` 模板创建新需求文件
2. 在本文件的需求列表中新增对应条目
3. 自动化任务执行时自动读取 `open/` 中的需求并纳入工作范围
4. 需求状态变迁: OPEN → IN_PROGRESS (自动化任务自动推进) → IMPLEMENTED (代码已写) → CLOSED (测试通过+用户确认)
   - ADOPTED: 需求被采纳但无需代码实现（如流程改进）
   - REJECTED: 任何阶段均可拒绝
5. **实施必须走 superpowers 流程**（见 REQ_TEMPLATE.md）：brainstorming → writing-plans → TDD → executing-plans → code-review
6. 缺少测试的需求不得推进到 CLOSED，最高停留在 IMPLEMENTED
