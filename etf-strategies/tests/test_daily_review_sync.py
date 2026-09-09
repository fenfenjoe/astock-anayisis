"""Tests for dashboard 每日复盘迁移同步 — 信号 v2.0 解析 / 持仓可用金额往返 / 调度范围 / 报告导入.

覆盖 2026-08-27 迁移同步（docs/2026-08-27-每日复盘迁移同步-差距清单.md）修复点：
- D1: api_daily._parse_signals 对齐 12 列 v2.0 信号总表（表头驱动 + 旧格式兜底）
- D3: portfolio 可用金额行 解析/回写保活（防 Dashboard 保存持仓删行）
- D4: scheduler 范围含 signal_quality_weekly
- D5: 报告导入识别 周度组合回顾
- S1/S4: 报告增量重扫（mtime 守卫）+ 调度窗口容差配置化
"""
import sys
from datetime import datetime
from pathlib import Path

import pytest

_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from dashboard import api_daily, portfolio, scheduler  # noqa: E402
from dashboard import scheduler_cli as cli  # noqa: E402


@pytest.fixture(autouse=True)
def _no_cloud():
    """2026-09-07 已移除 TOS：portfolio/scheduler 不再有 _cs_* 云存储，
    本地文件读写即为唯一路径，无需（也无法）monkeypatch 云对象。此 fixture 保留
    为 no-op 占位，便于未来若引入新云层时在此统一隔离。
    """
    yield


# ═══════════════════════════════════════════════════════════════
# D1: 信号总表解析（v2.0 12 列）
# ═══════════════════════════════════════════════════════════════

# 真实 v2.0 样例（取自 reports/20260827/每日信号.md 信号总表，节选 2 行）
V2_SIGNAL_MD = """# 每日信号 — 2026年8月27日（周四）

## 信号总表

| 优先级 | 标的 | 触发条件 | 操作类型 | 状态 | 方向 | 紧急度 | 预期触发率 | 目标/止损 | 有效时段 | 仓位 | 信号ID |
|:---:|------|----------|:------:|:---:|:---:|:---:|:---:|:---:|----------|:---:|--------|
| P0 | 黄金ETF(518880) | 跌破9.20 或 冲高回落+放量流出 → 减仓1/3 | 减仓 | 待执行 | 卖出 | 高 | — | 目标9.60/止损9.0 | 全天 | 1,300份(1/3) | SIG-20260827-01 |
| P1 | 电网设备ETF(159326) | 站上1.70 + 量比>0.8 → 正T | 正T | 已触发 | 买入 | 高 | 35% | 目标+2%(1.717)/止损-1%(1.683) | 10:30-11:30 | 1,975份(1/4) | SIG-20260827-04 |

## 信号触发记录

| 触发时间 | 信号ID | 优先级 | 标的 | 操作类型 | 触发条件摘要 | 当前状态 | 建议操作 | 用户操作 |
|----------|--------|:---:|------|:------:|-------------|:------:|----------|:------:|
| 10:31 | SIG-20260827-04 | P1 | 电网设备ETF(159326) | 正T | 午后路径三条件齐备 | 已触发 | 正T 1,975份 | 待用户填写 |
"""

# 旧 14 列格式（迁移前，用于兜底兼容验证）
V1_SIGNAL_MD = """## 信号总表

| 优先级 | 标的 | 触发条件 | 操作类型 | 状态 | 方向 | 紧急度 | 升级条件 | 预期收益日 | 有效时段 | 仓位 | 操作来源 | 生成依据 | 信号ID |
|--------|------|----------|:------:|:---:|:---:|:---:|----------|-----------|----------|:---:|:------:|----------|--------|
| P0 | 黄金ETF | 跌破守位线 | 减仓 | 待执行 | 卖出 | 高 | 放量 | T+3 | 全天 | 1,300份 | 早盘分析 | 早盘报告P0 | SIG-20260817-01 |
"""


