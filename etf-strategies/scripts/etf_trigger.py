"""薄封装入口 — 供 Windows 计划任务 / cron 直接调用（不依赖工作目录）。

计划任务配置（由 setup_etf_scheduled_tasks.ps1 生成）:
    程序:  python
    参数:  E:\\...\\etf-strategies\\scripts\\etf_trigger.py --task morning_analysis

等价于 `python -m dashboard.scheduler_cli ...`，但通过绝对路径执行本文件，
sys.path 自动指向 etf-strategies，无需关心工作目录 / PYTHONPATH。
"""
import sys
from pathlib import Path

_ETF_DIR = Path(__file__).resolve().parent.parent
if str(_ETF_DIR) not in sys.path:
    sys.path.insert(0, str(_ETF_DIR))

from dashboard.scheduler_cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
