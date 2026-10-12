#!/usr/bin/env python3
"""fetch_joinquant_strategy.py — 聚宽策略帖源码拉取与转化工作单生成（路径 B1）。

从聚宽社区抓取单篇策略帖的完整正文，提取策略源码 / 逻辑描述 / 元信息，
输出**策略转化工作单**（YAML），供 `quant-strategy-discovery` 方法论转化到
本地 `etf-strategies` 回测框架。

与 `fetch_joinquant_forum.py` 的分工：
- forum：抓**列表**（多帖，供 strategy_scan_weekly 筛 ETF 候选）
- strategy：抓**单帖详情**（detailV2，含完整源码/逻辑，供人工+LLM 转化）

关键事实（2026-10 实测）：
- detailV2 匿名可用（无需登录），返回完整正文 Markdown（含 ```python 代码块）
- 帖子质量参差：
  - 公开策略帖：content 含完整可运行源码（如 S4 来源 post/26142）
  - 思路分享帖：content 只有中文逻辑描述（选股/择时规则），无完整代码
  - 引流帖：content 只有摘要，源码需积分/克隆（detailV2 仍只给摘要）
- 工具尽力提取（代码块 + 代码块外正文），无法提取完整代码时明确标注，
  由转化方（LLM/人）基于逻辑描述实现

用法：
    python etf-strategies/automation/scripts/fetch_joinquant_strategy.py <postId|url>
    python etf-strategies/automation/scripts/fetch_joinquant_strategy.py <postId> --json
    python etf-strategies/automation/scripts/fetch_joinquant_strategy.py <postId> --save-dir out/

输出：YAML（默认）或 JSON（--json）的策略转化工作单：
  - 元信息（标题/作者/backtestId/克隆数/浏览/点赞/收藏/时间）
  - 源码块列表（含语言标记）
  - 逻辑描述（代码块外正文）
  - 转化提示（是否已入库/适合性粗判/JoinQuant→本地映射提醒）
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "https://www.joinquant.com"
DETAIL_URL = BASE_URL + "/community/post/detailV2"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/plain, */*",
    "Referer": BASE_URL + "/view/community/",
}

# 本地已有策略库（strategy_kb 已转化），转化工作单标注防重复
LOCAL_STRATEGY_MARKERS = [
    "添油加醋",        # S18 RSRS增强反转动量 @hayy
    "多资产动量",      # S4
    "三因子",          # S8
    "动态波动率",      # S14
    "趋势过滤",        # S15
    "金丝雀",          # S16/17
    "低相关",          # S19
]


def extract_post_id(arg):
    """从参数解析 postId：接受裸 postId（hex 或纯数字）或详情 URL。"""
    arg = arg.strip()
    m = re.search(r"/view/community/detail/([0-9a-f]{24,40}|\d+)", arg)
    if m:
        return m.group(1)
    if re.fullmatch(r"[0-9a-f]{24,40}|\d+", arg):
        return arg
    return None


def fetch_detail(post_id):
    """拉取 detailV2 完整帖子数据。返回 dict（失败抛异常）。"""
    import requests

    r = requests.get(
        DETAIL_URL,
        headers=HEADERS,
        params={"postId": post_id},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if (data.get("code") or "") != "00000":
        raise RuntimeError(f"聚宽接口返回异常: {data.get('msg') or data.get('code')}")
    return data.get("data") or {}


def extract_blocks(content):
    """提取 Markdown 代码块。返回 [{'lang','code'}]。"""
    blocks = []
    for m in re.finditer(r"```(\w*)\s*\n(.*?)```", content or "", re.S):
        lang = (m.group(1) or "text").strip().lower()
        code = m.group(2).strip("\n")
        if code.strip():
            blocks.append({"lang": lang, "code": code})
    return blocks


def extract_prose(content, blocks):
    """提取代码块外的正文（逻辑描述）。"""
    prose = content or ""
    for b in blocks:
        # 移除对应代码块（用原始反引号围栏匹配）
        prose = re.sub(r"```\w*\s*\n" + re.escape(b["code"]) + r"\n```", "", prose, count=1)
    # 清理空行/多余换行
    prose = re.sub(r"\n{3,}", "\n\n", prose).strip()
    return prose


def guess_etf_relevance(title, prose, blocks):
    """粗判是否 ETF/指数可转化（本地框架只有 ETF 数据）。
    返回 {"etf_likely": bool, "reasons": [...]}。
    """
    text = f"{title}\n{prose}\n" + "\n".join(b["code"] for b in blocks)
    etf_hits = [kw for kw in
                ("ETF", "etf", "指数", "轮动", "宽基", "纳指", "沪深300", "中证500",
                 "创业板", "上证180", "红利", "低波") if kw in text]
    stock_hits = [kw for kw in ("选股", "股票池", "个股", "成分股", "白马", "小市值",
                                "股息率", "涨停") if kw in text]
    reasons = []
    if etf_hits:
        reasons.append(f"含ETF/指数关键词: {etf_hits[:5]}")
    if stock_hits:
        reasons.append(f"含个股选股关键词: {stock_hits[:5]}（本地框架仅ETF，需适配或跳过）")
    return {
        "etf_likely": bool(etf_hits) and not bool(stock_hits),
        "mixed": bool(etf_hits) and bool(stock_hits),
        "reasons": reasons,
    }


def already_in_local(title):
    """粗查本地是否已有同源策略（标题含标记）。"""
    hits = [m for m in LOCAL_STRATEGY_MARKERS if m in title]
    return hits


def build_work_order(post_id, data):
    """组装策略转化工作单。"""
    content = data.get("content") or ""
    blocks = extract_blocks(content)
    prose = extract_prose(content, blocks)
    title = (data.get("title") or "").strip()
    author = ((data.get("author") or {}).get("alias")) if isinstance(data.get("author"), dict) else None
    if not author and isinstance(data.get("user"), dict):
        author = (data.get("user") or {}).get("alias")
    tags = [t.get("name") for t in (data.get("tagInfo") or []) if t.get("name")]

    relevance = guess_etf_relevance(title, prose, blocks)
    local_hits = already_in_local(title)

    # 转化建议
    notes = []
    py_blocks = [b for b in blocks if b["lang"] in ("python", "py", "")]
    if py_blocks and max(len(b["code"]) for b in py_blocks) > 500:
        notes.append("含较长 Python 源码块 → 可直接读取策略逻辑转化")
    elif blocks:
        notes.append("有代码块但以逻辑描述为主 → 需按逻辑描述实现")
    else:
        notes.append("无代码块 → 仅摘要/描述，可能需登录克隆获取完整源码")
    if local_hits:
        notes.append(f"⚠️ 标题含本地已有策略标记 {local_hits}，可能已转化过，先核对 strategy_kb")
    if not relevance["etf_likely"]:
        notes.append("⚠️ 可能非 ETF 纯策略（本地框架仅 ETF 数据），需评估适配性")
    if data.get("backtestId"):
        notes.append(f"帖子关联回测 backtestId={data.get('backtestId')}（可后续拉 backtest summary 核对原始指标）")

    return {
        "post_id": post_id,
        "url": f"{BASE_URL}/view/community/detail/{post_id}",
        "title": title,
        "author": author or "",
        "tags": tags,
        "add_time": data.get("addTime") or "",
        "meta": {
            "view_count": data.get("viewCount") or 0,
            "reply_count": data.get("replyCount") or 0,
            "like_count": data.get("likeCount") or 0,
            "collection_count": data.get("collectionCount") or 0,
            "backtest_id": data.get("backtestId") or "",
            "backtest_name": data.get("backtestName") or "",
            "backtest_clone_count": data.get("backtestCloneCount") or 0,
            "notebook_clone_count": data.get("notebookCloneCount") or 0,
        },
        "code_blocks": blocks,
        "logic_prose": prose[:4000],
        "relevance": relevance,
        "conversion_notes": notes,
    }


def _yaml_dump(obj, indent=0):
    """极简 YAML 序列化（避免依赖 PyYAML；结构：str/int/list/dict 嵌套）。"""
    pad = "  " * indent
    lines = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                lines.append(f"{pad}{k}:")
                lines.append(_yaml_dump(v, indent + 1))
            else:
                lines.append(f"{pad}{k}: {json.dumps(str(v), ensure_ascii=False)}")
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, (dict, list)):
                lines.append(f"{pad}-")
                lines.append(_yaml_dump(v, indent + 1))
            else:
                lines.append(f"{pad}- {json.dumps(str(v), ensure_ascii=False)}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="拉取聚宽策略帖详情并生成转化工作单")
    ap.add_argument("post", help="postId 或详情 URL")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非 YAML")
    ap.add_argument("--save-dir", default=None, help="若指定，把工作单存为文件")
    args = ap.parse_args()

    post_id = extract_post_id(args.post)
    if not post_id:
        print(f"无法解析 postId: {args.post!r}（应为 24 位 hex 或聚宽详情 URL）", file=sys.stderr)
        return 2

    try:
        data = fetch_detail(post_id)
    except Exception as e:
        print(f"拉取失败: {e}", file=sys.stderr)
        return 1

    wo = build_work_order(post_id, data)
    out_text = json.dumps(wo, ensure_ascii=False, indent=2) if args.json else _yaml_dump(wo)

    if args.save_dir:
        d = Path(args.save_dir)
        d.mkdir(parents=True, exist_ok=True)
        ext = "json" if args.json else "yaml"
        path = d / f"jq_{post_id[:12]}.{ext}"
        path.write_text(out_text, encoding="utf-8")
        print(f"工作单已保存: {path}")
        print(out_text)
    else:
        print(out_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
