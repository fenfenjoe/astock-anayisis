"""
REQ 对照验证 — P2（自进化框架"对照验证"环节，闭环最后一段）

把"改了但不知道有没有变好"升级为"指标前后对比证明变好"。

实现说明（P3b 框架插件化）：本文件为项目薄壳，核心算法已上移平台层
`~/.dsh/evolve/engine/verify.py`（无项目路径依赖），此处引用并保持
项目测试向后兼容。新增算法逻辑请先落框架引擎。
"""

import sys
from pathlib import Path

_DSH_HOME = Path.home() / ".dsh"
if str(_DSH_HOME) not in sys.path:
    sys.path.insert(0, str(_DSH_HOME))

from evolve.engine.verify import (  # noqa: F401,E402  (平台层框架引擎)
    parse_evolution_fields,
    evaluate_improvement,
    suggest_action,
    track_feedback,
    due_for_verification,
)

from evolve.engine.metrics import extract_window as _extract_window  # noqa: E402


def extract_window(sq_history: list, field: str, weeks: int) -> float | None:
    """取历史快照最近 N 周某字段均值（复用框架引擎，语义不变）。"""
    return _extract_window(sq_history, field, weeks)
