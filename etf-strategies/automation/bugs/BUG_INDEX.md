# BUG 索引

> 自动生成，由 bug_inspect_code.md、bug_inspect_logic.md、bug_inspect_data.md 和 bug_auto_fix.md 维护。
> 状态: OPEN | IN_PROGRESS | FIXED | VERIFIED | WONT_FIX | DUPLICATE

---

## 统计

| 状态 | 数量 |
|------|------|
| OPEN | 0 |
| IN_PROGRESS | 0 |
| FIXED | 18 |
| VERIFIED | 1 |
| WONT_FIX | 1 |
| MANUAL_REVIEW | 9 |

---

## ⚠️ 待人工审核 (MANUAL_REVIEW)

> 以下 BUG 因涉及计算逻辑/算法正确性/金融公式，需人工审阅决定修复方案。
> 操作: 审阅 `bugs/open/BUG-{NNN}.md`，手动执行 `bug_fix_template.md` 流程修复。

| BUG-ID | 标题 | 原因 |
|--------|------|------|
| BUG-005 | 胜率计算分母与正确性定义不符（非零收益天数 vs 总交易日数） | 指标口径决策（MET-005），auto_fix_eligible=false |
| BUG-007 | ENG-004 换手率定义与实现口径不一致:引擎年化(可>2)vs定义单次调仓(≤2) | 指标口径决策（ENG-004），auto_fix_eligible=false |
| BUG-012 | S8 三因子未归一化即加权：效率因子支配得分（实测占84.3%） | 策略打分公式（金融算法），auto_fix_eligible=false |
| BUG-013 | S12 KB"放量下跌自动切货币"未实现：仅0.3分惩罚 | 避险信号策略行为设计决策，auto_fix_eligible=false |
| BUG-014 | S12/S13 KB因子口径与实现不符（年化收益/成交量因子） | 因子口径决策，auto_fix_eligible=false |
| BUG-015 | S9/S13 KB资产池数量标注不符（6只 vs 实列5只） | KB 文档口径修订，auto_fix_eligible=false |
| BUG-025 | 云端集成测试 skipif 只查 env 不查 backend：cloud_db._ENABLED 模块级常量导入时序 + 门控不严，全量 11 项 FAILED/ERROR | 需设计决策（懒加载 enabled()/skipif 增强），云端迁移 WIP 未提交，auto_fix_eligible=false |
| BUG-029 | pet.js 引用已移除的场景层挂载点 xm-pet-scene，dashboard.html 无该元素（前端契约断裂） | 前端契约决策（移除死引用 vs 恢复挂载点），auto_fix_eligible=false |
| BUG-030 | pet.css 桌宠状态/姿态样式覆盖不完整：缺 data-state="working" 与全部 data-posture 规则 | 视觉设计决策 + posture 机制去留，auto_fix_eligible=false |

---

## BUG 列表

<!-- BUG 条目由自动巡检脚本追加在下方 -->

