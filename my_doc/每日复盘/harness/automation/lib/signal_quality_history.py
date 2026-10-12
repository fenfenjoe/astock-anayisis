"""
信号质量周度快照存档 — P0a（自进化框架 G8 版本化）

为 gap_analysis（P0c）提供"近 N 周分维度指标序列"原料：
  - save_weekly_snapshot(): 追加当周 {week_key, cohort_start, cohort_end, dashboard, dims, saved_at}
  - load_history(): 读全部快照（按 week_key 排序）
  - recent_weeks(n): 最近 n 周快照（按 week_key 取最后 n 个）

设计要点（对齐框架研究文档 §3.5 公共构件 #2 版本化/快照、#8 隔离与并发）：
  - 原子写：临时文件 + os.replace，避免写一半损坏
  - 幂等：同 week_key 重复保存 → 覆盖（周报重跑不产生重复周）
  - 损坏容错：文件缺失/损坏 → 备份 .bak + 返回 []（不阻塞周报任务）
  - 文件位置：automation/config/signal_quality_history.json（与 signal_tracking.json 同目录，
    云库化前先本地，迁移逻辑参考 migrate_signal_tracking.py）
"""

import json
import os
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent
DEFAULT_HISTORY_PATH = _HERE / "config" / "signal_quality_history.json"


def _read_raw(path: Path) -> list:
    """读原始 JSON 列表；损坏时备份 .bak 并返回 []。"""
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(f"history 文件应为 JSON 列表，实际: {type(data).__name__}")
        return data
    except (json.JSONDecodeError, ValueError, OSError) as e:
        # 损坏 → 备份后返回空，不阻塞调用方
        try:
            bak = path.with_suffix(path.suffix + ".bak")
            os.replace(path, bak)
        except OSError:
            pass
        return []


def _atomic_write(path: Path, data: list) -> None:
    """原子写：临时文件 + os.replace。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def save_weekly_snapshot(snapshot: dict, path=None) -> Path:
    """追加/覆盖一条周度快照（幂等：同 week_key 覆盖）。

    snapshot 至少含 week_key；自动补 saved_at（若缺失）。
    返回实际写入路径。
    """
    p = Path(path) if path is not None else DEFAULT_HISTORY_PATH
    snap = dict(snapshot)
    if "saved_at" not in snap:
        snap["saved_at"] = datetime.now().isoformat(timespec="seconds")

    history = _read_raw(p)
    # 幂等：同 week_key 覆盖
    history = [h for h in history if h.get("week_key") != snap.get("week_key")]
    history.append(snap)
    history.sort(key=lambda h: h.get("week_key", ""))
    _atomic_write(p, history)
    return p


def load_history(path=None) -> list:
    """读全部快照（按 week_key 排序）。文件缺失/损坏 → []。"""
    p = Path(path) if path is not None else DEFAULT_HISTORY_PATH
    return _read_raw(p)


def recent_weeks(n: int, path=None) -> list:
    """最近 n 周快照（按 week_key 取最后 n 个），gap_analysis 直接消费。"""
    history = load_history(path)
    return history[-n:] if n > 0 else []
