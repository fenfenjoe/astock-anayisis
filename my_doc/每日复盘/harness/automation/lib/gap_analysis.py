"""
差距分析 — P0c（自进化框架"差距分析器"，连接结算器与改进执行器）

输入：goals.md 的机器结算定义（JSON 块）+ 历史指标快照（signal_quality_history.json
      / report_quality_history.json）
输出：各目标差距（gap = target - current），排序 + 归因 + 定向 REQ 建议。

实现说明（P3b 框架插件化）：核心算法已上移平台层 `~/.dsh/evolve/engine/`
（gaps.py / goals.py / metrics.py，无项目路径依赖），本文件保留项目路径默认值
并复用框架核心，保持项目测试向后兼容。
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent
DEFAULT_GOALS_PATH = _HERE.parent.parent.parent.parent / "evolution" / "config" / "goals.md"
DEFAULT_SQ_HISTORY = _HERE / "config" / "signal_quality_history.json"
DEFAULT_RQ_HISTORY = _HERE / "config" / "report_quality_history.json"

_DSH_HOME = Path.home() / ".dsh"
if str(_DSH_HOME) not in sys.path:
    sys.path.insert(0, str(_DSH_HOME))

from evolve.engine.gaps import (  # noqa: F401,E402  (平台层框架引擎)
    compute_gaps,
    gen_req_suggestion,
    build_gap_report,
)
from evolve.engine.goals import parse_goals as _parse_goals  # noqa: E402
from evolve.engine.metrics import current_value as _current_value  # noqa: E402


def parse_goals(md_text: str) -> dict:
    """解析 goals.md 机器结算块（复用框架引擎）。"""
    return _parse_goals(md_text)


def current_value(metric: dict, sq_history: list, rq_history: list):
    """从历史快照算某指标当前值（复用框架引擎）。"""
    return _current_value(metric, sq_history, rq_history)