class TestParseSignalsV2:
    def test_parses_v2_columns(self):
        rows = api_daily._parse_signals(V2_SIGNAL_MD)
        assert len(rows) == 2

        r0 = rows[0]
        assert r0["优先级"] == "P0"
        assert r0["标的"] == "黄金ETF(518880)"
        assert r0["操作类型"] == "减仓"
        assert r0["状态"] == "待执行"
        assert r0["方向"] == "卖出"
        assert r0["紧急度"] == "高"
        assert r0["预期触发率"] == "—"          # P0 不考核触发率
        assert "9.60" in r0["目标/止损"]          # v2.0 新列
        assert r0["有效时段"] == "全天"
        assert r0["仓位"] == "1,300份(1/3)"
        assert r0["信号ID"] == "SIG-20260827-01"

        r1 = rows[1]
        assert r1["预期触发率"] == "35%"          # P1 必填百分比
        assert r1["目标/止损"].startswith("目标+2%")
        assert r1["信号ID"] == "SIG-20260827-04"

    def test_no_longer_exposes_v1_columns(self):
        rows = api_daily._parse_signals(V2_SIGNAL_MD)
        # v2.0 不再有 操作来源/生成依据 列
        assert "操作来源" not in rows[0]
        assert "生成依据" not in rows[0]

    def test_v1_format_fallback(self):
        """旧 14 列格式仍可解析（表头驱动，未知列名按位置兜底）。"""
        rows = api_daily._parse_signals(V1_SIGNAL_MD)
        assert len(rows) == 1
        r = rows[0]
        assert r["优先级"] == "P0"
        assert r["标的"] == "黄金ETF"
        assert r["信号ID"] == "SIG-20260817-01"
        # 旧格式的 升级条件 会落到 预期触发率 位置（兜底不硬失败即可）
        assert r["预期触发率"] in ("放量", "")

    def test_missing_section_returns_empty(self):
        assert api_daily._parse_signals("没有信号总表") == []


# ═══════════════════════════════════════════════════════════════
# D3: 持仓.md 可用金额 往返同步
# ═══════════════════════════════════════════════════════════════

HOLDINGS_SAMPLE = """# 当前持仓

> 本文件由每日复盘自动同步自 每日调仓.md，反映最新持仓状态。
> 最后更新: 自动同步
可用金额: 25701 元

| 股票名称 | 代码 | 持仓数量（份） | 成本价（元） |
| -------- | ------ | -------------- | ------------ |
| 黄金ETF | 518880 | 3,900 | 9.056 |
"""


class TestAvailableCashMd:
    def test_parse_available_cash(self):
        assert portfolio.parse_available_cash_md(HOLDINGS_SAMPLE) == 25701.0
        # 千分位兼容
        assert portfolio.parse_available_cash_md("可用金额: 25,701 元") == 25701.0
        # 全角冒号兼容
        assert portfolio.parse_available_cash_md("可用金额：25701 元") == 25701.0
        # 缺失
        assert portfolio.parse_available_cash_md("# 当前持仓\n\n| a | b |") is None

    def test_write_preserves_cash_when_not_provided(self, tmp_path, monkeypatch):
        """未显式传可用金额时，回写必须保留文件中已有行（防删行）。"""
        md = tmp_path / "持仓.md"
        md.write_text(HOLDINGS_SAMPLE, encoding="utf-8")
        monkeypatch.setattr(portfolio, "HOLDINGS_MD", md)
        rows = portfolio.parse_holdings_md(HOLDINGS_SAMPLE)

        portfolio.write_holdings_md(rows)  # available_cash=None

        out = md.read_text(encoding="utf-8")
        assert "可用金额: 25701 元" in out
        assert "| 黄金ETF | 518880 | 3,900 | 9.056 |" in out

    def test_write_with_explicit_cash(self, tmp_path, monkeypatch):
        md = tmp_path / "持仓.md"
        md.write_text(HOLDINGS_SAMPLE, encoding="utf-8")
        monkeypatch.setattr(portfolio, "HOLDINGS_MD", md)
        rows = portfolio.parse_holdings_md(HOLDINGS_SAMPLE)

        portfolio.write_holdings_md(rows, available_cash=12345.6)

        out = md.read_text(encoding="utf-8")
        assert "可用金额: 12346 元" in out  # 四舍五入取整

    def test_write_no_cash_line_when_none_existed(self, tmp_path, monkeypatch):
        md = tmp_path / "持仓.md"
        md.write_text("# 当前持仓\n\n| 股票名称 | 代码 | 持仓数量（份） | 成本价（元） |\n", encoding="utf-8")
        monkeypatch.setattr(portfolio, "HOLDINGS_MD", md)

        portfolio.write_holdings_md([])

        out = md.read_text(encoding="utf-8")
        assert "可用金额" not in out