<!-- BUG_TABLE_START -->
| BUG-001 | Dashboard同步测试策略计数不匹配 | tests | MEDIUM | VERIFIED | 2026-07-23 |
| BUG-002 | 3个已注册策略(S14/S15/S16/S17)无专项测试，覆盖率<40% | strategies | MEDIUM | FIXED | 2026-08-10 |
| BUG-003 | 动量家族R²截断不一致:S4/S8未用max(r_sq,0),其余已截断 | strategies | LOW | WONT_FIX | 2026-08-10 |
| BUG-004 | cache/512100.parquet缓存过期(2026-07-22,>24h) | data | MEDIUM | FIXED | 2026-08-27 |
| BUG-005 | 胜率计算分母与正确性定义不符(非零收益天数vs总交易日数) | metrics | MEDIUM | MANUAL_REVIEW | 2026-08-27 |
| BUG-006 | 正确性定义引用的6个测试节点不存在,reporting.py覆盖率0% | tests | MEDIUM | FIXED | 2026-08-27 |
| BUG-007 | ENG-004 换手率定义与实现口径不一致:引擎年化(可>2)vs定义单次调仓(≤2) | engine | MEDIUM | MANUAL_REVIEW | 2026-08-28 |
| BUG-008 | 5个cache parquet缓存过期(002142/159227/159326/512100/601398, mtime>24h) | data | MEDIUM | FIXED | 2026-08-31 |
| BUG-009 | conftest.py测试隔离缺陷:setdefault无法覆盖继承DB_MODE=memory(全量测试大面积失败+挂起+TOS污染风险) | tests | HIGH | FIXED | 2026-08-31 |
| BUG-010 | conftest.py预置CLOUD_RESTORE_ON_START=0破坏test_load_env断言(干净环境必失败) | tests | MEDIUM | FIXED | 2026-08-31 |
| BUG-011 | 硬编码回测窗口end=2026-07-01过时(回测静默缺2026-07~08数据,KB/sync元数据过时) | data | MEDIUM | FIXED | 2026-08-31 |
| BUG-012 | S8三因子未归一化即加权:效率因子支配得分(实测占84.3%),与KB"归一化后加权0.4/0.3/0.3"不符 | strategies | MEDIUM | MANUAL_REVIEW | 2026-08-31 |
| BUG-013 | S12 KB"放量下跌自动切货币"未实现:仅0.3分惩罚,放量下跌日仍满仓(实证货币权重0.0) | strategies | MEDIUM | MANUAL_REVIEW | 2026-08-31 |
| BUG-014 | S12/S13 KB因子口径与实现不符:"年化收益"实为简单收益;"成交量因子"实为价格波幅代理 | strategies | LOW | MANUAL_REVIEW | 2026-08-31 |
| BUG-015 | S9/S13 KB资产池数量标注不符:写"6只/5行业+1宽基"实列5只(4行业+1宽基),代码为5只 | strategies | LOW | MANUAL_REVIEW | 2026-08-31 |
| BUG-016 | 缓存2026-08-31日K为盘中快照:11/18缓存跨源价差>0.5%(9/13活跃ETF受影响,512480偏差-3.59%) | data | HIGH | FIXED | 2026-09-01 |
| BUG-017 | bug_inspect_data第四步脚本对策略类hasattr('assets')恒False,活跃ETF集合恒空,完整性门永久失效 | data | MEDIUM | FIXED | 2026-09-01 |
| BUG-018 | CLI帮助文本/文档字符串仍写「S1-S11」,实际已支持S1-S19(S12-S19遗漏提示) | registration | LOW | FIXED | 2026-09-02 |
| BUG-019 | 11/13活跃ETF缓存09-02日K为盘中快照:缓存mtime落在09-02交易时段,收盘后未重拉覆盖(513100偏差+0.501%) | data | HIGH | FIXED | 2026-09-03 |
| BUG-020 | 5个非活跃cache缓存过期(002142/159227/159326/512100/601398, mtime=09-01, 缺09-01/09-02数据) | data | MEDIUM | FIXED | 2026-09-03 |
| BUG-021 | 5个活跃策略ETF缓存mtime>24h(511880/512010/512480/512660/512800, mtime=09-04未收09-07刷新)+513100刷新未写入今日bar,刷新覆盖不一致 | data | MEDIUM | FIXED | 2026-09-07 |
| BUG-022 | 5个非活跃cache缓存过期复发(002142/159227/159326/512100/601398, mtime=09-03, 缺09-03/09-04数据, BUG-020同集合第3次复发) | data | MEDIUM | FIXED | 2026-09-07 |
| BUG-023 | test_agent_behavior 3个run_post_pipeline测试引用已删除函数(5c6fc61重构移除,execute_reading承接发动态),AttributeError | tests | HIGH | FIXED | 2026-09-07 |
| BUG-024 | test_agent_lifecycle tick测试未适配3bcc9d0上线/下线闸门(未设xiaoman_online=1, Rss断言失败) | tests | HIGH | FIXED | 2026-09-07 |
| BUG-025 | 云端集成测试skipif只查env不查backend:cloud_db._ENABLED模块级常量在.env加载前导入时永久False,全量测试11项FAILED/ERROR | tests | MEDIUM | MANUAL_REVIEW | 2026-09-07 |
| BUG-026 | 9/13活跃ETF缓存09-07 bar为盘中partial快照(非官方收盘),跨源偏差最高+1.17%(159915),BUG-021盘中重拉引入 | data | HIGH | FIXED | 2026-09-08 |
| BUG-029 | pet.js引用已移除场景层挂载点xm-pet-scene,dashboard.html无该元素(前端契约断裂,2测试FAILED) | dashboard | MEDIUM | MANUAL_REVIEW | 2026-09-08 |
| BUG-030 | pet.css桌宠状态/姿态样式覆盖不完整:缺data-state=working与全部data-posture规则(1测试FAILED) | dashboard | MEDIUM | MANUAL_REVIEW | 2026-09-08 |
| BUG-031 | test_scheduler_status fixture未重置agent_online()的_online_cache:测试跨用例缓存污染(顺序相关,2测试FAILED) | tests | MEDIUM | FIXED | 2026-09-08 |
<!-- BUG_TABLE_END -->

