# Harness BUG 索引

> 由 harness_bug_auto_fix 和测试发现流程维护。
> 状态: OPEN | IN_PROGRESS | FIXED | VERIFIED | WONT_FIX | DUPLICATE | MANUAL_REVIEW

---

## 统计

| 状态 | 数量 |
|------|------|
| OPEN | 7 |
| IN_PROGRESS | 0 |
| FIXED | 12 |
| VERIFIED | 0 |
| WONT_FIX | 1 |
| MANUAL_REVIEW | 0 |

---

## ✅ 待人工审核 (MANUAL_REVIEW)

> 待人工审核 BUG：BUG-022（P1 关注列表通信标 516880 实为光伏ETF银华非通信ETF，SIG-07-盘中 基于错误标的口径构建）、BUG-023（P1 复盘未完成：evening_review 17:07 仍 in_progress → 归档缺失+复盘报告缺失+信号收益追踪未填充+次日 staging 未刷新）、BUG-017（push2/push2his 连续 ≥2 交易日不可达 + 北向断供，数据源降级）、BUG-018（复盘报告 C3 章节关键词漂移复发：做T建议复盘/次日核心关注；9/2 报告已对齐 C3、逻辑巡检验证 PASS 待确认关闭）、BUG-019（早盘自动任务未运行/盘中检查点缺失，调度器运行环境问题）、BUG-020（1.3c Staging 持仓校验解析器误报，需人工限定表头/区域，参照 BUG-004 模式）、BUG-021（159227 成本 2.731 未复权致浮盈 -62.3% 失真，需人工核实复权成本）。全部历史 MANUAL_REVIEW（BUG-007/008/009/011/016）已于 2026-09-01 核查并关闭（FIXED）。

---

## BUG 列表

