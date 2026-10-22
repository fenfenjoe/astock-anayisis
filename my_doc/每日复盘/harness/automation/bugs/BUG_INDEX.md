# Harness BUG 索引

> 由 harness_bug_auto_fix 和测试发现流程维护。
> 状态: OPEN | IN_PROGRESS | FIXED | VERIFIED | WONT_FIX | DUPLICATE | MANUAL_REVIEW
>
> ⚠️ **2026-10-16 工作区镜像**（逻辑巡检生成）：规范文件位于
> `D:\Users\dongyz8\.dsh\workspace\xiaoman\harness\automation\bugs\BUG_INDEX.md`（会话沙箱禁止写入）。
> 本镜像 = 规范文件 + 2026-10-16 巡检更新（新增 BUG-041/042 + BUG-036 复发重开 + 巡检历史行），
> 供同步回规范位置合并。

---

## 统计

| 状态 | 数量 |
|------|------|
| OPEN | 21 |
| IN_PROGRESS | 0 |
| FIXED | 15 |
| VERIFIED | 0 |
| WONT_FIX | 2 |
| MANUAL_REVIEW | 0 |

> 口径说明（2026-10-16 更新）：OPEN 18→21（新增 BUG-041 C2 补生成缺章节、BUG-042 D3 孤立信号；BUG-036 D4 复发 FIXED→OPEN），FIXED 16→15（BUG-036 重开减计）。

---

## ✅ 待人工审核 (MANUAL_REVIEW)

> 待人工审核 BUG：BUG-022、BUG-023（P1 复盘未完成，第 6 次复现：10-15 中断状态滞留 + 10-16 未启动）、BUG-024、BUG-017、BUG-018、BUG-019、BUG-020、BUG-025、BUG-026、BUG-027、BUG-028、**BUG-041**（P2 每日信号.md 补生成缺 3 节：信号与早盘报告对照/信号评价/当日信号统计）、**BUG-042**（P2 signal_tracking 4 个 09-15 信号 open 超 30 天未结算）。~~BUG-021~~ 已用户确认 WONT_FIX。

---

## BUG 列表

