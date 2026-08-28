"""agent/dsh_runner.py — 通过 dsh headless 执行小满任务（Agent 2 = dsh --profile xiaoman）。"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from agent import config, dsh_runner


def test_find_dsh_returns_none_without_node(monkeypatch):
    monkeypatch.setattr(dsh_runner.shutil, "which", lambda name: None)
    # 屏蔽 nvm 分支（真实机器有 nvm 安装，会命中）
    monkeypatch.setattr(dsh_runner.Path, "home",
                        staticmethod(lambda: Path("Z:/no_such_home")))
    assert dsh_runner.find_dsh_bin() is None


def test_run_task_not_found(monkeypatch):
    monkeypatch.setattr(dsh_runner, "find_dsh_bin", lambda: None)
    status, out = dsh_runner.run_task("hi")
    assert status == "not_found"
    assert "dsh" in out


def test_run_task_success(monkeypatch):
    class FakeProc:
        returncode = 0
        stdout = "你好，我是小满。"
        stderr = ""

    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw
        return FakeProc()

    monkeypatch.setattr(dsh_runner, "find_dsh_bin",
                        lambda: (Path("node.exe"), Path("bin.js")))
    status, out = dsh_runner.run_task("hi", run=fake_run)
    assert status == "success"
    assert out == "你好，我是小满。"
    # 命令构造：node bin.js --profile xiaoman <task>
    assert captured["cmd"][-3:] == ["--profile", "xiaoman", "hi"]
    assert captured["kw"]["timeout"] == config.DSH_TIMEOUT_SECONDS
    assert captured["kw"]["capture_output"] is True
    # 默认注入 OpenViking 隔离变量（②）
    env = captured["kw"]["env"]
    assert env["OPENVIKING_PEER_ID"] == "xiaoman"
    assert env["OPENVIKING_RECALL_PEER_SCOPE"] == "actor"


def test_run_task_env_override(monkeypatch):
    class FakeProc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    captured = {}

    def fake_run(cmd, **kw):
        captured["kw"] = kw
        return FakeProc()

    monkeypatch.setattr(dsh_runner, "find_dsh_bin",
                        lambda: (Path("n"), Path("b")))
    dsh_runner.run_task("hi", run=fake_run, env={"OPENVIKING_PEER_ID": "other"})
    assert captured["kw"]["env"]["OPENVIKING_PEER_ID"] == "other"


def test_run_task_timeout(monkeypatch):
    def fake_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, timeout=kw["timeout"])

    monkeypatch.setattr(dsh_runner, "find_dsh_bin",
                        lambda: (Path("n"), Path("b")))
    status, out = dsh_runner.run_task("hi", run=fake_run)
    assert status == "timeout"
    assert "超时" in out


def test_run_task_failed_nonzero(monkeypatch):
    class FakeProc:
        returncode = 1
        stdout = ""
        stderr = "boom: bad profile"

    monkeypatch.setattr(dsh_runner, "find_dsh_bin",
                        lambda: (Path("n"), Path("b")))
    status, out = dsh_runner.run_task("hi", run=lambda *a, **k: FakeProc())
    assert status == "failed"
    assert "boom" in out


def test_run_task_oserror(monkeypatch):
    def fake_run(cmd, **kw):
        raise OSError("cannot run node")

    monkeypatch.setattr(dsh_runner, "find_dsh_bin",
                        lambda: (Path("n"), Path("b")))
    status, out = dsh_runner.run_task("hi", run=fake_run)
    assert status == "failed"
    assert "启动失败" in out
