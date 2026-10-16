"""dashboard/api_tickets.py — 工单管理 API 路由（后台）

直接读云库 public.tickets 表（数据由 Agent 进程写入），不经过 Agent 代理。
2026-10-15 解耦：原实现依赖 agent.db（agent 运行时已外迁至 ~/.dsh），
改为直接消费 Dashboard 侧共享的 cloud_db（同一云库 tickets 表），
云库不可用时降级返回空列表，不再 import agent 包。
"""

import os

from fastapi import APIRouter, Depends, HTTPException, Query

from dashboard.auth import get_current_user

router = APIRouter(prefix="/api/tickets", dependencies=[Depends(get_current_user)])

_TICKET_COLS = "id,kind,title,description,severity,status,source_task,assignee,created_at,updated_at,result,log_entries"

# 允许的筛选枚举（与 agent 侧写入口径一致）
_KINDS = ("bug", "req")
_SEVERITIES = ("p0", "p1", "p2", "p3")
_STATUSES = ("open", "analyzing", "in_progress", "needs_human", "resolved", "closed")


def _cloud() -> "object | None":
    """返回 cloud_db 模块；云库不可用/未启用时返回 None。"""
    try:
        import cloud_db

        if not cloud_db.enabled():
            return None
        return cloud_db
    except Exception:
        return None


@router.get("")
def list_tickets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    kind: str | None = Query(None),
    severity: str | None = Query(None),
    status: str | None = Query(None),
):
    cd = _cloud()
    if cd is None:
        return {"tickets": [], "total": 0, "page": page, "page_size": page_size,
                "total_pages": 0, "source": "unavailable"}

    filters = []
    if kind in _KINDS:
        filters.append(("kind", "eq", kind))
    if severity in _SEVERITIES:
        filters.append(("severity", "eq", severity))
    if status in _STATUSES:
        filters.append(("status", "eq", status))

    try:
        total = len(cd.select("tickets", columns="id", filters=filters or None) or [])
        offset = (page - 1) * page_size
        items = cd.select(
            "tickets",
            columns=_TICKET_COLS,
            filters=filters or None,
            order="created_at.desc",
            limit=page_size,
            offset=offset,
        ) or []
    except Exception:
        return {"tickets": [], "total": 0, "page": page, "page_size": page_size,
                "total_pages": 0, "source": "error"}

    return {
        "tickets": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max((total + page_size - 1) // page_size, 0),
        "source": "cloud",
    }


@router.get("/{ticket_id}")
def get_ticket(ticket_id: str):
    cd = _cloud()
    if cd is None:
        raise HTTPException(503, "云库不可用")
    t = cd.select_one("tickets", filters=[("id", "eq", ticket_id)])
    if not t:
        raise HTTPException(404, "工单不存在")
    return t


@router.post("/{ticket_id}/retrigger")
def retrigger_ticket(ticket_id: str):
    import requests as req

    cd = _cloud()
    if cd is None:
        raise HTTPException(503, "云库不可用")
    t = cd.select_one("tickets", filters=[("id", "eq", ticket_id)])
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