# ═══════════════════════════════════════════════════════════════
# D4: 调度范围 — signal_quality_weekly 在接管范围内
# ═══════════════════════════════════════════════════════════════

class TestSchedulerScope:
    def test_signal_quality_weekly_in_scope(self):
        tasks = scheduler.scoped_tasks()
        ids = {t["task_id"] for t in tasks}
        assert "signal_quality_weekly" in ids
        assert "morning_analysis" in ids
        assert "evening_review" in ids

    def test_etf_automation_tasks_in_scope(self):
        """2026-08-27 决策：ETF 自动化巡检任务也随 Web 启停（纳入引擎）。"""
        ids = {t["task_id"] for t in scheduler.scoped_tasks()}
        assert "bug_auto_fix" in ids
        assert "bug_inspect_data" in ids
        assert "bug_inspect_code" in ids
        assert "bug_inspect_logic" in ids
        assert "strategy_scan_weekly" in ids

    def test_all_scoped_tasks_have_prompt_file(self):
        for t in scheduler.scoped_tasks():
            assert t.get("prompt_file", "").startswith(scheduler.SCOPE_PREFIXES)


# ═══════════════════════════════════════════════════════════════
# D5: 报告导入 — 类型识别 + 周度组合回顾
# ═══════════════════════════════════════════════════════════════

class TestReportImport:
    @pytest.mark.parametrize("name,expected", [
        ("复盘报告.md", "复盘报告"),
        ("早盘报告.md", "早盘报告"),
        ("早盘机会.md", "早盘机会"),
        ("每日信号.md", "每日信号"),
        ("每日信号-复盘填充版.md", None),   # 影子产物（降级执行），不导入
        ("2026-08-27_周报.md", "周报"),
        ("周度组合回顾.md", "周度组合回顾"),
        ("README.md", None),
    ])
    def test_report_type_from_name(self, name, expected):
        assert scheduler._report_type_from_name(name) == expected

    def test_import_weekly_combined_review(self, tmp_path, monkeypatch):
        """周度组合回顾（日期目录内）可导入。"""
        monkeypatch.setattr(scheduler, "REPORTS_DIR", tmp_path)
        (tmp_path / "20260730").mkdir()
        (tmp_path / "20260730" / "周度组合回顾.md").write_text("# 周度组合回顾", encoding="utf-8")

        from dashboard import db as db_mod
        in_mem = _in_memory_db(monkeypatch)
        db_mod.init_db()

        result = scheduler.import_reports_from_disk()
        assert result["imported"] == 1
        rep = db_mod.report_get("20260730", "周度组合回顾")
        assert rep is not None
        assert "# 周度组合回顾" in rep["markdown"]
        in_mem.close()


# ═══════════════════════════════════════════════════════════════
# S1: 报告增量重扫（mtime 守卫）
# ═══════════════════════════════════════════════════════════════

class TestReportRescanIncremental:
    def _setup(self, tmp_path, monkeypatch):
        from dashboard import db as db_mod
        in_mem = _in_memory_db(monkeypatch)
        db_mod.init_db()
        monkeypatch.setattr(scheduler, "REPORTS_DIR", tmp_path)
        (tmp_path / "20260827").mkdir()
        return tmp_path, db_mod, in_mem

    def test_first_scan_imports_then_second_skips(self, tmp_path, monkeypatch):
        _, db_mod, in_mem = self._setup(tmp_path, monkeypatch)
        f = tmp_path / "20260827" / "每日信号.md"
        f.write_text("# 每日信号 v1", encoding="utf-8")

        assert scheduler.import_reports_from_disk()["imported"] == 1
        assert scheduler.import_reports_from_disk()["imported"] == 0  # mtime 未变，跳过
        in_mem.close()

    def test_changed_file_reimported(self, tmp_path, monkeypatch):
        _, db_mod, in_mem = self._setup(tmp_path, monkeypatch)
        f = tmp_path / "20260827" / "每日信号.md"
        f.write_text("# 每日信号 v1", encoding="utf-8")
        scheduler.import_reports_from_disk()
        assert db_mod.report_get("20260827", "每日信号")["markdown"] == "# 每日信号 v1"

        f.write_text("# 每日信号 v2（盘中更新）", encoding="utf-8")
        assert scheduler.import_reports_from_disk()["imported"] == 1
        assert db_mod.report_get("20260827", "每日信号")["markdown"] == "# 每日信号 v2（盘中更新）"
        in_mem.close()

    def test_force_full_rescan(self, tmp_path, monkeypatch):
        _, db_mod, in_mem = self._setup(tmp_path, monkeypatch)
        f = tmp_path / "20260827" / "每日信号.md"
        f.write_text("# 每日信号", encoding="utf-8")
        scheduler.import_reports_from_disk()
        # force=True 强制全量重读
        assert scheduler.import_reports_from_disk(force=True)["imported"] == 1
        in_mem.close()