---

## 巡检历史

| 日期 | 巡检类型 | 新增 | 修复 | 仍开放 |
|------|---------|------|------|--------|
| 2026-07-23 | 代码巡检 | 1 | 1 | 0 |
| 2026-07-24 | 代码巡检 | 0 | 0 | 0 |
| 2026-07-27 | 代码巡检 | 0 | 0 | 0 |
| 2026-07-27 | 逻辑巡检 | 0 | 0 | 0 |
| 2026-08-07 | 代码巡检 | 0 | 0 | 0 |
| 2026-08-10 | 代码巡检 | 1 | 0 | 1 |
| 2026-08-10 | 逻辑巡检 | 1 | 0 | 2 |
| 2026-08-10 | 自动修复 | 0 | 1 | 1 |
| 2026-08-10 | 人工审阅 | 0 | 1 | 0 |
| 2026-08-27 | 数据巡检 | 1 | 0 | 1 |
| 2026-08-27 | 代码巡检 | 2 | 0 | 3 |
| 2026-08-27 | 自动修复 | 0 | 2 | 1 |
| 2026-08-28 | 数据巡检 | 0 | 0 | 1 |
| 2026-08-28 | 代码巡检 | 1 | 0 | 2 |
| 2026-08-28 | 自动修复 | 0 | 0 | 1 |
| 2026-08-31 | 数据巡检 | 1 | 0 | 3 |
| 2026-08-31 | 代码巡检 | 3 | 0 | 6 |
| 2026-08-31 | 逻辑巡检 | 4 | 0 | 10 |
| 2026-08-31 | 自动修复 | 0 | 4 | 0 |
| 2026-09-01 | 数据巡检 | 2 | 0 | 2 |
| 2026-09-01 | 代码巡检 | 0 | 0 | 2 |
| 2026-09-01 | 自动修复 | 0 | 2 | 0 |
| 2026-09-02 | 数据巡检 | 0 | 0 | 0 |
| 2026-09-02 | 代码巡检 | 1 | 0 | 1 |
| 2026-09-02 | 自动修复 | 0 | 1 | 0 |
| 2026-09-03 | 数据巡检 | 2 | 0 | 2 |
| 2026-09-03 | 代码巡检 | 0 | 0 | 8 |
| 2026-09-03 | 自动修复 | 0 | 2 | 0 |
| 2026-09-07 | 数据巡检 | 2 | 0 | 2 |
| 2026-09-07 | 逻辑巡检 | 0 | 0 | 8 |
| 2026-09-07 | 代码巡检 | 3 | 0 | 11 |
| 2026-09-07 | 自动修复 | 0 | 4 | 0 |
| 2026-09-08 | 数据巡检 | 1 | 1 | 0 |
| 2026-09-08 | 代码巡检 | 3 | 0 | 10 |
| 2026-09-08 | 自动修复 | 0 | 1 | 9 |

---

## 修复分支索引

| BUG ID | 分支名 | 状态 | 合并日期 |
|--------|--------|------|---------|
| - | - | - | - |
