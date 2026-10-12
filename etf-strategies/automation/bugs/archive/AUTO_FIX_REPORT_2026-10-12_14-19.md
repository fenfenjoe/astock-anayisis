# 自动修复报告 — 2026-10-12 14:19

## 本轮扫描
- 扫描时间: 2026-10-12T14:19:21+08:00
- 发现 OPEN BUG: 1 个（BUG-060）
- AUTO_FIX 候选: 1 个（BUG-060: auto_fix_eligible=true，注册遗漏属机械性确定性修复）
- MANUAL_REVIEW 候选: 0 个（bugs/open 下其余 9 项 BUG-005/007/012/013/014/015/038/039/059 均为 MANUAL_REVIEW 且已含自动修复判定，沿用既有判定无新增动作）

## 自动修复结果

| BUG-ID | 标题 | 结果 | 详情 |
|--------|------|------|------|
| BUG-060 | S21 WufuMomentumRotation 未注册进 list_strategies.py STRATEGIES 列表（REG-003） | ✅ FIXED | `list_strategies.py` 补 `from backtest.strategies.wufu_momentum_rotation import WufuMomentumRotation` import + `STRATEGIES` 列表追加 `WufuMomentumRotation`（最小变更 +2 行）。验证：注册一致性检查通过（未注册: 无）；`python list_strategies.py --plain` 输出 21 个策略（原 20，含 S21 五福动量轮动）；目标测试 78 passed（含 4 项 test_wufu_*）；全量回归 782 passed / 17 skipped / 0 failed（exit code 1 为已知 BUG-059 Windows asyncio ProactorEventLoop teardown 环境问题，与本次修复无关）。提交 `7394f3f` |

## 升级到人工审核

| BUG-ID | 标题 | 原因 |
|--------|------|------|
| （无） | - | 本轮无新增 MANUAL_REVIEW |

> 现有 MANUAL_REVIEW 9 项：BUG-005/007/012/013/014/015/038/039/059（沿用既有判定）。均保留在 `bugs/open/`，待人工审阅后执行 bug_fix_template.md 流程。

## 本轮相关观察

- **退出码 1 说明**：全量回归 `782 passed / 17 skipped / 0 failed`，但进程退出码=1 — 这是 **BUG-059 已知的 Windows asyncio ProactorEventLoop teardown access violation**（MANUAL_REVIEW 项，10-09 记录），由 `test_agent_browser_cookies.py` 的 `TestClient(agent_api.app)` asyncio 生命周期触发，**与本次注册类修复无因果关系**（本次仅改 `list_strategies.py` 的 import + STRATEGIES 列表，不触及任何测试执行路径）。
- **缓存纪律**：BUG-060 为注册类修复，不涉及缓存数据，不受「盘中不得修改缓存」纪律限制，盘中可安全执行。
- **影响面**：修复仅作用于策略目录工具 `list_strategies.py`，对回测结果/实盘信号无影响（run_backtest/daily_signal/sync 本已正常注册 S21）；修复后注册一致性巡检（bug_inspect_code 2.2 步）不再报 ERROR。

## 执行日志
- 2026-10-12T14:13+08:00 扫描到 1 个 OPEN BUG（BUG-060，auto_fix_eligible=true）
- 2026-10-12T14:13+08:00 BUG-060: auto_fix → 备份（git 可回滚 + 内存记录）→ 补 import + STRATEGIES 列表条目（+2 行）→ 注册一致性检查通过 + list_strategies --plain 21 个策略 → 目标测试 78 passed → 全量回归 782 passed/17 skipped/0 failed（exit code 1 为已知 BUG-059 环境问题）→ 修复成功 → FIXED
- 2026-10-12T14:19+08:00 提交 `7394f3f`（fix(BUG-060): [auto-fix] 注册 S21 WufuMomentumRotation）
- 2026-10-12T14:19+08:00 BUG-060.md 状态 OPEN→FIXED + 追加自动修复记录，移入 bugs/closed/
- 2026-10-12T14:19+08:00 更新 BUG_INDEX.md 完成（OPEN 1→0, FIXED 46→47；BUG-060 列表状态 OPEN→FIXED；巡检历史追加"自动修复 0 新 1 修 0 留"）
