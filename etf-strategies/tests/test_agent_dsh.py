"""agent/dsh_runner.py — 通过 dsh headless 执行小满任务（Agent 2 = dsh --profile xiaoman）。

2026-09-07：run_task 改为文件重定向（stdout/stderr → 临时文件）替代 capture_output，
规避 Windows 管道 EOF 挂死雷区；测试同步适配：fake run 需向传入的 stdout/stderr 文件句柄写内容。
"""
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
    def fake_run(cmd, **kw):
        # 新契约：stdout/stderr 是临时文件句柄（文件重定向），真实写入即代表子进程输出
        kw["stdout"].write("你好，我是小满。")
        kw["stderr"].write("")
        kw["stdout"].flush()
        return type("P", (), {"returncode": 0})()

    captured = {}

    def fake_run_wrap(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw
        return fake_run(cmd, **kw)

    monkeypatch.setattr(dsh_runner, "find_dsh_bin",
                        lambda: (Path("node.exe"), Path("bin.js")))
    status, out = dsh_runner.run_task("hi", run=fake_run_wrap)
    assert status == "success"
    assert out == "你好，我是小满。"
    # 命令构造：node bin.js --profile xiaoman <task>
    assert captured["cmd"][-3:] == ["--profile", "xiaoman", "hi"]
    assert captured["kw"]["timeout"] == config.DSH_TIMEOUT_SECONDS
    # 不再使用 capture_output（Windows 管道 EOF 挂死雷区）→ 走文件重定向
    assert "capture_output" not in captured["kw"]
    assert "stdin" in captured["kw"] and captured["kw"]["stdin"] == subprocess.DEVNULL
    assert "stdout" in captured["kw"] and hasattr(captured["kw"]["stdout"], "write")
    # 默认注入 OpenViking 隔离变量（②）
    env = captured["kw"]["env"]
    assert env["OPENVIKING_PEER_ID"] == "xiaoman"
    assert env["OPENVIKING_RECALL_PEER_SCOPE"] == "actor"


def test_run_task_env_override(monkeypatch):
    def fake_run(cmd, **kw):
        kw["stdout"].write("ok")
        kw["stderr"].write("")
        kw["stdout"].flush()
        return type("P", (), {"returncode": 0})()

    captured = {}

    def fake_run_wrap(cmd, **kw):
        captured["kw"] = kw
        return fake_run(cmd, **kw)

    monkeypatch.setattr(dsh_runner, "find_dsh_bin",
                        lambda: (Path("n"), Path("b")))
    dsh_runner.run_task("hi", run=fake_run_wrap, env={"OPENVIKING_PEER_ID": "other"})
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
    def fake_run(cmd, **kw):
        kw["stdout"].write("partial output")
        kw["stderr"].write("boom: bad profile")
        kw["stderr"].flush()
        return type("P", (), {"returncode": 1})()

    monkeypatch.setattr(dsh_runner, "find_dsh_bin",
                        lambda: (Path("n"), Path("b")))
    status, out = dsh_runner.run_task("hi", run=fake_run)
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
