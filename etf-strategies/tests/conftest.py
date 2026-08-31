import os
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from unittest.mock import MagicMock
import pandas as pd
import pytest


# ═══════════════════════════════════════════════════════════════
# 测试环境隔离（2026-08-31 事故修复）
# ───────────────────────────────────────────────────────────────
# 事故：test_dashboard_auth.py 用 `with TestClient(app)` 触发 lifespan，
# lifespan 执行真实启动副作用（CLOUD_RESTORE 云下载覆盖本地账本 +
# import_holdings/trades 用真实文件覆盖真实 DB + upload 上传云），且
# dashboard.app 导入时会 load_env_file() 读 .env 的 DB_MODE=memory /
# CLOUD_RESTORE_ON_START=1 → 测试数据污染真实 DB 并经 memory 快照回传扩散到 TOS。
#
# 防护：在 pytest 进程最早阶段（本模块导入时，早于任何 dashboard 模块）
# 设置安全环境变量。load_env_file 的语义是"已存在的键不覆盖"，因此
# 只要这里的值先于 .env 设置，dashboard 导入后仍保持安全值。
# 注意：必须用强制赋值而非 setdefault —— 宿主环境（harness/Claude Code 会话
# 加载 .env 后）可能已继承 DB_MODE=memory / CLOUD_RESTORE_ON_START=1，
# setdefault 无法覆盖继承值，会重新触发 2026-08-31 事故（BUG-009/BUG-010）。
os.environ["DB_MODE"] = "file"                           # 强制文件模式，禁用 memory 快照回传
os.environ["CLOUD_RESTORE_ON_START"] = "0"               # 强制禁用启动云下载（file 模式下 cloud_restore 本就 no-op）
os.environ.setdefault("DSH_TEST", "1")                   # app.lifespan 测试免疫标记


# ═══════════════════════════════════════════════════════════════
# Shared mock: daily_signal
# ═══════════════════════════════════════════════════════════════
_REAL_DAILY_SIGNAL = sys.modules.get("daily_signal")
# Only create the mock if the real module hasn't been imported yet, OR if
# another test file has already replaced it with its own mock. We use a
# consistent mock object that both test files share.
if "daily_signal" not in sys.modules or isinstance(sys.modules["daily_signal"], MagicMock):
    _shared_ds_mock = MagicMock()
    _shared_ds_mock.STRAT_MAP = {}
    _shared_ds_mock.get_etf_name = MagicMock(return_value="TestETF")
    sys.modules["daily_signal"] = _shared_ds_mock
else:
    # Real module is loaded — don't replace it; individual tests should
    # use monkeypatch.setattr to mock specific attributes.
    _shared_ds_mock = None


@pytest.fixture(autouse=True)
def _reset_daily_signal_mock():
    """Reset the shared daily_signal mock before each test."""
    if _shared_ds_mock is not None:
        _shared_ds_mock.STRAT_MAP = {}
        _shared_ds_mock.get_etf_name = MagicMock(return_value="TestETF")
    yield
    if _shared_ds_mock is not None:
        _shared_ds_mock.STRAT_MAP = {}


@pytest.fixture
def synth_prices():
    """合成价格：510300 每日涨1%，511260 每日涨0.1%，共10个交易日。"""
    dates = pd.date_range("2024-01-01", periods=10, freq="B")
    return pd.DataFrame({
        "510300": [100 * (1.01 ** i) for i in range(10)],
        "511260": [100 * (1.001 ** i) for i in range(10)],
    }, index=dates)


@pytest.fixture
def flat_prices():
    """平价序列（无收益）：便于测再平衡算术。"""
    dates = pd.date_range("2024-01-01", periods=10, freq="B")
    return pd.DataFrame({
        "510300": [100.0] * 10,
        "511260": [100.0] * 10,
    }, index=dates)
