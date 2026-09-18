# Dashboard 与小满解耦方案（方案一）

> 日期：2026-09-10 | 状态：✅ 已实施完成
> 目标：Dashboard 与小满 Agent 完全解耦——Agent 内嵌独立 HTTP API（端口 8020），Dashboard 通过 httpx 反向代理调用，双方不再共享 agent.db 文件，可独立启动/关闭。
> 来源：CHAT.md §1

## 一、背景与问题

### 1.1 现状

改前 Dashboard 和 Agent 通过**共享本地 SQLite 文件（agent.db）**通信，严重耦合：

- Dashboard `api_agent.py` 直接 `import agent.db` 读 agent.db，两个进程通过本地文件耦合
- 一方未启动则 Dashboard 报错（agent.db 不存在）
- 无法支持"小满进程单独在另一台机器运行"的场景

### 1.2 目标

- Agent 进程内嵌 HTTP API，所有对外接口通过 HTTP 暴露
- Dashboard 通过 httpx 反向代理到 Agent API，不再直接读 agent.db
- Agent 不可达时返回优雅降级状态（offline），不报错
- 双方可独立启动/关闭，可部署在不同机器

## 二、架构设计

```
┌─────────────────────┐         HTTP (httpx)         ┌─────────────────────┐
│   Dashboard 进程    │ ────────────────────────────> │   Agent 进程         │
│   (FastAPI :8000)   │ <- 反向代理 JSON 响应         │   (FastAPI :8020)   │
│                     │                              │   + 状态机 tick      │
│  api_agent.py       │   AGENT_API_URL              │   + 调度引擎         │
│  (反向代理到 Agent) │   AGENT_API_KEY (X-Api-Key)  │  api.py              │
│                     │   Agent 不可达 → offline      │  (内嵌 HTTP API)     │
└─────────────────────┘                              └─────────────────────┘
                              │
                         云库 Supabase（双方共享数据源）
```

关键原则：

- **Agent 进程**：内嵌 FastAPI（`agent/api.py`），监听 8020 端口，提供完整 API（状态/介绍页/会话/通知/素材源/文章/调度任务执行）
- **Dashboard 进程**：`api_agent.py` 从 `import agent.db` 改为 httpx 反向代理，`_proxy_get/_proxy_post/_proxy_delete` 封装
- **认证**：通过 `AGENT_API_KEY` 环境变量做 API Key 认证（`X-Api-Key` 头），Dashboard 请求时自动携带
- **降级**：Agent 不可达时返回预定义的 offline 结构，不报错、不抛异常

## 三、实施详情

### 3.1 Agent API（agent/api.py）— 新建

Agent 内嵌 FastAPI HTTP 服务，实现全部 `/api/agent/*` 路由：

| 模块 | 路由 | 方法 | 说明 |
|------|------|------|------|
| 状态 | `/api/agent/status` | GET | 角色在线状态、心跳、当前状态 |
| 介绍页 | `/api/agent/profile` | GET | persona、活动、文章、阅读、社交平台 |
| 活动 | `/api/agent/activities` | GET | 分页活动列表 |
| 上线/下线 | `/api/agent/online`、`/offline` | POST | 切换是否在线 |
| 状态切换 | `/api/agent/state` | POST | random/reading/slack 手动切换 |
| 提示/待办 | `/api/agent/notices` 系列 | GET/POST | 通知列表、已读、回复 |
| 会话 | `/api/agent/sessions` 系列 | GET/POST/DELETE | 会话 CRUD + SSE 聊天 |
| 素材源 | `/api/agent/sources` 系列 | GET/POST/DELETE | 素材源管理 |
| 文章 | `/api/agent/articles` | GET | 文章列表和详情 |
| 调度执行 | `/api/agent/scheduler/run/{task_id}` | POST | 接收 Dashboard 派发执行调度任务 |
| 调度状态 | `/api/agent/scheduler/status` | GET | 查询 Agent 侧调度状态 |

