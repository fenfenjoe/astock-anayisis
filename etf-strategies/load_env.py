"""load_env.py — 轻量 .env 加载（零依赖）。

本地跑 `python dashboard/app.py` / `python -m agent` 时自动读取
etf-strategies/.env（不覆盖已存在的系统环境变量：环境变量优先）。
Docker 场景由 compose 注入环境变量，无需本文件。
"""
import os
from pathlib import Path

_ENV_FILE = Path(__file__).resolve().parent / ".env"


def load_env_file(path=None):
    """读取 .env 并写入 os.environ（已存在的键不覆盖）。文件不存在无副作用。"""
    path = Path(path) if path else _ENV_FILE
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def load():
    load_env_file()
