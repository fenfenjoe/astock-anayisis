# 自动修复报告 — 2026-08-27 14:11

## 本轮扫描
- 扫描时间: 2026-08-27T14:07+08:00
- 发现 OPEN BUG: 3 个
- AUTO_FIX 候选: 2 个（BUG-004、BUG-006）
- MANUAL_REVIEW 候选: 1 个（BUG-005）

## 自动修复结果

| BUG-ID | 标题 | 结果 | 详情 |
|--------|------|------|------|
| BUG-004 | cache/512100.parquet 缓存过期(2026-07-22,>24h) | ✅ FIXED | `get_kline("512100", refresh=True)` 东财重拉，mtime 更新至 2026-08-27 14:07:59，覆盖至 2026-08-27 |
| BUG-006 | 正确性定义引用的6个测试节点不存在,reporting.py覆盖率0% | ✅ FIXED | 补 5 个专项测试 + reporting.py 4 测试；修正 ENG-001/DAT-002 引用；data.py 补索引去重；reporting 覆盖率 0%→100% |

## 升级到人工审核

| BUG-ID | 标题 | 原因 |
|--------|------|------|
| BUG-005 | 胜率计算分母与正确性定义不符(非零收益天数vs总交易日数) | 指标口径决策（MET-005），涉及计算公式，auto_fix_eligible=false |

## 执行日志
- 2026-08-27T14:07+08:00 扫描到 3 个 OPEN BUG
- 2026-08-27T14:08+08:00 BUG-004: auto_fix → 重拉 512100 缓存成功 → FIXED
- 2026-08-27T14:08+08:00 BUG-005: manual_review → MANUAL_REVIEW
- 2026-08-27T14:10+08:00 BUG-006: auto_fix → 补测试+修正引用+data.py 去重，全量回归 286 passed → FIXED
- 2026-08-27T14:11+08:00 更新 BUG_INDEX.md 完成（OPEN 0 / FIXED 3 / MANUAL_REVIEW 1）
