"""dashboard/api_tickets.py — 工单管理 API 路由（后台）

直接读云库 public.tickets 表（数据由 Agent 进程写入），不经过 Agent 代理。
"""

import os

os.environ.setdefault("AGENT_DB_BACKEND", "cloud")

from fastapi import APIRouter, Depends, HTTPException, Query

from dashboard.auth import get_current_user
from agent import db as agent_db

router = APIRouter(prefix="/api/tickets", dependencies=[Depends(get_current_user)])


@router.get("")
def list_tickets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    kind: str | None = Query(None),
    severity: str | None = Query(None),
    status: str | None = Query(None),
):
    filters = {}
    if kind and kind in ("bug", "req"):
        filters["kind"] = kind
    if severity and severity in ("p0", "p1", "p2", "p3"):
        filters["severity"] = severity
    if status and status in (
        "open",
        "analyzing",
        "in_progress",
        "needs_human",
        "resolved",
        "closed",
    ):
        filters["status"] = status

    total = agent_db.ticket_count(**filters)
    offset = (page - 1) * page_size
    items = agent_db.ticket_list(limit=page_size, offset=offset, **filters)

    return {
        "tickets": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max((total + page_size - 1) // page_size, 0),
    }


@router.get("/{ticket_id}")
def get_ticket(ticket_id: str):
    t = agent_db.ticket_get(ticket_id)
    if not t:
        raise HTTPException(404, "工单不存在")
    return t


@router.post("/{ticket_id}/retrigger")
def retrigger_ticket(ticket_id: str):
    import os, requests as req

    t = agent_db.ticket_get(ticket_id)
    if not t:
        raise HTTPException(404, "工单不存在")

    source_task = t.get("source_task", "")
    if not source_task:
        return {
            "started": False,
            "reason": "no_source_task",
            "message": "该工单无关联调度任务",
        }

    agent_url = os.environ.get("AGENT_API_URL", "http://127.0.0.1:8020").rstrip("/")
    agent_key = os.environ.get("AGENT_API_KEY", "").strip()
    headers = {"X-Api-Key": agent_key} if agent_key else {}

    try:
        r = req.post(
            f"{agent_url}/api/agent/scheduler/run/{source_task}",
            json={"trigger": "manual"},
            headers=headers,
            timeout=10,
        )
        result = r.json()
    except Exception as e:
        return {"started": False, "reason": "agent_unreachable", "message": str(e)}

    return result