<!-- BUG_TABLE_START -->
| BUG-001 | P3 | ~~每日调仓.md 当前持仓表与 config 冲突~~（误报，两文件一致） | 2026-08-18 | 复盘验证 | WONT_FIX | config/持仓.md | 误用早盘旧 config（5标的含纳指），实际两文件一致（4标的无纳指）；config 8/18 15:23 已更新 |
| BUG-002 | P2 | 归档检查失败：归档机制自 8/25 退化"仅写归档说明.md"，A1/A2 仍按旧文件名 | 2026-08-26 | 逻辑巡检 | FIXED | auto_evening_review.md 11.0 | 先覆盖后归档致原件丢失；已恢复"先归档后生成"流程（用户确认 1A） |
| BUG-003 | P2 | 复盘报告缺「做T建议复盘/核心回顾/操作预案」章节（结构漂移） | 2026-08-26 | 逻辑巡检 | FIXED | auto_logic_inspect.md C3 | 报告章节命名被替代；C3 已适配新命名并实测 PASS（用户确认 2B） |
| BUG-004 | P2 | D1 持仓解析失败：每日调仓.md 表格前"持仓："说明行致正则失配 | 2026-08-26 | 逻辑巡检 | FIXED | 每日调仓.md + D1 脚本 | 格式漂移，解析失败（内容实际一致）；解析正则已容忍标题与表格间非表格行（D1+复盘模板 4.5） |
| BUG-005 | P1 | D4 信号模型一致性检查脚本失效：CHECK_TARGETS 解包错误 | 2026-08-26 | 逻辑巡检 | FIXED | auto_logic_inspect.md D4 | lib 升三元组、prompt 未同步 |
| BUG-006 | P3 | E2 BUG_INDEX 统计口径误报：closed 目录 WONT_FIX 被误计 FIXED | 2026-08-26 | 逻辑巡检 | FIXED | auto_logic_inspect.md E2 | 按目录文件数而非状态字段统计；E2 已改为按文件内 **状态**: 字段计数（OPEN/IN_PROGRESS/FIXED/WONT_FIX 分别统计），实测 E2:PASS，回归 208 passed |
| BUG-007 | P1 | B4 报 STALE — staging mtime 早于 evening_review 完成时间（疑似检查逻辑误报） | 2026-08-27 | 逻辑巡检 | FIXED | staging_verify.py / task_state.json | 判定为检查逻辑误报（staging 由复盘第 11 步写入必然早于 completed_at）；**2026-09-01 修复：check_review_staging 时间基准 completed_at→executed_at + 第十五步显式写 staging_generated=true；新增 2 回归测试；用户确认关闭** |
| BUG-008 | P2 | C1 早盘报告检查关键词漂移：「前次预测回顾/海外市场传导」vs 检查「上期预判回顾/事件验证」 | 2026-08-27 | 逻辑巡检 | FIXED | auto_logic_inspect.md C1 | 报告结构与 auto_morning_analysis.md 12 模块一致，检查脚本关键词未同步；8/28 连续复现；8/31 第三次复现（同 2 处 MISSING），修复优先级上调；**2026-09-01 REQ-004 已同步 C1 关键词为新 9 节结构（前次预测回顾/海外市场传导/宏观研判/资金面与情绪/板块机会扫描/持仓映射/风险提示），漂移修复；用户确认关闭（test_report_structure.py 回归通过）** |
| BUG-009 | P2 | C3 复盘报告检查关键词漂移：「次日核心关注」vs 检查「次日核心变量」 | 2026-08-27 | 逻辑巡检 | FIXED | auto_logic_inspect.md C3 | 8/26 BUG-003 修复后再次漂移，报告/模板/检查三处命名不一致；8/28 复现（「8/31 核心变量」）；8/31 第三次复现扩大到 3 处 MISSING（早盘预判复盘/做T预判复盘/次日核心变量），修复优先级上调；**2026-09-01 REQ-004 已同步 C3 关键词（早盘预测回顾/做T建议复盘/次日核心关注），漂移修复；用户确认关闭（test_report_structure.py 回归通过）** |
| BUG-010 | P2 | auto_logic_inspect 检查脚本缺陷：C1/C2/C3 引号语法错误 + C4/D2 缺 UTF-8 致 Windows 无法运行 | 2026-08-27 | 逻辑巡检 | FIXED | auto_logic_inspect.md C1-C4/D2 | 已修复（auto_fix）：C1/C2/C3 `f = 'f'my_doc/...''` → f-string；C4/D2 `python -c` → `python -X utf8 -c`；新增回归测试 test_logic_inspect_scripts.py；回归 211 passed（1 环境性失败与修复无关，修复前已复现） |
| BUG-011 | P2 | B2 核心变量误报：check_lessons_and_vars 裸关键词 split 被正文命中 | 2026-08-28 | 逻辑巡检 | FIXED | lib/staging_verify.py check_lessons_and_vars | 检查器缺陷（裸关键词切分 + 正则不识别 🔑 前缀）；**2026-09-01 修复：_section_after 标题行定位 + 变量计数正则支持 `- 🔑 **`；新增 3 回归测试，真实 staging 复测 PASS；用户确认关闭** |
| BUG-012 | P1 | parse_signal_markdown 无法解析带 markdown 加粗的状态列（**已触发**），8.6.1 入库解析 0 条 | 2026-08-31 | 复盘验证 | FIXED | lib/signal_tracking.py | 盘中信号状态列加粗与 _TRACKABLE_STATUSES 不匹配；已剥离 ** 标记 + 3 单测，回归 214 passed（1 环境性失败无关） |
| BUG-016 | P1 | 复盘读取过期持仓/调仓：dashboard TOS 云端模式只写云端，本地文件不更新 | 2026-08-31 | 复盘验证 | FIXED | dashboard/portfolio.py + 复盘/早盘/盘中/周报 prompts | 修复已实施（pull_holdings_to_local + sync_holdings_cloud.py + prompts 第零步）；**2026-09-01 复核：sync 实跑 PULLED、4 prompt 均含第零步、8/31 错误产出已修正（复盘/每日信号/9-1 staging/signal_tracking 状态 executed/经验教训移除）、现金口径用户确认 37,629；etf 407 + harness 274 测试通过；用户确认关闭** |
| BUG-017 | P2 | push2/push2his 连续 ≥2 交易日不可达 + 北向断供，行业/题材板块扫描与资金面数据降级 | 2026-09-01 | 复盘验证 | OPEN | config/probe_status.json + auto_evening_review 第五步 | 探测 partial(6/7)：push2/push2his fail（8/31+9/1 连续）、北向 hsgt 陈旧快照；行业/题材板块 OHLC/资金流降级；auto_fix_eligible=false（MANUAL_REVIEW 由人工判断网络/代码）；**2026-09-02 第3交易日复现（探测 all_ok 但实际调用被拒，已追加处理记录）**；**2026-09-09 第8交易日复现：探测 partial(5/7) push2/push2his fail，板块数据用 push2delay 镜像（可用，概念板块返回受限 88/400），北向 hsgt 仍为陈旧快照（09:44 非实时）断供持续——已追加处理记录（未新建）** |
| BUG-018 | P2 | 复盘报告 C3 章节关键词漂移复发：「做T建议复盘」实际为「做T预判复盘」且「次日核心关注」章节缺失 | 2026-09-01 | 逻辑巡检 | OPEN | auto_logic_inspect.md C3 + 复盘报告/复盘分析-模板 | 9/1 复盘报告用「5.5 做T预判复盘」且无「次日核心关注」章节，C3 报 2 处 MISSING；与 BUG-003/009 同类漂移复发；auto_fix_eligible=false（MANUAL_REVIEW 需人工定：改检查关键词 or 补模板/报告章节）；**2026-09-02 复盘报告已对齐 C3（新增「4.2 做T建议复盘」+「九、次日核心关注」）；2026-09-02 逻辑巡检验证 C3 PASS（8 章节全命中），待用户确认关闭** |
| BUG-019 | P2 | 09/02 早盘自动任务（07:55）未运行 → 11:20 手动补执行；盘中检查点仅 11:00/13:30 执行，14:45 P0 强制窗口无提醒 | 2026-09-02 | 收盘复盘验证 | OPEN | task_scheduler.py + automation/logs/2026-09-02/ | scheduler 无 09/02 morning_analysis 自动记录（11:17 手动补执行）；当日盘中检查仅 11:00/13:30（logs 缺 0940/1000/1030/1400/1430）→ SIG-01 P0 减仓 14:45 窗口无提醒、用户未执行；auto_fix_eligible=false（需人工确认调度器运行环境） |
| BUG-020 | P2 | 1.3c Staging 持仓校验误报：解析器将板块扫描/做T表等非持仓行误判为持仓 → 每次早盘 [FAIL] 12 errors | 2026-09-03 | 早盘校验执行 | OPEN | auto_morning_analysis.md 1.3c | 宽松条件 len(parts)>=4 抓取 staging 所有含代码行（第五节板块扫描/6.2 做T表），真实持仓表（第一节）与 config 一致却误报 STALE/MISMATCH；auto_fix_eligible=false（需人工改 1.3c 解析：表头/区域限定，参照 BUG-004 模式） |
| BUG-021 | P2 | 航空航天ETF(159227) 成本 2.731 未复权，浮亏 -62.3% 失真（持续 ≥3 周未修正） | 2026-09-03 | 复盘验证 | OPEN | config/持仓.md + 每日调仓.md | 成本基准与现价（1.03 元）不同基准（份额调整/除权未处理）；8 月中旬起仅报告标注"持续已知异常"未建单，本单正式登记；auto_fix_eligible=false（MANUAL_REVIEW 需人工核实复权成本）；**2026-09-09 复现：成本 2.731 仍未复权（现价 1.06 元，浮盈口径失真），报告仅标注不以此决策，待人工核实** |
| BUG-022 | P1 | 关注列表通信标代码错误：516880 实为光伏ETF银华（非通信ETF）→ SIG-07-盘中 基于错误标的口径构建 | 2026-09-07 | 盘中检查(11:00) | OPEN | 早盘报告关注列表 + 每日信号 SIG-07-盘中 | 双源验证（腾讯/新浪）516880=光伏ETF银华；正确通信ETF 515880(+3.91%放量19亿)/515050(+4.36%)；SIG-07 触发条件（0.70前高）基于光伏 ETF 口径→不触发待人工修正/取消；auto_fix_eligible=false（MANUAL_REVIEW 需人工重校准或取消） |
| BUG-023 | P1 | 复盘未完成（evening_review 17:07 仍 in_progress）→ 归档缺失(A1/A2) + 复盘报告缺失(C3) + 信号收益追踪未填充(C2) | 2026-09-08 | 逻辑巡检 | OPEN | task_state.json + archive/20260908 + reports/20260908/复盘报告.md + staging | 17:07 巡检 evening_review 仍 in_progress（started 15:53:47，completed_at 残留 9/7 时间戳）→ 归档目录/复盘报告/信号收益追踪/次日 staging 四项产物缺失 → A1/A2/C2/C3 连锁 FAIL；auto_fix_eligible=false（MANUAL_REVIEW 需人工确认复盘实际执行情况并补产物）；**2026-09-09 确认：9/8 复盘已人工补完成（归档 archive/20260908 + 复盘报告 reports/20260908 + 信号收益追踪 + 次日 staging 全部产出），今日 9/9 复盘全流程（Step 0-17）正常执行无中断，本 BUG 场景未复现，待用户确认关闭** |
<!-- BUG_TABLE_END -->

