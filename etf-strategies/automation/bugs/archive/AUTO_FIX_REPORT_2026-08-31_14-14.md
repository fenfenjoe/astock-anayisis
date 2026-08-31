# 自动修复报告 — 2026-08-31 14:14

## 本轮扫描
- 扫描时间: 2026-08-31T14:14:04+08:00
- 发现 OPEN BUG: 8 个
- AUTO_FIX 候选: 4 个（BUG-008/009/010/011）
- MANUAL_REVIEW 候选: 4 个（BUG-012/013/014/015）

## 自动修复结果

| BUG-ID | 标题 | 结果 | 详情 |
|--------|------|------|------|
| BUG-008 | 5 个 cache parquet 缓存过期 | ✅ FIXED | 走东财 push2his（em_get 限流）重拉 5 标的日K写回 parquet：002142/159227/159326/512100/601398 最后数据日期均更新至 2026-08-31，全部 18 个缓存 mtime=2026-08-31，DAT-001 新鲜度达标 |
| BUG-009 | conftest 测试隔离缺陷（setdefault 无法覆盖继承 DB_MODE=memory） | ✅ FIXED | `tests/conftest.py` 改为强制赋值 `os.environ["DB_MODE"]="file"`，测试进程在任何宿主环境下均为文件模式，无 memory 快照回传/TOS 污染/挂起 |
| BUG-010 | conftest 预置 CLOUD_RESTORE_ON_START=0 破坏 test_load_env 断言 | ✅ FIXED | 采用建议方案 (b)：CLOUD_RESTORE_ON_START 改强制赋值 "0"（维持隔离防护断言），test_load_env 先 delenv 再验证 .env 加载语义（方案 (a) 在宿主 =1 环境下会使防护断言失效，故弃用） |
| BUG-011 | 硬编码回测窗口 end=2026-07-01 过时 | ✅ FIXED | run_backtest.py `END`/报告 data_end、backtest/data.py `get_kline` 默认 end 改动态 `date.today()`；strategy_kb.py(13处)/dashboard/sync.py(13处) window 元数据 + db.py 注释示例刷新至 2026-08-31 |

## 升级到人工审核

| BUG-ID | 标题 | 原因 |
|--------|------|------|
| BUG-012 | S8 三因子未归一化即加权（效率因子占 84.3%） | 策略打分公式（auto_fix_eligible=false） |
| BUG-013 | S12 KB"放量下跌自动切货币"未实现（仅 0.3 分惩罚） | 避险信号策略行为设计决策（auto_fix_eligible=false） |
| BUG-014 | S12/S13 KB 因子口径与实现不符（年化收益/成交量因子） | 因子口径决策（auto_fix_eligible=false） |
| BUG-015 | S9/S13 KB 资产池数量标注不符（6只 vs 实列5只） | KB 文档口径修订（auto_fix_eligible=false） |

## 测试验证

- 定向（BUG-009/010 相关）: `tests/test_load_env.py + tests/test_test_isolation.py` → **8 passed**
- 策略/回测/引擎/指标: `pytest -k "backtest or strategies or engine or metrics"` → **114 passed**
- 全量回归（第 1 轮）: 403 passed, 1 failed（`test_daily_review_sync.py::test_upload_changed_file_reupload`，mtime 守卫时序 flake，与本轮修复无关——该测试隔离运行 7/7 通过，未触碰 scheduler.py），2 skipped（网络）
- 全量回归（第 2 轮复跑）: **405 passed, 1 skipped, 0 failed** — 确认 flake，本轮修复全部通过

## 执行日志
- 2026-08-31T14:08+08:00 扫描到 8 个 OPEN BUG
- 2026-08-31T14:08+08:00 BUG-008: auto_fix → 修复成功 → FIXED
- 2026-08-31T14:12+08:00 BUG-009: auto_fix → 修复成功 → FIXED
- 2026-08-31T14:12+08:00 BUG-010: auto_fix → 修复成功 → FIXED
- 2026-08-31T14:13+08:00 BUG-011: auto_fix → 修复成功 → FIXED
- 2026-08-31T14:15+08:00 BUG-012: manual_review → MANUAL_REVIEW
- 2026-08-31T14:15+08:00 BUG-013: manual_review → MANUAL_REVIEW
- 2026-08-31T14:15+08:00 BUG-014: manual_review → MANUAL_REVIEW
- 2026-08-31T14:15+08:00 BUG-015: manual_review → MANUAL_REVIEW
- 2026-08-31T14:16+08:00 更新 BUG_INDEX.md 完成（OPEN: 8→0, FIXED: 3→7, MANUAL_REVIEW: 2→6）
- 2026-08-31T14:16+08:00 修复报告: AUTO_FIX_REPORT_2026-08-31_14-14.md
