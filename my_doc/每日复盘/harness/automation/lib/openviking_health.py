"""
OpenViking 经验库健康检查核心逻辑 — REQ-009

从 auto_experience_health 的领域标签完整性 / 元数据校验 / 过时检测 / 置信度健康
/ T2 贝叶斯置信度更新 提取为可复用纯函数，供 auto_experience_health 任务复用，
并支撑 REQ-009 的补全迁移回归验证。

设计原则：
- 纯计算函数，不读写磁盘、不调用 OpenViking API（调用方负责传入条目内容/元数据）。
- 元数据格式对齐 harness/experience/_schema.md 的 `## 元数据` 节约定：
  ```
  ## 元数据（供检索与融会贯通）
  - 来源：{source}
  - 领域：{domain}
  - 状态：{active | deprecated | merged | conflict}
  - 关联：{相关经验 URI 列表}
  - 首次沉淀：{YYYY-MM-DD} | 最近更新：{YYYY-MM-DD}
  ```
  置信度：在 Reflect 节（`- 置信度：{高/中/低}`）或 元数据 节均可被解析。
"""

from datetime import date, datetime

# ============================================================
# 常量
# ============================================================

# 必需领域定义（对齐 auto_experience_health 第五步 5.1/5.2/5.3 与 09-09 健康报告）
REQUIRED_DOMAINS = {
    "投资": [
        "市场判断",
        "跨市场映射",
        "开盘前评估",
        "数据纪律",
        "早盘纪律设计",
        "策略纪律",
        "宏观数据公布日",
        "超跌反弹",
        "信号设计",
    ],
    "短线": [
        "做T",
        "跷跷板套利",
        "跨市场套利",
        "事件套利",
    ],
    "审阅": [
        "审阅流程",
        "数据核验清单",
        "逻辑一致性检查",
        "完整性检查",
        "格式标准",
        "常见错误模式",
        "修正原则",
        "每日信号审阅清单",
    ],
}

# 元数据必需字段（REQ-009 期望结果 2：领域/状态/置信度/首次沉淀/最近更新）
REQUIRED_METADATA_FIELDS = ["领域", "状态", "置信度", "首次沉淀", "最近更新"]

# 置信度合法取值
VALID_CONFIDENCE = {"高", "中", "低"}

# 状态合法取值（对齐 _schema.md）
VALID_STATUS = {"active", "deprecated", "merged", "conflict"}

# T2 证据类型
VALID_EVIDENCE_TYPES = {"verify", "falsify"}

# 过时检测阈值（天）
STALE_DAYS = 90

# 元数据节标题前缀（正文省略协议前缀，标题含"元数据"字样）
_METADATA_HEADER_KEYWORDS = ("## 元数据",)


# ============================================================
# 元数据解析
# ============================================================

def parse_metadata(content: str) -> dict:
    """解析经验条目的 `## 元数据` 节 → dict。

    格式：`- 键：值` 逐行。特殊行 `- 首次沉淀：{d} | 最近更新：{d}` 拆分为两个键。
    置信度若不在 元数据 节（通常在 Reflect 的 `- 置信度：`），从全文兜底提取。

    Args:
        content: 经验条目全文（markdown 字符串）。

    Returns:
        dict — 解析出的元数据键值对；无 元数据 节时返回空 dict。
        值可能为空字符串（键存在但无值）。
    """
    meta = {}
    lines = content.splitlines()
    in_meta = False

    for line in lines:
        stripped = line.strip()
        # 进入/退出 元数据 节（下一个 ## 二级标题结束）
        if stripped.startswith("## ") and not stripped.startswith("### "):
            if in_meta:
                break
            if any(kw in stripped for kw in _METADATA_HEADER_KEYWORDS):
                in_meta = True
            continue

        if not in_meta:
            continue

        # 解析 `- 键：值`（兼容 中文全角冒号）
        if stripped.startswith("- ") and "：" in stripped:
            key, _, value = stripped[2:].partition("：")
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            # 首次沉淀：{d} | 最近更新：{d} 拆分为两键
            if key == "首次沉淀" and " | " in value:
                first_part, _, last_part = value.partition(" | ")
                meta["首次沉淀"] = first_part.strip()
                if "：" in last_part:
                    last_key, _, last_val = last_part.partition("：")
                    meta[last_key.strip()] = last_val.strip()
                else:
                    meta["最近更新"] = last_part.strip()
            else:
                meta[key] = value

    # 置信度兜底：元数据节缺失时从全文（通常 Reflect）提取
    if "置信度" not in meta:
        conf = _extract_confidence(content)
        if conf is not None:
            meta["置信度"] = conf

    return meta


def _extract_confidence(content: str) -> str | None:
    """从全文提取 `置信度：{高/中/低}`（返回规范化值；找不到返回 None）。"""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("- 置信度"):
            _, _, val = stripped.partition("：")
            val = val.strip()
            for c in ("高", "中", "低"):
                if c in val:
                    return c
    return None


def check_metadata_complete(metadata: dict, required: list = None) -> tuple:
    """校验条目元数据完整性。

    Args:
        metadata: parse_metadata 的结果 dict。
        required: 必需字段列表（默认 REQUIRED_METADATA_FIELDS）。

    Returns:
        (complete: bool, missing: list[str]) — complete=True 表示全部必需字段
        存在且非空；missing 为缺失/空值字段列表。
    """
    if required is None:
        required = REQUIRED_METADATA_FIELDS
    missing = [f for f in required if not metadata.get(f, "").strip()]
    return (len(missing) == 0, missing)


# ============================================================
# 领域完整性
# ============================================================