# ═══════════════════════════════════════════════════════════════
# S4: 调度窗口容差配置化
# ═══════════════════════════════════════════════════════════════

class TestWindowTolerance:
    TASK = {"task_id": "t", "target_time": "10:00", "window_minutes": 7, "days_of_week": None}

    def test_default_7min_window(self, monkeypatch):
        monkeypatch.setattr(scheduler, "WINDOW_TOLERANCE_MINUTES", None)
        assert scheduler.task_due_now(dict(self.TASK), datetime(2026, 8, 27, 10, 5)) is True
        assert scheduler.task_due_now(dict(self.TASK), datetime(2026, 8, 27, 10, 20)) is False

    def test_env_override_30min(self, monkeypatch):
        monkeypatch.setattr(scheduler, "WINDOW_TOLERANCE_MINUTES", 30)
        assert scheduler.task_due_now(dict(self.TASK), datetime(2026, 8, 27, 10, 20)) is True
        assert scheduler.task_due_now(dict(self.TASK), datetime(2026, 8, 27, 10, 31)) is False


# ═══════════════════════════════════════════════════════════════
# 双引擎：dsh 主 / claude 辅，可切换
# ═══════════════════════════════════════════════════════════════

class TestEngineSelection:
    def test_find_dsh_on_this_machine(self):
        """本机应能定位 dsh CLI（node + bin.js）。"""
        found = scheduler._find_dsh()
        if found is not None:  # 装有 dsh 的环境
            node_exe, bin_js = found
            assert node_exe.exists() and bin_js.exists()
            assert bin_js.name == "bin.js"

    def test_resolve_explicit(self, monkeypatch):
        monkeypatch.setattr(scheduler, "_engine_from_meta", lambda: None)
        monkeypatch.setattr(scheduler, "DEFAULT_ENGINE", "auto")
        assert scheduler.resolve_engine("dsh") == "dsh"
        assert scheduler.resolve_engine("claude") == "claude"

    def test_resolve_meta_override(self, monkeypatch):
        monkeypatch.setattr(scheduler, "_engine_from_meta", lambda: "claude")
        assert scheduler.resolve_engine(None) == "claude"
        assert scheduler.resolve_engine("dsh") == "dsh"  # 调用方优先

    def test_resolve_auto_falls_back_to_claude(self, monkeypatch):
        monkeypatch.setattr(scheduler, "_engine_from_meta", lambda: None)
        monkeypatch.setattr(scheduler, "DEFAULT_ENGINE", "auto")
        monkeypatch.setattr(scheduler, "_find_dsh", lambda: None)
        assert scheduler.resolve_engine(None) == "claude"

    def test_dsh_directive(self):
        t = {"task_id": "evening_review", "prompt_file": "my_doc/每日复盘/harness/automation/prompts/auto_evening_review.md",
             "self_managed_complete": True}
        d = scheduler._dsh_directive(t)
        assert d.startswith("执行 my_doc/每日复盘/harness/automation/prompts/auto_evening_review.md")
        assert "--complete" not in d

        t2 = {"task_id": "morning_analysis", "prompt_file": "p.md"}
        d2 = scheduler._dsh_directive(t2)
        assert "--complete morning_analysis" in d2


# ═══════════════════════════════════════════════════════════════
# 跨平台独立触发入口（cron / launchd / 计划任务 / 容器 cron）
# ═══════════════════════════════════════════════════════════════

