"""load_env.py — .env 加载测试（不覆盖已存在环境变量 / 解析规则）。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from load_env import load_env_file


def test_loads_keys_and_does_not_override_existing(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "DASHBOARD_DB_BACKEND=cloud\nOTHER=value\n",
        encoding="utf-8")
    monkeypatch.setenv("DASHBOARD_DB_BACKEND", "file")  # 已存在 → 不覆盖
    load_env_file(env)
    assert os.environ["DASHBOARD_DB_BACKEND"] == "file"  # 环境变量优先
    assert os.environ["OTHER"] == "value"


def test_ignores_comments_and_blanks(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# 注释\n\nEMPTY=\nA=\"quoted\"\nB='single'\n",
        encoding="utf-8")
    load_env_file(env)
    assert "EMPTY" not in os.environ or os.environ["EMPTY"] == ""
    assert os.environ["A"] == "quoted"
    assert os.environ["B"] == "single"


def test_missing_file_noop(tmp_path, monkeypatch):
    load_env_file(tmp_path / "nope.env")  # 不抛异常