def check_domain_completeness(present_domains: list, required=None) -> list:
    """领域缺失检测。

    Args:
        present_domains: 现有条目已覆盖的领域标签列表。
        required: 必需领域定义。可为 dict（如 REQUIRED_DOMAINS，展平为单层列表）
            或扁平 list[str]（自定义必需领域列表）。默认 REQUIRED_DOMAINS。

    Returns:
        list[str] — 缺失的必需领域列表（保持 required 定义顺序）。present 中的
        额外/未知领域不计入。
    """
    if required is None:
        required = REQUIRED_DOMAINS
    if isinstance(required, dict):
        required_flat = [d for cat in required.values() for d in cat]
    else:
        required_flat = list(required)
    present_set = set(present_domains)
    return [d for d in required_flat if d not in present_set]


# ============================================================
# 置信度健康
# ============================================================

def compute_confidence_distribution(entries: list) -> dict:
    """统计经验条目置信度分布。

    Args:
        entries: list[dict] — 每条含 '置信度'（可能缺失/None/空）。

    Returns:
        {
            '高': n, '中': n, '低': n, 'unknown': n, 'total': n,
            'high_pct': float,   # 高 / total × 100（total=0 → 0.0）
            'low_pct': float,    # 低 / total × 100
        }
    """
    counts = {"高": 0, "中": 0, "低": 0}
    unknown = 0
    for e in entries:
        conf = (e.get("置信度") or "").strip()
        if conf in counts:
            counts[conf] += 1
        else:
            unknown += 1
    total = len(entries)
    high_pct = (counts["高"] / total * 100.0) if total else 0.0
    low_pct = (counts["低"] / total * 100.0) if total else 0.0
    return {
        "高": counts["高"],
        "中": counts["中"],
        "低": counts["低"],
        "unknown": unknown,
        "total": total,
        "high_pct": high_pct,
        "low_pct": low_pct,
    }


# ============================================================
# 过时检测
# ============================================================

def _parse_date(value: str):
    """解析 YYYY-MM-DD（兼容 YYYY/M/D）；失败返回 None。"""
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def detect_stale(entries: list, max_days: int = STALE_DAYS, ref_date: str = None) -> list:
    """过时检测：`最近更新` 早于 ref_date - max_days 的条目。

    Args:
        entries: list[dict] — 每条含 '最近更新'（YYYY-MM-DD）。
        max_days: 过时阈值天数（> max_days 才算过时）。
        ref_date: 参考日期（YYYY-MM-DD）；默认今天。

    Returns:
        list[dict] — 过时条目（保留原 dict 引用）。无日期/日期无法解析的条目跳过。
    """
    if ref_date:
        ref = _parse_date(ref_date) or date.today()
    else:
        ref = date.today()

    stale = []
    for e in entries:
        raw = (e.get("最近更新") or "").strip()
        d = _parse_date(raw)
        if d is None:
            continue
        if (ref - d).days > max_days:
            stale.append(e)
    return stale


# ============================================================
# T2 贝叶斯置信度更新
# ============================================================

def apply_t2_update(confidence: str, evidence_type: str, verify_count: int = 1) -> dict:
    """贝叶斯 T2 置信度更新（对齐 _schema.md 贝叶斯更新落地规则）。

    规则：
    - evidence_type='verify'（验证）：
      - 中 + 累计 ≥2 次独立验证 → 高（不一次打满）
      - 中 + <2 次 → 保持不变
      - 高 → 保持不变
      - 低 → 保持不变（单次验证不直接回中）
    - evidence_type='falsify'（证伪）：
      - 中 → 低（不删除）
      - 低 → 低 + 状态 deprecated（低被再证伪）
      - 高 → 低（单次证伪大幅降级但不直接废弃）

    Args:
        confidence: 当前置信度（高/中/低）。
        evidence_type: 'verify' | 'falsify'。
        verify_count: 累计独立验证次数（默认 1；仅 verify 且 confidence=中 时生效）。

    Returns:
        {
            'confidence': 更新后置信度,
            'status_change': None | 'deprecated'（仅低被再证伪时非 None）,
            'changed': bool,
            'reason': str,
        }

    Raises:
        ValueError: confidence 或 evidence_type 非法。
    """
    conf = (confidence or "").strip()
    if conf not in VALID_CONFIDENCE:
        raise ValueError(f"非法置信度: {confidence!r}，合法值 {sorted(VALID_CONFIDENCE)}")
    if evidence_type not in VALID_EVIDENCE_TYPES:
        raise ValueError(
            f"非法证据类型: {evidence_type!r}，合法值 {sorted(VALID_EVIDENCE_TYPES)}"
        )

    if evidence_type == "verify":
        if conf == "中" and verify_count >= 2:
            return {
                "confidence": "高",
                "status_change": None,
                "changed": True,
                "reason": f"中 + {verify_count} 次独立验证（≥2）→ 高",
            }
        return {
            "confidence": conf,
            "status_change": None,
            "changed": False,
            "reason": f"verify 不足以提升 {conf} 置信度",
        }

    # evidence_type == 'falsify'
    if conf == "中":
        return {
            "confidence": "低",
            "status_change": None,
            "changed": True,
            "reason": "单次证伪 中 → 低（不删除）",
        }
    if conf == "低":
        return {
            "confidence": "低",
            "status_change": "deprecated",
            "changed": True,
            "reason": "低置信度再被证伪 → deprecated",
        }
    # conf == '高'
    return {
        "confidence": "低",
        "status_change": None,
        "changed": True,
        "reason": "单次证伪 高 → 低",
    }