<!-- BUG_TABLE_START -->
| BUG-001 | P3 | ~~每日调仓.md 当前持仓表与 config 冲突~~（误报，两文件一致） | 2026-08-18 | 复盘验证 | WONT_FIX | config/持仓.md | 误用早盘旧 config |
| BUG-002 | P2 | 归档检查失败：归档机制退化 | 2026-08-26 | 逻辑巡检 | FIXED | auto_evening_review.md 11.0 | 已恢复"先归档后生成"流程 |
| BUG-003 | P2 | 复盘报告缺章节（结构漂移） | 2026-08-26 | 逻辑巡检 | FIXED | auto_logic_inspect.md C3 | C3 已适配新命名 |
| BUG-004 | P2 | D1 持仓解析失败 | 2026-08-26 | 逻辑巡检 | FIXED | 每日调仓.md + D1 脚本 | 正则已容忍非表格行 |
| BUG-005 | P1 | D4 检查脚本失效（CHECK_TARGETS 解包错误） | 2026-08-26 | 逻辑巡检 | FIXED | auto_logic_inspect.md D4 | lib 升三元组 |
| BUG-006 | P3 | E2 统计口径误报 | 2026-08-26 | 逻辑巡检 | FIXED | auto_logic_inspect.md E2 | 已按状态字段计数 |
| BUG-007 | P1 | B4 报 STALE（疑似检查误报） | 2026-08-27 | 逻辑巡检 | FIXED | staging_verify.py | check_review_staging 基准修正 |
| BUG-008 | P2 | C1 早盘报告检查关键词漂移 | 2026-08-27 | 逻辑巡检 | FIXED | auto_logic_inspect.md C1 | REQ-004 同步新 9 节结构 |
| BUG-009 | P2 | C3 复盘报告检查关键词漂移 | 2026-08-27 | 逻辑巡检 | FIXED | auto_logic_inspect.md C3 | REQ-004 同步关键词 |
| BUG-010 | P2 | 检查脚本缺陷（引号/UTF-8） | 2026-08-27 | 逻辑巡检 | FIXED | auto_logic_inspect.md | 已修复 |
| BUG-011 | P2 | B2 核心变量误报 | 2026-08-28 | 逻辑巡检 | FIXED | lib/staging_verify.py | 标题行定位+正则支持🔑 |
| BUG-012 | P2 | 信号状态列 markdown 加粗致解析 0 条 | 2026-08-31 | 盘中检查 | FIXED | lib | 解析器剥离 markdown |
| BUG-016 | P2 | 复盘报告结构漂移 | 2026-08-26 | 复盘验证 | FIXED | 复盘模板 | 已修复 |
| BUG-017 | P1 | push2/push2his 连续不可达 + 北向断供 | 2026-08-29 | 早盘分析 | OPEN | a-stock-data | 数据源降级（42+ 交易日持续） |
| BUG-018 | P2 | 复盘报告 C3 章节关键词漂移复发 | 2026-09-01 | 逻辑巡检 | OPEN | auto_logic_inspect.md C3 | 模板与 C3 关键词长期不同步 |
| BUG-019 | P1 | 早盘自动任务未运行/盘中检查点缺失 | 2026-09-02 | 早盘分析 | OPEN | 调度器 | 调度运行环境问题 |
| BUG-020 | P2 | 1.3c Staging 持仓校验解析器误报 | 2026-09-05 | 早盘分析 | OPEN | staging_verify.py | 需人工限定表头/区域 |
| BUG-021 | P3 | ~~成本未复权误判~~ | 2026-09-08 | 逻辑巡检 | WONT_FIX | config/持仓.md | 2026-10-14 用户确认误报关闭 |
| BUG-022 | P1 | 关注列表通信标 516880 实为光伏ETF | 2026-09-08 | 盘中检查 | OPEN | 关注列表 | 错误标的口径 |
| BUG-023 | P1 | 复盘未完成 → 归档/复盘报告缺失 | 2026-09-08 | 逻辑巡检 | OPEN | evening_review | 第 6 次复现（10-16） |
| BUG-024 | P2 | 盘中主力资金流口径不一致 | 2026-09-09 | 盘中检查 | OPEN | fflow | f51 累计值误求和 |
| BUG-025 | P2 | 板块宇宙 pz 截断致广度/排名失真 | 2026-09-10 | 收盘复盘 | OPEN | 板块扫描 | 需修复 |
| BUG-026 | P2 | OpenViking 周配额耗尽 429 | 2026-09-10 | 复盘 | OPEN | OpenViking | 经验注入降级 |
| BUG-027 | P2 | 东财 fflow secid 前缀遗漏 | 2026-09-10 | 收盘复盘 | OPEN | fflow | 沪市 ETF 资金流为空 |
| BUG-028 | P2 | 盘前板块实时快照字段全量重置 | 2026-09-14 | 早盘分析 | OPEN | 板块扫描 | 静默降级 |
| BUG-029 | P2 | 信号入库解析问题 | 2026-09-15 | 复盘验证 | OPEN | lib | — |
| BUG-030 | P2 | 复盘 staging 验证日期周五失效 | 2026-09-16 | 复盘验证 | OPEN | staging_verify | 交易日感知 |
| BUG-031 | P3 | （closed 归档） | 2026-09-17 | — | FIXED | — | — |
| BUG-032 | P2 | C2 检查脚本历史漂移 | 2026-09-16 | 逻辑巡检 | OPEN | auto_logic_inspect.md C2 | 移除信号收益追踪检查 |
| BUG-033 | P2 | 每日信号.md 状态列注解致解析失败 | 2026-09-18 | 盘中检查 | OPEN | 信号表 | 状态列标准词元 |
| BUG-034 | P3 | 进化周报 HTML 校验大小写误报 | 2026-10-02 | 进化周报 | FIXED | auto_evolution_weekly.md | 已修复 |
| BUG-035 | P2 | 盘中检查市场快照数据源降级 | 2026-10-08 | 盘中检查 | OPEN | 数据源 | — |
| BUG-036 | P3 | D4 SKILL.md 缺交易价/止损价（复发） | 2026-09-22 | 逻辑巡检 | OPEN | SKILL.md | 10-08 修复未持久，10-16 复发 |
| BUG-037 | P3 | BUG_INDEX 统计数与实际不符 | 2026-10-10 | 逻辑巡检 | FIXED | BUG_INDEX.md | 已修复 |
| BUG-038 | P2 | （其他） | 2026-10-12 | — | OPEN | — | — |
| BUG-039 | P2 | 每日信号.md 缺信号与早盘报告对照 | 2026-10-12 | 逻辑巡检 | OPEN | 每日信号.md | 章节回归缺失 |
| BUG-040 | P3 | test_REQ_016 真实日历测试失败 | 2026-10-14 | 回归测试 | FIXED | tests | 已修复 |
| BUG-041 | P2 | 每日信号.md 补生成缺 3 节（对照/评价/统计） | 2026-10-16 | 逻辑巡检 | OPEN | 每日信号.md | 补生成流程漏节 |
| BUG-042 | P2 | signal_tracking 4 个信号 open 超 30 天 | 2026-10-16 | 逻辑巡检 | OPEN | signal_tracking.json | 09-15 信号未结算 |
<!-- BUG_TABLE_END -->

---

## 巡检历史

| 日期 | 来源 | 新增 | 修复 | 摘要 |
|------|------|:---:|:---:|------|
| 2026-10-15 | 逻辑巡检 | 0 | 1 | 21(A1/A2 FAIL + C3 FAIL（BUG-023 第5次复现：进程死亡+锁 stale）→ 已并入 BUG-023；F1 报告新鲜度告警 streak=1 → PENDING #20；B1-B4 PASS；C1/C2 PASS；C4 PASS；D1 PASS/D2 PASS/D3 PASS/D4 PASS；E1 PASS/E2 PASS；新增 BUG 0) |
| 2026-10-16 | 逻辑巡检 | 2 | 0 | 23(A1/A2 FAIL + C3 FAIL（**BUG-023 第6次复现**：10-15 in_progress 状态滞留 + 当日 evening_review 未启动 → archive/20261016/ + reports/20261016/复盘报告.md 缺失，已更新 BUG-023 处理记录）；B1-B4 PASS（staging 章节/代码名称/新鲜度豁免）；C1 PASS；**C2 FAIL → BUG-041 新建**（每日信号.md 补生成缺 信号与早盘报告对照/信号评价/当日信号统计 3 节）；C4 PASS；D1 PASS（7 持仓一致）；D2 WARN（task_state date=20261015 ≠ today，早盘补生成未回写 task_state）；**D3 WARN → BUG-042 新建**（4 个 09-15 信号 open 31 天未结算）；**D4 FAIL → BUG-036 复发**（SKILL.md mtime 09-01 早于 10-08 修复，缺交易价/止损价，FIXED→OPEN）；E1 PASS（经验库无矛盾）；E2 PASS（OPEN=18/FIXED=16/WONT_FIX=2 与规范文件实际一致）；F1 WARN（报告新鲜度 streak=2 → PENDING #21）；新增 BUG 2 个（BUG-041/042），复发重开 1 个（BUG-036），PENDING #21) |
