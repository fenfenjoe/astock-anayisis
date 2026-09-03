"""Tests for scheduler 429 限流退避重试 + dsh 并发错峰（2026-09-02 事故修复）。

背景：morning_analysis 等任务因 DeepSeek API 429（AccountRateLimitExceeded）
直接失败（run#195）或陷入无限重试循环（run#198）。本测试覆盖：
- _is_rate_limited：可靠识别 429 特征
- _exec_dsh：命中 429 时指数退避重试，非 429 失败不重试
- 重试有上限（MAX_RATE_LIMIT_RETRIES），耗尽后返回 failed
- dsh 并发信号量：并发满时快速失败而非无限排队
"""
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from dashboard import scheduler  # noqa: E402


# ── fakes ────────────────────────────────────────────────────────

class _FakeProc:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode


def _make_subprocess_run(sequence):
    """返回 (fake_run, calls)。sequence: [(returncode, stderr_text), ...]。

    每个调用按顺序消费 sequence（超出则复用最后一个）；把 stderr 文本写入
    传入的 stderr 文件句柄（真实 _exec_dsh 用文件重定向避免 Windows 管道 EOF）。
    """
    calls = {"n": 0}

    def fake_run(cmd, **kwargs):
        idx = min(calls["n"], len(sequence) - 1)
        calls["n"] += 1
        rc, err = sequence[idx]
        fe = kwargs.get("stderr")
        if fe is not None and err:
            fe.write(err)
            fe.flush()
        return _FakeProc(rc)

    return fake_run, calls


@pytest.fixture(autouse=True)
def _fast_retry(monkeypatch):
    """把退避基数压到近零、并发获取超时压到极短，避免测试真实等待。"""
    monkeypatch.setattr(scheduler, "RATE_LIMIT_RETRY_BACKOFF_BASE_SECONDS", 0.01)
    monkeypatch.setattr(scheduler, "MAX_RATE_LIMIT_RETRIES", 2)
    monkeypatch.setattr(scheduler, "DSH_SEM_ACQUIRE_TIMEOUT", 0.05)
    monkeypatch.setattr(scheduler, "DSH_MAX_CONCURRENT", 2)


@pytest.fixture
def _env_ok(monkeypatch):
    """让 _exec_dsh 能走到 subprocess：dsh 可定位 + directive 正常。"""
    monkeypatch.setattr(scheduler, "_find_dsh", lambda: (Path("node.exe"), Path("bin.js")))
    monkeypatch.setattr(scheduler, "_dsh_directive", lambda task: "directive")


# ── 429 识别 ─────────────────────────────────────────────────────

class TestRateLimitDetection:
    def test_detect_real_429_signature(self):
        out = ('some progress\n\n[stderr]\n'
               'dsh: RATE_LIMIT: 429 {"error":{"code":"AccountRateLimitExceeded",'
               '"message":"Requests are too frequent. Please reduce your request frequency..."}')
        assert scheduler._is_rate_limited(out) is True

    def test_detect_lowercase(self):
        assert scheduler._is_rate_limited("... rate limit exceeded ...") is True
        assert scheduler._is_rate_limited("... requests are too frequent ...") is True

    def test_no_false_positive_on_normal_output(self):
        # 普通失败输出（无 429 特征）不应判为限流
        assert scheduler._is_rate_limited("strategy S4 done, 34 strategies loaded") is False
        assert scheduler._is_rate_limited("") is False
        assert scheduler._is_rate_limited(None) is False

    def test_bare_429_number_not_flagged(self):
        # 裸数字 429（如策略数量）不应误判为限流
        assert scheduler._is_rate_limited("total 429 strategies scanned") is False


# ── 退避重试 ─────────────────────────────────────────────────────

class TestRateLimitRetry:
    def test_retries_on_429_then_success(self, monkeypatch, _env_ok):
        seq = [
            (1, "dsh: RATE_LIMIT: 429 AccountRateLimitExceeded"),
            (0, "all done"),
        ]
        fake_run, calls = _make_subprocess_run(seq)
        monkeypatch.setattr(scheduler.subprocess, "run", fake_run)
        monkeypatch.setattr(scheduler, "MAX_RATE_LIMIT_RETRIES", 1)  # 1 次重试 = 2 次尝试

        status, out = scheduler._exec_dsh({"task_id": "morning_analysis"})

        assert calls["n"] == 2
        assert status == "success"
        assert "all done" in out

    def test_gives_up_after_max_retries(self, monkeypatch, _env_ok):
        seq = [
            (1, "dsh: RATE_LIMIT: 429 AccountRateLimitExceeded"),
            (1, "dsh: RATE_LIMIT: 429 AccountRateLimitExceeded"),
            (1, "dsh: RATE_LIMIT: 429 AccountRateLimitExceeded"),
        ]
        fake_run, calls = _make_subprocess_run(seq)
        monkeypatch.setattr(scheduler.subprocess, "run", fake_run)

        status, out = scheduler._exec_dsh({"task_id": "morning_analysis"})

        # MAX_RATE_LIMIT_RETRIES=2 → 最多 2 次重试 + 首次 = 3 次尝试
        assert calls["n"] == 3
        assert status == "failed"
        assert "429" in out

    def test_no_retry_on_non_ratelimit_failure(self, monkeypatch, _env_ok):
        seq = [(1, "some other error")]
        fake_run, calls = _make_subprocess_run(seq)
        monkeypatch.setattr(scheduler.subprocess, "run", fake_run)

        status, out = scheduler._exec_dsh({"task_id": "morning_analysis"})

        assert calls["n"] == 1
        assert status == "failed"
        assert "some other error" in out

    def test_success_no_retry(self, monkeypatch, _env_ok):
        seq = [(0, "done")]
        fake_run, calls = _make_subprocess_run(seq)
        monkeypatch.setattr(scheduler.subprocess, "run", fake_run)

        status, _ = scheduler._exec_dsh({"task_id": "morning_analysis"})

        assert calls["n"] == 1
        assert status == "success"


# ── 并发错峰（信号量） ───────────────────────────────────────────

class TestDshConcurrency:
    def test_semaphore_full_fails_fast(self, monkeypatch, _env_ok):
        """并发已满时，_exec_dsh 快速失败（不无限排队）。"""
        # 替换为容量 1 的信号量，并提前占满
        sem = threading.BoundedSemaphore(1)
        sem.acquire()
        monkeypatch.setattr(scheduler, "_dsh_sem", sem)

        status, out = scheduler._exec_dsh({"task_id": "morning_analysis"})

        assert status == "failed"
        assert "并发" in out
        sem.release()

    def test_semaphore_released_after_run(self, monkeypatch, _env_ok):
        """运行结束后信号量释放，后续任务可进入。"""
        monkeypatch.setattr(scheduler.subprocess, "run",
                            lambda *a, **k: _FakeProc(0))
        status, _ = scheduler._exec_dsh({"task_id": "morning_analysis"})
        assert status == "success"
        # 容量 2 的信号量应全部可用（acquire 不阻塞即证明已释放）
        assert scheduler._dsh_sem.acquire(blocking=False) is True
        scheduler._dsh_sem.release()
        assert scheduler._dsh_sem.acquire(blocking=False) is True
        scheduler._dsh_sem.release()
