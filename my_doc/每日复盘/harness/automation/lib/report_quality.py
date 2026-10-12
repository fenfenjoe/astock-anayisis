"""
报告质量独立评审核心 — P0b（自进化框架 G6 评估 / G8 版本化）

为 gap_analysis（P0c）提供"报告质量分数序列"：
  - validate_score(): 校验/规整四维分数（0-5 整数，总分=求和）
  - parse_score_markdown(): 从评审子代理输出中解析 JSON 分数（容忍 markdown 包裹）
  - save_report_score(): 存档当日分数（幂等：同 date 覆盖）
  - load_scores() / recent_scores(n): 读历史
  - weekly_report_quality(): 周度聚合（四维均值 + 总分均值 + 样本数）

设计要点（对齐框架研究文档 §3.5 公共构件 #1 演化状态存储、#2 版本化快照）：
  - 原子写 + 损坏 .bak 备份（与 signal_quality_history 同构）
  - 幂等同日覆盖：评审重跑不产生重复记录
  - Generator-Evaluator 分离：本模块只消费评审者输出，不参与报告生成
"""

import json
import re
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent
DEFAULT_HISTORY_PATH = _HERE / "config" / "report_quality_history.json"

SCORE_DIMENSIONS = ['data_validation', 'logic_consistency', 'completeness', 'format']
MAX_PER_DIM = 5


def validate_score(score: dict) -> dict:
    """校验/规整分数。返回带 total 的副本；非法抛 ValueError。"""
    if not isinstance(score, dict):
        raise ValueError('score 必须是 dict')
    scores = score.get('scores')
    if not isinstance(scores, dict):
        raise ValueError('score.scores 缺失或非 dict')
    for dim in SCORE_DIMENSIONS:
        if dim not in scores:
            raise ValueError(f'缺少维度: {dim}')
        v = scores[dim]
        if not isinstance(v, (int, float)):
            raise ValueError(f'{dim} 必须是数值')
        if not (0 <= v <= MAX_PER_DIM):
            raise ValueError(f'{dim}={v} 超出范围 [0,{MAX_PER_DIM}]')
        scores[dim] = int(v)
    out = dict(score)
    out['scores'] = dict(scores)
    out['total'] = sum(scores.values())
    return out


def parse_score_markdown(md_text: str) -> dict | None:
    """从评审输出中解析分数 JSON。容忍 ```json 包裹；非法返回 None。"""
    if not md_text or not isinstance(md_text, str):
        return None
    # 优先取 ```json ... ``` 代码块
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', md_text, re.S)
    candidate = m.group(1) if m else md_text.strip()
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    try:
        return validate_score(data)
    except ValueError:
        return None


def _read_raw(path: Path) -> list:
    if not path.exists():
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError('应为 JSON 列表')
        return data
    except (json.JSONDecodeError, ValueError, OSError):
        try:
            bak = path.with_suffix(path.suffix + '.bak')
            path.replace(bak)
        except OSError:
            pass
        return []


def _atomic_write(path: Path, data: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    tmp.replace(path)


def save_report_score(score: dict, path=None) -> Path:
    """存档当日分数（幂等：同 date 覆盖）。返回实际写入路径。"""
    p = Path(path) if path is not None else DEFAULT_HISTORY_PATH
    rec = validate_score(score)
    if 'scored_at' not in rec:
        rec['scored_at'] = datetime.now().isoformat(timespec='seconds')

    history = _read_raw(p)
    history = [h for h in history if h.get('date') != rec.get('date')]
    history.append(rec)
    history.sort(key=lambda h: h.get('date', ''))
    _atomic_write(p, history)
    return p


def load_scores(path=None) -> list:
    p = Path(path) if path is not None else DEFAULT_HISTORY_PATH
    return _read_raw(p)


def recent_scores(n: int, path=None) -> list:
    history = load_scores(path)
    return history[-n:] if n > 0 else []


def weekly_report_quality(scores: list, week_start: str, week_end: str) -> dict:
    """周度聚合：四维均值 + 总分均值 + 样本数（含边界日期）。
    总分由四维重新求和（不信任存储的 total，防脏数据）。
    无样本时 avg_total 为 None。"""
    week = [s for s in scores if week_start <= s.get('date', '') <= week_end]
    if not week:
        return {'n': 0, 'avg_total': None, 'avg_by_dim': {d: None for d in SCORE_DIMENSIONS}}
    avg_by_dim = {}
    for dim in SCORE_DIMENSIONS:
        vals = [s.get('scores', {}).get(dim) for s in week
                if s.get('scores', {}).get(dim) is not None]
        avg_by_dim[dim] = round(sum(vals) / len(vals), 2) if vals else None
    totals = []
    for s in week:
        sc = s.get('scores') or {}
        if all(d in sc for d in SCORE_DIMENSIONS):
            totals.append(sum(sc[d] for d in SCORE_DIMENSIONS))
    return {
        'n': len(week),
        'avg_total': round(sum(totals) / len(totals), 2) if totals else None,
        'avg_by_dim': avg_by_dim,
    }
