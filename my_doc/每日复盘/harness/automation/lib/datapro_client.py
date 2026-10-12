"""
datapro_client.py — 火山引擎专业数据集（DataPro）客户端（2026-09-24）

DataPro 是 Agent Plan 的金融数据库能力（HTTP Streamable MCP）：
  endpoint: https://datapro.hqd.cn-beijing.volces.com/mcp
  认证:     X-Agent-Plan-Key header（Agent Plan 专属 Key）
  工具:     dataPro_search（语义查询金融数据：财务/日频行情/技术形态/盈利预测）

定位：a-stock-data（实时行情）的**补充/备源**。DataPro 数据是**日频**，
不能替代 mootdx/腾讯的实时行情，但可补充日频财务指标/技术形态查询。

用法：
  from lib.datapro_client import datapro_search
  items = datapro_search("002594 ROE 盈利水平")   # 返回 items 列表

环境变量：
  AGENT_PLAN_KEY: Agent Plan 专属 API Key（未配置时 datapro_search 返回 None + 警告）
  DATAPRO_ENDPOINT: 覆盖默认 endpoint（测试用）
"""

import json
import os
from pathlib import Path

DEFAULT_ENDPOINT = "https://datapro.hqd.cn-beijing.volces.com/mcp"
TOOL_NAME = "dataPro_search"


def _agent_plan_key() -> str:
    return os.environ.get("AGENT_PLAN_KEY", "").strip()


def is_available() -> bool:
    """DataPro 是否可调用（已配置 Agent Plan Key）。"""
    return bool(_agent_plan_key())


def _headers() -> dict:
    key = _agent_plan_key()
    if not key:
        return {}
    return {"X-Agent-Plan-Key": key}


def datapro_search(query: str, limit: int | None = None) -> list | None:
    """调用 dataPro_search 工具查询金融数据。

    返回 items 列表；未配置 Key / 调用失败 → None（调用方降级到 a-stock-data）。
    """
    if not is_available():
        return None
    try:
        import mcp
        from mcp.client.streamable_http import streamablehttp_client
        from mcp.client.session import ClientSession

        endpoint = os.environ.get("DATAPRO_ENDPOINT", DEFAULT_ENDPOINT)
        headers = _headers()

        async def _run():
            async with streamablehttp_client(endpoint, headers=headers) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        TOOL_NAME, {"query": query}
                    )
                    return _parse_result(result)

        import asyncio
        return asyncio.run(_run())
    except Exception as e:
        # 失败不抛错（备源语义），由调用方决定降级
        print(f"[datapro] 调用失败，降级到 a-stock-data: {e}")
        return None


def _parse_result(result) -> list | None:
    """解析 MCP call_tool 结果 → items 列表。"""
    try:
        if result is None:
            return None
        if getattr(result, "isError", False):
            return None
        # text 内容通常是 JSON 字符串
        for content in getattr(result, "content", []) or []:
            text = getattr(content, "text", None)
            if not text:
                continue
            try:
                data = json.loads(text)
            except (ValueError, TypeError):
                continue
            items = data.get("items") if isinstance(data, dict) else None
            if isinstance(items, list):
                return items
        return None
    except Exception:
        return None


# ── 直连 HTTP 兜底（不依赖 mcp SDK，走 streamable HTTP JSON-RPC）─────────────
def datapro_search_http(query: str) -> list | None:
    """无 mcp SDK 时的直连兜底：HTTP Streamable MCP initialize + tools/call。

    需要 requests/httpx。返回 items 列表或 None。
    """
    if not is_available():
        return None
    import requests

    endpoint = os.environ.get("DATAPRO_ENDPOINT", DEFAULT_ENDPOINT)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **_headers(),
    }
    try:
        # initialize
        r = requests.post(endpoint, headers=headers,
                          json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                "params": {"protocolVersion": "2024-11-05",
                                           "capabilities": {}, "clientInfo": {"name": "astock-datapro", "version": "0.1.0"}}},
                          timeout=15)
        # 初始化响应（可能带 session header）
        sess = r.headers.get("mcp-session-id")
        if sess:
            headers["mcp-session-id"] = sess
        # 通知 initialized
        requests.post(endpoint, headers=headers,
                      json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                      timeout=15)
        # 调用工具
        r2 = requests.post(endpoint, headers=headers,
                           json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                 "params": {"name": TOOL_NAME, "arguments": {"query": query}}},
                           timeout=30)
        data = r2.json()
        result = data.get("result", {})
        for content in result.get("content", []) or []:
            text = content.get("text", "")
            if text:
                try:
                    parsed = json.loads(text)
                except (ValueError, TypeError):
                    continue
                items = parsed.get("items") if isinstance(parsed, dict) else None
                if isinstance(items, list):
                    return items
        return None
    except Exception as e:
        print(f"[datapro] HTTP 直连失败: {e}")
        return None
