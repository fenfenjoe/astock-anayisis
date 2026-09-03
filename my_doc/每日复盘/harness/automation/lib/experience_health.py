"""
经验库健康检查核心逻辑 — REQ-005

从 auto_experience_health 的大小检查 / 章节完整性检查 / 过时检测（数据源断供）
提取为可复用纯函数，供 auto_experience_health 任务复用，并支撑 REQ-005 的
压缩重组回归验证。

纯计算函数，不读写磁盘（调用方负责读取文件内容后传入字符串）。
"""

# ============================================================
# 常量
# ============================================================

# 投资经验.md 必需章节（与 auto_experience_health 第五步 5.1 保持一致
# + 后续由 REQ-003/REQ-004 新增的章节）
REQUIRED_SECTIONS = [
    "市场判断",
    "跨市场映射",
    "开盘前评估",
    "数据纪律",
    "早盘纪律设计",
    "策略纪律",
    "宏观数据公布日",
    "超跌反弹",
    "信号设计",
    "板块机会扫描",
    "全市场异动扫描（行业/题材版）",
]

# 行数强制合并线（>500 需压缩）与警告线
LINE_LIMIT = 500
LINE_WARNING = 300

# 北向数据断供降级路径标注标记（条目内包含该标记即视为已标注）
NORTHBOUND_ANNOTATION_MARKER = "北向数据断供降级"

# 北向依赖关键词（任一出现即视为该条目依赖北向数据）
NORTHBOUND_KEYWORDS = ("北向", "北向资金", "北向净")


# ============================================================
# 行数检查
# ============================================================

def count_lines(content: str) -> int:
    """统计文本行数（与 wc -l 口径一致：按换行符切分，空行计 1 行）。"""
    if not content:
        return 0
    return len(content.splitlines())


def check_line_limit(content: str, limit: int = LINE_LIMIT) -> tuple:
    """检查行数是否超过限制。

    Returns:
        (within_limit: bool, line_count: int)
        within_limit=True 表示行数 <= limit。
    """
    n = count_lines(content)
    return (n <= limit, n)


# ============================================================
# 重复章节头检测
# ============================================================

def find_duplicate_headers(content: str) -> list:
    """找出重复出现的章节头（## 级别，## 后首个非空字符开始匹配完整标题）。

    Returns:
        list[str] — 去重后的重复标题列表（按首次出现顺序）。
    """
    seen = {}
    dupes = []
    for line in content.splitlines():
        if line.startswith("## ") and not line.startswith("### "):
            header = line[3:].strip()
            if header in seen and header not in dupes:
                dupes.append(header)
            seen[header] = True
    return dupes


# ============================================================
# 必需章节存在性
# ============================================================

def check_required_sections(content: str, required: list = None) -> list:
    """检查必需章节是否存在。

    Args:
        content: 经验文件内容
        required: 必需章节标题列表（默认 REQUIRED_SECTIONS）

    Returns:
        list[str] — 缺失章节列表（空列表 = 全部存在）。
    """
    if required is None:
        required = REQUIRED_SECTIONS
    headers = []
    for line in content.splitlines():
        if line.startswith("## ") and not line.startswith("### "):
            headers.append(line[3:].strip())
    return [s for s in required if s not in headers]


# ============================================================
# 北向断供标注缺失检测
# ============================================================

def find_unannotated_northbound_entries(
    content: str,
    marker: str = NORTHBOUND_ANNOTATION_MARKER,
    keywords: tuple = NORTHBOUND_KEYWORDS,
) -> list:
    """找出依赖北向数据但未标注断供降级路径的条目。

    以 ### 条目为单位扫描：条目头或条目正文引用北向关键词、但未包含
    降级标注标记 marker 的，返回其标题行号列表（1 起始，升序）。
    <details> 折叠备份区（bullet 形式）不参与条目解析。

    Args:
        content: 经验文件内容
        marker: 断供降级标注标记（默认 NORTHBOUND_ANNOTATION_MARKER）
        keywords: 北向依赖关键词元组

    Returns:
        list[int] — 未标注条目所在行号（升序）。
    """
    lines = content.splitlines()
    unannotated = []
    current_header_idx = None
    current_block = []
    in_details = False

    def _flush():
        nonlocal current_block, current_header_idx
        if current_header_idx is not None and current_block:
            block_text = "\n".join(current_block)
            has_north = any(k in block_text for k in keywords)
            has_marker = marker in block_text
            if has_north and not has_marker:
                unannotated.append(current_header_idx)
        current_block = []
        current_header_idx = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "<details>":
            in_details = True
            _flush()
            continue
        if stripped == "</details>":
            in_details = False
            continue
        if in_details:
            continue
        if line.startswith("### "):
            _flush()
            current_header_idx = i + 1
            current_block = [line]
        elif line.startswith("## ") and not line.startswith("### "):
            _flush()
        elif current_header_idx is not None:
            current_block.append(line)
    _flush()
    return unannotated


# ============================================================
# 复合健康检查
# ============================================================

def check_experience_health(content: str, required: list = None) -> dict:
    """复合健康检查（供 auto_experience_health 复用）。

    Returns:
        {
            'line_count', 'line_limit', 'within_limit',
            'duplicate_headers', 'missing_sections',
            'unannotated_northbound_entries', 'healthy'
        }
    """
    line_count = count_lines(content)
    within_limit, _ = check_line_limit(content)
    dupes = find_duplicate_headers(content)
    missing = check_required_sections(content, required)
    unannotated_north = find_unannotated_northbound_entries(content)
    return {
        "line_count": line_count,
        "line_limit": LINE_LIMIT,
        "within_limit": within_limit,
        "duplicate_headers": dupes,
        "missing_sections": missing,
        "unannotated_northbound_entries": unannotated_north,
        "healthy": (
            within_limit
            and not dupes
            and not missing
            and not unannotated_north
        ),
    }