---

## 巡检历史

| 日期 | 发现方式 | 新增 | 修复 | 仍开放 |
|------|---------|------|------|--------|
| 2026-07-27 | 初始化 | 0 | 0 | 0 |
| 2026-08-18 | 复盘验证 | 1 | 1(误报关闭) | 0 |
| 2026-08-26 | 逻辑巡检 | 5 | 0 | 5 |
| 2026-08-26 | auto_fix(BUG-005) | 0 | 1 | 4 |
| 2026-08-26 | 人工确认(1A/2B/3) | 0 | 2 | 2(BUG-004/006) |
| 2026-08-26 | auto_fix(BUG-004) | 0 | 1 | 1(BUG-006) |
| 2026-08-27 | auto_fix(BUG-006) | 0 | 1 | 0 |
| 2026-08-27 | 逻辑巡检 | 3 | 0 | 3(BUG-007/008/009, 均 MANUAL_REVIEW) |
| 2026-08-27 | 逻辑巡检(补记脚本缺陷) | 1 | 0 | 4(BUG-007/008/009 MANUAL_REVIEW + BUG-010 OPEN) |
| 2026-08-27 | auto_fix(BUG-010) | 0 | 1 | 3(BUG-007/008/009, 均 MANUAL_REVIEW) |
| 2026-08-28 | 逻辑巡检 | 1 | 0 | 4(BUG-007/008/009 复现确认误报/漂移 + BUG-011 MANUAL_REVIEW) |
| 2026-08-31 | 复盘验证 | 1 | 1 | 4(BUG-007/008/009/011 MANUAL_REVIEW) |
| 2026-08-31 | 逻辑巡检 | 0 | 0 | 4(BUG-007/008/009/011 第三次复现确认漂移/缺陷, 无新建) |
| 2026-09-01 | 用户确认(REQ-004) | 0 | 2(BUG-008/009 关键词已同步, FIXED) | 3(BUG-007/011/016 MANUAL_REVIEW) |
| 2026-09-01 | 用户要求核查并修复 | 0 | 3(BUG-007 时间基准/011 变量计数/016 复核确认, 均 FIXED) | 0（全部 BUG 关闭） |
| 2026-09-01 | 收盘复盘验证 | 1 | 0 | 1(BUG-017 数据源降级, MANUAL_REVIEW) |
| 2026-09-01 | 逻辑巡检 | 1 | 0 | 2(BUG-017/018) |
| 2026-09-02 | 早盘验证 | 0 | 0 | 2(BUG-017 第3交易日复现已追加处理记录/018) |
| 2026-09-02 | 收盘复盘验证 | 1 | 0 | 3(BUG-017 晚间复现再追加/018 报告已对齐待验证/019 早盘任务未运行) |
| 2026-09-02 | 逻辑巡检 | 0 | 0 | 3(BUG-017/018 C3 验证 PASS 待用户确认/019) |
| 2026-09-03 | 早盘验证 | 1 | 0 | 4(BUG-017 第4交易日复现/018 待确认/019 9/3 早盘已正常运行/020 新建) |
| 2026-09-03 | 收盘复盘验证 | 1 | 0 | 5(BUG-017 晚间复现 push2delay 可用/018/019 未复现/020/021 新建) |
| 2026-09-07 | 盘中检查(11:00) | 1 | 0 | 6(BUG-017/018/019/020/021 沿用 + BUG-022 新建：关注列表通信标代码错误 516880=光伏ETF银华) |
| 2026-09-08 | 早盘分析 | 0 | 0 | 6(BUG-017/018/019/020/021/022 沿用；BUG-017 push2/push2his 第7交易日复现、BUG-019 早盘运行中断第3次复现、BUG-020 1.3c 误报复现——均按 6.5.2 去重规则追加处理记录，未新建) |
| 2026-09-08 | 逻辑巡检 | 1 | 0 | 7(BUG-017/018/019/020/021/022 沿用 + BUG-023 新建：复盘未完成 evening_review 17:07 仍 in_progress → 归档缺失(A1/A2)+复盘报告缺失(C3)+信号收益追踪未填充(C2)，四项产物连锁缺失) |
| 2026-09-08 | 收盘复盘验证 | 0 | 0 | 7(BUG-017 晚间第7交易日复现已追加处理记录（push2delay 镜像可用）；BUG-023 四项产物已补齐（人工续跑 evening_review 18:1x 完成归档/复盘报告/信号收益追踪/次日 staging），待第十五步状态回写后确认；BUG-018/019/020/021/022 沿用) |
| 2026-09-09 | 收盘复盘验证 | 0 | 0 | 7(BUG-017 第8交易日复现（push2delay 镜像可用，北向断供持续）；BUG-021 成本未复权复现；BUG-023 9/9 全流程正常执行未复现（待用户确认关闭）；BUG-018/019/020/022 沿用；P0 执行率连续 2 日 0% 触发 P1 告警——REQ-007 机制预期输出，追加 REQ-010 新建（显式放弃确认交互）) |

---

## 修复分支索引

| BUG ID | 分支名 | 状态 | 合并日期 |
|--------|--------|------|---------|
| - | - | - | - |
