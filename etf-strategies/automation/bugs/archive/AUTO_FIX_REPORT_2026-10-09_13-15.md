# 自动修复报告 — 2026-10-09 13:15

## 本轮扫描
- 扫描时间: 2026-10-09T13:14:15+08:00
- 发现 OPEN BUG: 3 个（BUG-057 / BUG-058，2026-10-09 12:15 数据巡检发现；BUG-059，2026-10-09 12:27 代码巡检发现，均写入 bugs/open/）
- AUTO_FIX 候选: 2 个（BUG-057 / BUG-058: auto_fix_eligible=true 但受盘中时间约束推迟）
- MANUAL_REVIEW 候选: 1 个（BUG-059: auto_fix_eligible=false → 本轮标记 MANUAL_REVIEW）

## 自动修复结果

| BUG-ID | 标题 | 结果 | 详情 |
|--------|------|------|------|
| BUG-057 | 6/13 活跃 ETF 缓存含 10-08 盘中 partial bar（510300/510500/512010/512480/512660/512800） | ⏸️ DEFERRED（保持 OPEN） | auto_fix_eligible=true 但本报告明确「必须收盘后 ≥15:00 执行，盘中轮不得以 partial 覆盖 partial」（BUG-040/034/026/016 教训，BUG-054 同族第 8 次复发）。本轮 13:07 为盘中轮（13:14 < 15:00），不执行缓存刷新；留待收盘后轮次（≥15:00，如 15:07/16:07 轮）对 6 个 ETF 执行 get_kline(refresh=True, end=2026-10-08) 补全官方收盘 bar（东财不可达时回退腾讯 qfq 日K，REQ-001 已许可）。BUG 报告已追加推迟记录 |
| BUG-058 | 非活跃缓存 512100 缺 10-08 bar + 4 个非活跃 ETF（159227/159326/159992/515880）10-08 partial bar | ⏸️ DEFERRED（保持 OPEN） | auto_fix_eligible=true 但本报告明确「必须收盘后 ≥15:00 执行，盘中轮不得以 partial 覆盖 partial」。本轮 13:07 为盘中轮（13:14 < 15:00），不执行缓存刷新；留待收盘后轮次（≥15:00，如 15:07/16:07 轮）对 512100 补拉 10-08 bar、对 159227/159326/159992/515880（及 WARN 的 002142/601398）重拉官方收盘 bar 覆盖 partial。BUG 报告已追加推迟记录 |
| BUG-059 | pytest 全量通过但退出码=1（Windows asyncio ProactorEventLoop teardown access violation） | ⚠️ MANUAL_REVIEW | auto_fix_eligible=false（环境级处置，可选方案各有副作用需人工裁决）。状态 OPEN → MANUAL_REVIEW，BUG 报告已追加「自动修复判定」章节，保留在 bugs/open/ |

## 升级到人工审核

| BUG-ID | 标题 | 原因 |
|--------|------|------|
| BUG-059 | pytest 全量通过但退出码=1（Windows asyncio ProactorEventLoop teardown access violation） | 测试运行环境处置决策：换 SelectorEventLoop 策略 / 改 TestClient 生命周期 / 升级运行时 / 自动化容忍 exit 1 各有副作用，非机械性确定性修复（auto_fix_eligible=false） |

> 现有 MANUAL_REVIEW 9 项：BUG-005/007/012/013/014/015/038/039（沿用既有判定）+ BUG-059（本轮新增）。均保留在 `bugs/open/`，待人工审阅后执行 bug_fix_template.md 流程。

## 执行日志
- 2026-10-09T13:15+08:00 扫描到 3 个 OPEN BUG（BUG-057 / BUG-058 / BUG-059）
- 2026-10-09T13:15+08:00 BUG-057: auto_fix → ⏸️ 推迟（盘中 13:14 < 15:00，按报告约束禁止 partial 覆盖 partial）→ 保持 OPEN，留待收盘后轮次（≥15:00）；缓存复检 6 ETF 仍含 10-08 盘中 partial bar（510300 close=4.360 vs 官方 4.389，510500 close=7.230 vs 7.279，512010 close=0.385 vs 0.382，512480 close=0.924 vs 0.914，512660 close=1.102 vs 1.095，512800 close=0.857 vs 0.859），与巡检记录一致、未演进
- 2026-10-09T13:15+08:00 BUG-058: auto_fix → ⏸️ 推迟（盘中 13:14 < 15:00，按报告约束禁止 partial 覆盖 partial）→ 保持 OPEN，留待收盘后轮次（≥15:00）；缓存复检 512100 仍止于 09-30（缺 10-08 bar），159992/515880 仍含 10-08 partial（close 0.857/0.614 vs 官方 0.839/0.594），未演进
- 2026-10-09T13:15+08:00 BUG-059: manual_review（auto_fix_eligible=false）→ 状态 OPEN → MANUAL_REVIEW，追加自动修复判定，保留在 bugs/open/
- 2026-10-09T13:15+08:00 更新 BUG_INDEX.md 完成（OPEN 3→2, MANUAL_REVIEW 8→9；BUG-059 列表状态 OPEN→MANUAL_REVIEW 并加入待人工审核表；巡检历史追加「自动修复 0 新 0 修 2 留」）
- 2026-10-09T13:15+08:00 无代码修改/测试运行（本轮无 AUTO_FIX 候选实际执行，2 项推迟 + 1 项标记人工）

## 本轮相关观察
- BUG-057/058 的根因 REQ-001（数据刷新流程防护：收盘门控 + 刷新后 bar 完整性校验）在 steering/open/REQ-001.md 保持 OPEN 未实施，本次为 BUG-040 族第 8 次复发 + BUG-055 同族复发；收盘后轮次完成补拉后，建议优先推进 REQ-001 以根治盘中 partial 写入问题