class TestSchedulerCli:
    TASK = {"task_id": "morning_analysis", "target_time": "09:07",
            "days_of_week": [0, 1, 2, 3, 4], "trading_day_required": True}

    def test_skip_weekend(self, monkeypatch):
        monkeypatch.setattr(scheduler, "is_trading_day", lambda d: True)
        ok, reason, _ = cli.decide(dict(self.TASK), False, datetime(2026, 8, 29))  # 周六
        assert not ok and "星期" in reason

    def test_skip_non_trading_day(self, monkeypatch):
        monkeypatch.setattr(scheduler, "is_trading_day", lambda d: False)
        ok, reason, _ = cli.decide(dict(self.TASK), False, datetime(2026, 8, 27, 9, 7))  # 周四
        assert not ok and "交易日" in reason

    def test_idempotent_skip(self, monkeypatch):
        from dashboard import db as db_mod
        in_mem = _in_memory_db(monkeypatch)
        db_mod.init_db()
        monkeypatch.setattr(scheduler, "is_trading_day", lambda d: True)
        now = datetime(2026, 8, 27, 9, 7)
        wkey = scheduler.make_window_key(self.TASK, now)
        db_mod.scheduler_run_insert("morning_analysis", wkey, "cron",
                                    "2026-08-27 09:07:00", status="success")
        ok, reason, _ = cli.decide(dict(self.TASK), False, now)
        assert not ok and "已执行" in reason
        in_mem.close()

    def test_force_bypasses_all_gates(self, monkeypatch):
        monkeypatch.setattr(scheduler, "is_trading_day", lambda d: False)
        ok, _, wkey = cli.decide(dict(self.TASK), True, datetime(2026, 8, 29))  # 周六+非交易日
        assert ok and wkey.startswith("manual:")

    def test_run_task_sync_cron_window_key_matches_auto(self, monkeypatch):
        """cron 触发的 window_key 与引擎 auto 相同 → 两者互斥防双跑。"""
        from dashboard import db as db_mod
        in_mem = _in_memory_db(monkeypatch)
        db_mod.init_db()
        monkeypatch.setattr(scheduler, "_run_prompt", lambda task, run_id: None)
        now = datetime(2026, 8, 27, 9, 7)
        task = dict(self.TASK)
        run = scheduler.run_task_sync(task, trigger="cron", now=now)
        assert run["trigger"] == "cron"
        assert run["window_key"] == scheduler.make_window_key(task, now)
        in_mem.close()

    def test_cli_unknown_task_returns_1(self):
        assert cli.main(["--task", "no_such_task"]) == 1


# ═══════════════════════════════════════════════════════════════
# S6: 失败重试限次（2026-08-31 重试风暴修复）
# ═══════════════════════════════════════════════════════════════
# 背景：引擎每 20s tick，失败任务不在 scheduler_window_done 的完成状态
# （success/timeout）里 → 同一窗口内无限重试 → 7 分钟窗口可触发 20+ 次
# 失败风暴（实证：harness_bug_auto_fix run#85-91 连续 7 次失败）。
# 修复：同一窗口内 auto 失败达 MAX_AUTO_FAILURES_PER_WINDOW 次后跳过。

