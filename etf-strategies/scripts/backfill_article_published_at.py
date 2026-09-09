"""backfill_article_published_at.py — 一次性回填 agent_articles.published_at 为 NULL 的行.

背景（2026-09-08）：云迁移后 agent_articles.published_at 因无 DEFAULT + article_create
云分支未传该列而全部为 NULL，导致"我的动态"不显示发文时间。本文修复了 article_create，
本脚本用于把存量 NULL 行回填为合理时间：

- kind=article（长文）：匹配 "📝 写文章" 活动台账（behavior.run_publish_pipeline 的
  _finish_writing note 形如 "完成：{title}"）→ 用该活动的 ended_at（精确发文时刻）。
- kind=post（动态）：title 即发文日期（如 "2026-09-08"）→ 取当天最近一条
  "📖 阅读" 活动的 ended_at（动态由阅读会话产生，同一会话动态集中在结束时刻）。
- 仍无法匹配的行：按行 id 顺序在当天 09:00–17:30 内均匀摊开（尽力近似，保序）。

幂等：只更新 published_at IS NULL 的行；可重复执行。
"""

import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from load_env import load_env_file  # noqa: E402

load_env_file()

from cloud_db import select, update  # noqa: E402

READ_KINDS = {"reading", "writing"}


def _parse_dt(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19].replace("T", " "), fmt)
        except ValueError:
            continue
    return None


def main():
    articles = select(
        "agent_articles", columns="id,kind,title,published_at", order="id.asc"
    )
    pending = [a for a in articles if not a.get("published_at")]
    if not pending:
        print("无需回填：没有 published_at 为 NULL 的文章")
        return

    acts = select(
        "agent_activities", columns="id,kind,label,started_at,ended_at,note", order="id.asc"
    )
    writing_by_title = {}
    reading_by_date = defaultdict(list)  # date -> [ended_at str]
    for a in acts:
        if a.get("kind") == "writing" and a.get("ended_at"):
            note = (a.get("note") or "")
            # note 形如 "完成：{title}" 或 "标题：{title}"
            for prefix in ("完成：", "标题："):
                if note.startswith(prefix):
                    writing_by_title[note[len(prefix):].strip()] = a["ended_at"]
                    break
        elif a.get("kind") == "reading" and a.get("ended_at"):
            dt = _parse_dt(a["ended_at"])
            if dt:
                reading_by_date[dt.date().isoformat()].append(a["ended_at"])

    now = datetime.now()
    updated = 0
    for art in pending:
        aid, kind, title = art["id"], art["kind"], (art["title"] or "").strip()
        ts = None
        if kind == "article" and title in writing_by_title:
            ts = writing_by_title[title]
        elif kind == "post":
            date_key = title[:10]
            if date_key in reading_by_date:
                # 该日期阅读会话的结束时刻列表（升序）→ 取最近一次
                ts = reading_by_date[date_key][-1]
        if not ts:
            # 兜底：按 id 在当天 09:00-17:30 内摊开（保序近似）
            date_key = (title[:10] if kind == "post" else now.strftime("%Y-%m-%d"))
            base = _parse_dt(date_key) or now
            n = len(pending)
            idx = pending.index(art)
            span = (17 * 60 + 30) - (9 * 60)
            minutes = 9 * 60 + (span * idx // max(n, 1))
            ts = (base.replace(hour=0, minute=0, second=0)
                  + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
        if ts:
            update("agent_articles", {"published_at": ts}, filters=[("id", "eq", aid)])
            updated += 1
            print(f"  id={aid} kind={kind} title={title[:24]!r} -> {ts}")
        else:
            print(f"  id={aid} SKIP (无可用时间)")

    print(f"\n回填完成：{updated}/{len(pending)} 行已更新")


if __name__ == "__main__":
    main()