API Key 认证逻辑（`agent/api.py:27-31`）：
```python
def verify_api_key(key: str | None = Depends(api_key_header)):
    if not API_KEY:
        return
    if key != API_KEY:
        raise HTTPException(401, "Invalid API Key")
```

### 3.2 Agent 启动改造（agent/__main__.py）— 已改

- 强制 `AGENT_DB_BACKEND=cloud`（Agent 独立运行不再支持 file 模式）
- 启动时同时拉起 HTTP API daemon 线程：
```python
api_thread = threading.Thread(target=_start_api, daemon=True, name="agent-api")
api_thread.start()
```

### 3.3 Dashboard 反向代理（dashboard/api_agent.py）— 重写

从直接 `import agent.db` 改为 httpx 反向代理：

```python
AGENT_API_URL = os.environ.get("AGENT_API_URL", "http://127.0.0.1:8020").rstrip("/")
AGENT_API_KEY = os.environ.get("AGENT_API_KEY", "").strip()
_http = httpx.Client(
    timeout=_DEFAULT_TIMEOUT,
    headers={"X-Api-Key": AGENT_API_KEY} if AGENT_API_KEY else {},
)
```

代理方法封装：
- `_proxy_get(path, params)` — GET 代理，失败返回 None
- `_proxy_post(path, body)` — POST 代理，失败返回 None
- `_proxy_delete(path)` — DELETE 代理，失败返回 None

每个路由处理返回 None 时返回优雅降级结构（如 status/offline、空列表等）。

SSE 聊天消息转发（`api_agent.py:256-274`）：
```python
@router.post("/sessions/{sid}/messages")
async def chat_message(sid: int, request: Request):
    body = await request.json()
    async def event_gen():
        try:
            async with httpx.AsyncClient(...) as client:
                async with client.stream("POST", _agent_url(f"/sessions/{sid}/messages"), json=body) as r:
                    async for chunk in r.aiter_text():
                        yield chunk
        except Exception as e:
            yield f"data: {json.dumps({'error': f'Agent 不可达: {e}'}, ...)}\n\n"
    return StreamingResponse(event_gen(), media_type="text/event-stream")
```

### 3.4 环境变量配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AGENT_API_PORT` | 8020 | Agent API 监听端口 |
| `AGENT_API_KEY` | (空) | API Key 认证密钥 |
| `AGENT_API_URL` | `http://127.0.0.1:8020` | Dashboard 连接 Agent 的地址 |

`start_all.ps1` 中添加：
```powershell
$env:AGENT_API_PORT = "8020"
$env:AGENT_API_KEY = "..."
```

### 3.5 Dashboard 启动改造（dashboard/app.py）— 已改

- 删除 `agent.db.init_db()` 调用（不再直接依赖 agent.db）
- 后续挂载 tickets_router（方案三）

## 四、文件变更清单

| 文件 | 状态 | 说明 |
|------|------|------|
| `agent/api.py` | 新建 | Agent 内嵌 FastAPI HTTP 服务（572 行） |
| `agent/__main__.py` | 已改 | 强制 cloud 模式 + 启动 API daemon 线程 |
| `dashboard/api_agent.py` | 重写 | 从直接读 agent.db 改为 httpx 反向代理（336 行） |
| `dashboard/app.py` | 已改 | 删除 agent.db init 调用 |
| `scripts/start_all.ps1` | 已改 | 添加 AGENT_API_PORT + AGENT_API_KEY |
| `.env` | 已改 | 添加 AGENT_API_PORT、AGENT_API_KEY、AGENT_API_URL |

## 五、验收标准

1. Dashboard 单独启动：Agent API 路由返回 offline 状态，不报错
2. Agent 单独启动：状态机 + 调度器正常运行，HTTP API 可访问
3. 双方同时启动：Dashboard 正确展示 Agent 状态、会话、文章等数据
4. Agent 停止后 Dashboard 降级展示 offline，不崩溃
5. 可配置 AGENT_API_URL 指向远程 Agent（不同机器）