class TestAutoFailureRetryLimit:
    TASK = {"task_id": "hourly_fail", "hourly": True, "target_minute": 17,
            "hourly_range": [9, 10, 11], "days_of_week": None}

    def test_window_done_after_max_failures(self, monkeypatch):
        """同一窗口内失败达上限后，scheduler_window_done 视为已完成（阻止再重试）。"""
        from dashboard import db as db_mod
        in_mem = _in_memory_db(monkeypatch)
        db_mod.init_db()
        now = datetime(2026, 8, 31, 11, 18)  # 窗口内（:17 + 7min）
        wkey = scheduler.make_window_key(self.TASK, now)
        max_f = scheduler.MAX_AUTO_FAILURES_PER_WINDOW
        task_id = self.TASK["task_id"]

        # 初始：无运行记录 → 未 done
        assert db_mod.scheduler_window_done(task_id, wkey, max_failures=max_f) is False

        # 插入 max_f-1 条 failed → 仍可重试
        for _ in range(max_f - 1):
            db_mod.scheduler_run_insert(task_id, wkey, "auto",
                                        "2026-08-31 11:17:00", status="failed")
        assert db_mod.scheduler_window_done(task_id, wkey, max_failures=max_f) is False, \
            "未达失败上限前不应视为 done"

        # 再插 1 条 failed → 达上限 → done
        db_mod.scheduler_run_insert(task_id, wkey, "auto",
                                    "2026-08-31 11:18:00", status="failed")
        assert db_mod.scheduler_window_done(task_id, wkey, max_failures=max_f) is True, \
            "失败达上限后应视为 done（阻止重试风暴）"
        in_mem.close()

    def test_success_still_marks_done_immediately(self, monkeypatch):
        """success 仍立即可见（原语义不变）。"""
        from dashboard import db as db_mod
        in_mem = _in_memory_db(monkeypatch)
        db_mod.init_db()
        now = datetime(2026, 8, 31, 11, 18)
        wkey = scheduler.make_window_key(self.TASK, now)
        db_mod.scheduler_run_insert(self.TASK["task_id"], wkey, "auto",
                                    "2026-08-31 11:17:00", status="success")
        assert db_mod.scheduler_window_done(self.TASK["task_id"], wkey) is True
        in_mem.close()

    def test_manual_trigger_bypasses_failure_limit(self, monkeypatch):
        """手动触发不受失败限次影响（manual window_key 独立）。"""
        from dashboard import db as db_mod
        in_mem = _in_memory_db(monkeypatch)
        db_mod.init_db()
        now = datetime(2026, 8, 31, 11, 18)
        auto_wkey = scheduler.make_window_key(self.TASK, now)
        for _ in range(scheduler.MAX_AUTO_FAILURES_PER_WINDOW):
            db_mod.scheduler_run_insert(self.TASK["task_id"], auto_wkey, "auto",
                                        "2026-08-31 11:17:00", status="failed")
        # auto 窗口已耗尽 → run_task auto 应拒绝
        r = scheduler.run_task(dict(self.TASK), trigger="auto", now=now)
        assert r.get("started") is False
        assert r.get("reason") == "idempotent"
        # manual 触发仍可跑（手动 window_key 独立；mock _run_prompt 防真实执行）
        monkeypatch.setattr(scheduler, "_run_prompt", lambda task, run_id: None)
        r2 = scheduler.run_task(dict(self.TASK), trigger="manual", now=now)
        assert r2.get("started") is True
        import time
        time.sleep(0.3)  # 等后台线程跑完 mock（不产生未处理线程异常）
        in_mem.close()


# ═══════════════════════════════════════════════════════════════
# 僵尸 running 清理：进程重启后遗留 running 记录在 start() 时回收
# ═══════════════════════════════════════════════════════════════

class TestStartCleansZombieRuns:
    def test_start_marks_zombie_running_failed(self, monkeypatch):
        """start() 引擎启动前，把 DB 遗留 running 记录标记为 failed（重启中断）。"""
        from dashboard import db as db_mod
        in_mem = _in_memory_db(monkeypatch)
        db_mod.init_db()
        rid = db_mod.scheduler_run_insert("morning_analysis", "morning_analysis:2026-09-02",
                                          "auto", "2026-09-02 14:30:00", status="running")
        # 防止真实启动引擎线程（daemon 循环），只验证清理逻辑被触发
        monkeypatch.setattr(scheduler.SchedulerEngine, "_loop",
                            lambda self: None)

        scheduler.start()

        r = db_mod.scheduler_run_get(rid)
        assert r["status"] == "failed"
        assert "中断" in (r["output"] or "")
        in_mem.close()

    def test_start_no_running_no_cleanup(self, monkeypatch):
        """无 running 记录时 start() 不报错、无清理动作。"""
        from dashboard import db as db_mod
        in_mem = _in_memory_db(monkeypatch)
        db_mod.init_db()
        db_mod.scheduler_run_insert("morning_analysis", "morning_analysis:2026-09-02",
                                    "auto", "2026-09-02 14:30:00", status="success")
        monkeypatch.setattr(scheduler.SchedulerEngine, "_loop",
                            lambda self: None)
        scheduler.start()
        assert db_mod.scheduler_running_tasks() == []
        in_mem.close()


# ── helper：把 dashboard.db 指向内存库（与 test_dashboard_db.py 一致）──
def _in_memory_db(monkeypatch):
    import sqlite3
    from contextlib import contextmanager
    from dashboard import db as db_mod

    mem_conn = sqlite3.connect(":memory:")
    mem_conn.row_factory = sqlite3.Row

    @contextmanager
    def _get_conn():
        try:
            yield mem_conn
            mem_conn.commit()
        except Exception:
            mem_conn.rollback()
            raise

    monkeypatch.setattr(db_mod, "get_conn", _get_conn)
    return mem_conn
