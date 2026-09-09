"""agent/db.py — 拟人 Agent 数据持久化层（独立 agent.db，WAL）.

Tables
------
agent_sessions   聊天会话
agent_messages   消息（role/content/sources 引用来源）
agent_articles   文章（主动发文产出）
agent_opinions   观点库（主题/观点/关联文章）—「有独立见解」的持久化保障
agent_knowledge  知识条目（RSS/搜索素材；url 去重；consumed 消费标记）
agent_metadata   key-value（heartbeat / 每日发文状态）

设计：与 dashboard/db.py 同模式（get_conn + WAL + foreign_keys）。
多进程（dashboard + agent 常驻）共用同一 db 文件安全（WAL 短事务）。
"""

import difflib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from agent import config

_DB_PATH = config.DB_PATH

# ── 云端权威数据库后端（AGENT_DB_BACKEND=cloud 时启用）：
#    所有 CRUD 直接读写火山 Supabase Postgres（PostgREST Data API），
#    替代本地 SQLite 权威存储 → 跨机器/多进程天然一致。
#    2026-09-07 移除 DB_MODE=memory（TOS 快照互覆机制），仅保留 file/cloud 两后端。
USE_CLOUD = os.environ.get("AGENT_DB_BACKEND", "").lower() == "cloud"

if USE_CLOUD:
    try:
        from cloud_db import (
            delete as _cd_delete,
            enabled as _cd_enabled,
            insert as _cd_insert,
            q as _cd_q,
            select as _cd_select,
            select_one as _cd_select_one,
            update as _cd_update,
            upsert as _cd_upsert,
        )
    except ImportError:
        USE_CLOUD = False
else:
    # 测试可动态把 USE_CLOUD 置 True；此处总是尝试导入，供测试 fixture 使用
    try:
        from cloud_db import (
            delete as _cd_delete,
            enabled as _cd_enabled,
            insert as _cd_insert,
            q as _cd_q,
            select as _cd_select,
            select_one as _cd_select_one,
            update as _cd_update,
            upsert as _cd_upsert,
        )
    except ImportError:  # pragma: no cover
        _cd_delete = _cd_enabled = _cd_insert = _cd_q = None
        _cd_select = _cd_select_one = _cd_update = _cd_upsert = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    persona     TEXT NOT NULL DEFAULT 'xiaoman',
    title       TEXT NOT NULL DEFAULT '新会话',
    created_at  TEXT DEFAULT (datetime('now','localtime')),
    updated_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS agent_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,               -- user | assistant
    content     TEXT NOT NULL,
    sources     TEXT,                        -- JSON array [{title,url,fetched_at}]
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS agent_articles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    summary      TEXT,
    content      TEXT NOT NULL,
    topics       TEXT,                       -- JSON array
    sources      TEXT,                       -- JSON array
    status       TEXT NOT NULL DEFAULT 'published',  -- draft | published
    kind         TEXT NOT NULL DEFAULT 'article',    -- article=长文 | post=短动态
    published_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS agent_opinions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic       TEXT NOT NULL,
    opinion     TEXT NOT NULL,
    article_id  INTEGER,
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS agent_knowledge (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,              -- cls | wallstreetcn | zhihu | xueqiu | search | manual
    title        TEXT NOT NULL,
    url          TEXT NOT NULL UNIQUE,       -- 去重 key
    summary      TEXT,
    content      TEXT,
    viewpoint    TEXT,                       -- LLM 提取的核心观点（摘要级）
    emotion      TEXT,                       -- 小满读完后的情绪标签：excited|angry|curious|calm|skeptical
    memory       TEXT,                       -- 阅读记忆：LLM 生成的个人感受/联想（可跨会话检索）
    read_at      TEXT,                       -- 小满最后阅读该条目的时间
    published_at TEXT,                       -- 源发布时间
    consumed     INTEGER NOT NULL DEFAULT 0, -- 已被发文消费
    fetched_at   TEXT DEFAULT (datetime('now','localtime'))
); 

CREATE TABLE IF NOT EXISTS agent_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS agent_sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,                -- 站点/源名（或文章标题）
    url         TEXT NOT NULL,                -- 入口 URL（首页/栏目/单篇文章）
    kind        TEXT NOT NULL DEFAULT 'website',  -- website=常驻站点 | manual=手动喂单条
    note        TEXT,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS agent_activities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,                -- 事件/状态 id（reading/writing/tea/...）
    label       TEXT NOT NULL,                -- 展示名（含 emoji，如 📖 阅读 / 📝 写文章）
    source      TEXT NOT NULL DEFAULT 'auto', -- auto=自动 | manual=用户手动
    started_at  TEXT NOT NULL,                -- 开始时间（切换/开始执行时写入）
    ended_at    TEXT,                         -- 结束时间（完成/切换走时写入）
    note        TEXT,                         -- 备注（如：读了哪几篇 / 写了哪篇文章）
    tokens      INTEGER                       -- 该时段真实 token 用量（暂无通道 → NULL=未计量）
);

CREATE TABLE IF NOT EXISTS platform_cookies (
    platform_id TEXT PRIMARY KEY,             -- weibo | xhs
    cookie      TEXT NOT NULL,                -- 完整 Cookie 串（用户从浏览器复制）
    updated_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS platform_reachability (
    platform_id TEXT PRIMARY KEY,             -- weibo | xhs | x | zhihu | xueqiu
    reachable   INTEGER NOT NULL DEFAULT 0,   -- 0=不可达/未判定 1=可达
    checked_at  TEXT DEFAULT (datetime('now','localtime')),
    reason      TEXT                          -- 判定依据（无 Cookie / 探测失败 / 未实施访问逻辑…）
);

-- 提示/待办（REQ-002：聊天页「📌 提示与待办」；小满主动发，未读小红点 + 待办回复回调）
-- 待办状态机：open(未处理) → replied(已回复) → done(处理成功)；失败回 open 并记 result=失败原因；
--             dismissed=用户忽略（不再提示，不计未读）
CREATE TABLE IF NOT EXISTS agent_notices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,                -- notice=提示（不需回复） | todo=待办（需回复）
    status      TEXT NOT NULL DEFAULT 'open', -- open | replied | done | dismissed
    title       TEXT NOT NULL,                -- 短标题（列表项标题）
    content     TEXT NOT NULL,                -- 正文（提示/待办说明）
    todo_type   TEXT,                         -- 待办类型（回调 dispatch key；提示为 NULL）
    todo_data   TEXT,                         -- 待办负载 JSON（如 {"platform_id":"weibo"}）
    reply       TEXT,                         -- 用户回复内容（待办回复后记录）
    reply_at    TEXT,                         -- 回复时间
    result      TEXT,                         -- 小满处理结果（成功=小满回复；失败=失败原因）
    read_at     TEXT,                         -- 标记已读时间（NULL=未读；失败重置未处理时清空）
    source      TEXT,                         -- 生成来源（evening_review / agent / manual…）
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);
"""

_JSON_FIELDS = ("sources", "topics", "todo_data")


def init_db(db_path=None):
    """设置数据库路径并建表（幂等）。db_path=None 复位为默认路径。

    cloud 模式：仅校验云连接（不落本地文件）。
    """
    global _DB_PATH
    _DB_PATH = Path(db_path) if db_path else config.DB_PATH
    if USE_CLOUD:
        return  # 云表已由 schema 建好；连接由 cloud_db 惰性建立
    with get_conn():
        pass  # 建表 + 迁移在 get_conn 首次打开时执行


def _migrate(conn):
    """轻量列迁移（幂等）：老库补 kind / viewpoint / emotion / memory / read_at / result 列。"""
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(agent_articles)")]
    if "kind" not in cols:
        conn.execute(
            "ALTER TABLE agent_articles ADD COLUMN kind TEXT NOT NULL DEFAULT 'article'"
        )
    kcols = [r["name"] for r in conn.execute("PRAGMA table_info(agent_knowledge)")]
    for col, ddl in [
        ("viewpoint", "ALTER TABLE agent_knowledge ADD COLUMN viewpoint TEXT"),
        ("emotion", "ALTER TABLE agent_knowledge ADD COLUMN emotion TEXT"),
        ("memory", "ALTER TABLE agent_knowledge ADD COLUMN memory TEXT"),
        ("read_at", "ALTER TABLE agent_knowledge ADD COLUMN read_at TEXT"),
    ]:
        if col not in kcols:
            conn.execute(ddl)
    acols = [r["name"] for r in conn.execute("PRAGMA table_info(agent_activities)")]
    if "note" not in acols:
        conn.execute("ALTER TABLE agent_activities ADD COLUMN note TEXT")
    ncols = [r["name"] for r in conn.execute("PRAGMA table_info(agent_notices)")]
    if "result" not in ncols:
        conn.execute("ALTER TABLE agent_notices ADD COLUMN result TEXT")


@contextmanager
def get_conn():
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_dict(row):
    d = dict(row)
    for f in _JSON_FIELDS:
        if f in d and isinstance(d[f], str):
            try:
                d[f] = json.loads(d[f])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def _now_str():
    """本地时间字符串（与 SQLite datetime('now','localtime') 同形）。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ═══════════════════════════════════════════
# Schema 检查（测试用）
# ═══════════════════════════════════════════


def list_tables():
    if USE_CLOUD:
        return [
            "agent_sessions",
            "agent_messages",
            "agent_articles",
            "agent_opinions",
            "agent_knowledge",
            "agent_metadata",
            "agent_sources",
            "agent_activities",
            "platform_cookies",
            "platform_reachability",
            "agent_notices",
        ]
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return [r["name"] for r in rows]


# ═══════════════════════════════════════════
# 会话 / 消息
# ═══════════════════════════════════════════


def session_create(title="新会话", persona=config.PERSONA_ID):
    if USE_CLOUD:
        row = _cd_insert("agent_sessions", {"persona": persona, "title": title})
        return row["id"] if row else None
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agent_sessions(persona, title) VALUES (?, ?)", (persona, title)
        )
        return cur.lastrowid


def session_list():
    if USE_CLOUD:
        return _cd_select("agent_sessions", order="updated_at.desc")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_sessions ORDER BY updated_at DESC"
        ).fetchall()
        return [_row_dict(r) for r in rows]


def session_get(session_id):
    if USE_CLOUD:
        return _cd_select_one("agent_sessions", filters=[("id", "eq", session_id)])
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM agent_sessions WHERE id=?", (session_id,)
        ).fetchone()
        return dict(r) if r else None


def session_rename(session_id, title):
    if USE_CLOUD:
        _cd_update(
            "agent_sessions",
            {"title": title, "updated_at": _now_str()},
            filters=[("id", "eq", session_id)],
        )
        return
    with get_conn() as conn:
        conn.execute(
            "UPDATE agent_sessions SET title=?, updated_at=datetime('now','localtime') "
            "WHERE id=?",
            (title, session_id),
        )


def session_delete(session_id):
    if USE_CLOUD:
        # 级联删消息由数据库外键 ON DELETE CASCADE 处理
        _cd_delete("agent_sessions", filters=[("id", "eq", session_id)])
        return
    with get_conn() as conn:
        conn.execute("DELETE FROM agent_sessions WHERE id=?", (session_id,))


def message_add(session_id, role, content, sources=None):
    if USE_CLOUD:
        row = _cd_insert(
            "agent_messages",
            {
                "session_id": session_id,
                "role": role,
                "content": content,
                "sources": sources or [],
            },
        )
        _cd_update(
            "agent_sessions",
            {"updated_at": _now_str()},
            filters=[("id", "eq", session_id)],
        )
        return row["id"] if row else None
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agent_messages(session_id, role, content, sources) "
            "VALUES (?,?,?,?)",
            (session_id, role, content, json.dumps(sources or [], ensure_ascii=False)),
        )
        conn.execute(
            "UPDATE agent_sessions SET updated_at=datetime('now','localtime') "
            "WHERE id=?",
            (session_id,),
        )
        return cur.lastrowid


def messages_by_session(session_id):
    if USE_CLOUD:
        return _cd_select(
            "agent_messages", filters=[("session_id", "eq", session_id)], order="id.asc"
        )
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_messages WHERE session_id=? ORDER BY id", (session_id,)
        ).fetchall()
        return [_row_dict(r) for r in rows]


def messages_all():
    if USE_CLOUD:
        return _cd_select("agent_messages", order="id.asc")
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM agent_messages ORDER BY id").fetchall()
        return [_row_dict(r) for r in rows]


# ═══════════════════════════════════════════
# 文章
# ═══════════════════════════════════════════


def article_create(
    title,
    summary,
    content,
    topics=None,
    sources=None,
    status="published",
    kind="article",
):
    if USE_CLOUD:
        # BUG-FIX(2026-09-08)：云表 agent_articles.published_at 无 DEFAULT（SQLite 才有
        # datetime('now','localtime') 默认值）→ 云端插入不传该列会得到 NULL，
        # 导致"我的动态"列表不显示发文时间。这里显式写入当前时间，与 SQLite 分支语义一致。
        row = _cd_insert(
            "agent_articles",
            {
                "title": title,
                "summary": summary,
                "content": content,
                "topics": topics or [],
                "sources": sources or [],
                "status": status,
                "kind": kind,
                "published_at": _now_str(),
            },
        )
        return row["id"] if row else None
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agent_articles(title, summary, content, topics, sources, status, kind) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                title,
                summary,
                content,
                json.dumps(topics or [], ensure_ascii=False),
                json.dumps(sources or [], ensure_ascii=False),
                status,
                kind,
            ),
        )
        return cur.lastrowid


def article_list(limit=50, kind=None):
    if USE_CLOUD:
        filters = [("kind", "eq", kind)] if kind else None
        return _cd_select(
            "agent_articles",
            filters=filters,
            order="published_at.desc,id.desc",
            limit=limit,
        )
    with get_conn() as conn:
        if kind:
            rows = conn.execute(
                "SELECT * FROM agent_articles WHERE kind=? "
                "ORDER BY published_at DESC, id DESC LIMIT ?",
                (kind, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_articles "
                "ORDER BY published_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_dict(r) for r in rows]


def article_get(article_id):
    if USE_CLOUD:
        return _cd_select_one("agent_articles", filters=[("id", "eq", article_id)])
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM agent_articles WHERE id=?", (article_id,)
        ).fetchone()
        return _row_dict(r) if r else None


# ═══════════════════════════════════════════
# 观点库
# ═══════════════════════════════════════════


def opinion_add(topic, opinion, article_id=None):
    if USE_CLOUD:
        row = _cd_insert(
            "agent_opinions",
            {
                "topic": topic,
                "opinion": opinion,
                "article_id": article_id,
            },
        )
        return row["id"] if row else None
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agent_opinions(topic, opinion, article_id) VALUES (?,?,?)",
            (topic, opinion, article_id),
        )
        return cur.lastrowid


def opinions_by_topic(topic):
    if USE_CLOUD:
        return _cd_select(
            "agent_opinions", filters=[("topic", "eq", topic)], order="id.asc"
        )
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_opinions WHERE topic=? ORDER BY id", (topic,)
        ).fetchall()
        return [_row_dict(r) for r in rows]


def opinions_all():
    if USE_CLOUD:
        return _cd_select("agent_opinions", order="id.asc")
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM agent_opinions ORDER BY id").fetchall()
        return [_row_dict(r) for r in rows]


# ═══════════════════════════════════════════
# 知识条目（RSS/搜索素材）
# ═══════════════════════════════════════════


def knowledge_upsert(source, title, url, summary=None, content=None, published_at=None):
    """按 url 去重入库。返回 True=新增；False=已存在（不更新，保序）。"""
    if USE_CLOUD:
        exists = _cd_select_one(
            "agent_knowledge", filters=[("url", "eq", url)], columns="id"
        )
        if exists:
            return False
        _cd_insert(
            "agent_knowledge",
            {
                "source": source,
                "title": title,
                "url": url,
                "summary": summary,
                "content": content,
                "published_at": published_at,
            },
        )
        return True
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM agent_knowledge WHERE url=?", (url,)
        ).fetchone()
        if exists:
            return False
        conn.execute(
            "INSERT INTO agent_knowledge(source, title, url, summary, content, published_at) "
            "VALUES (?,?,?,?,?,?)",
            (source, title, url, summary, content, published_at),
        )
        return True


def knowledge_set_memory(kid, viewpoint=None, emotion=None, memory=None, read_at=None):
    """将阅读后的观点/情绪/记忆写回知识条目（阅读完成回调）。"""
    if USE_CLOUD:
        patch = {}
        for k, v in (
            ("viewpoint", viewpoint),
            ("emotion", emotion),
            ("memory", memory),
            ("read_at", read_at),
        ):
            if v is not None:
                patch[k] = v
        if patch:
            _cd_update("agent_knowledge", patch, filters=[("id", "eq", kid)])
        return
    with get_conn() as conn:
        conn.execute(
            "UPDATE agent_knowledge SET "
            "viewpoint=COALESCE(?, viewpoint), "
            "emotion=COALESCE(?, emotion), "
            "memory=COALESCE(?, memory), "
            "read_at=COALESCE(?, read_at) "
            "WHERE id=?",
            (viewpoint, emotion, memory, read_at, kid),
        )


def knowledge_with_memory(limit=20):
    """检索已有阅读记忆的条目（可供下次阅读时做上下文联想）。"""
    if USE_CLOUD:
        # BUG-FIX(2026-09-07)：过滤方向反了 —— 应返回 memory 非空的条目
        # （SQLite 分支 IS NOT NULL），原写 is.null 返回的是"无记忆"条目。
        return _cd_select(
            "agent_knowledge",
            filters=[("memory", "not.is", None)],
            order="read_at.desc,id.desc",
            limit=limit,
        )
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_knowledge WHERE memory IS NOT NULL "
            "ORDER BY read_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_dict(r) for r in rows]


def knowledge_unread(limit=10):
    """获取尚未被小满阅读过的条目（read_at IS NULL）。"""
    if USE_CLOUD:
        return _cd_select(
            "agent_knowledge",
            filters=[("read_at", "is", None), ("consumed", "eq", 0)],
            order="fetched_at.desc,id.desc",
            limit=limit,
        )
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_knowledge WHERE read_at IS NULL AND consumed=0 "
            "ORDER BY fetched_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_dict(r) for r in rows]


def knowledge_unconsumed(limit=20):
    if USE_CLOUD:
        return _cd_select(
            "agent_knowledge",
            filters=[("consumed", "eq", 0)],
            order="fetched_at.desc,id.desc",
            limit=limit,
        )
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_knowledge WHERE consumed=0 "
            "ORDER BY fetched_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_dict(r) for r in rows]


def knowledge_mark_consumed(kid):
    if USE_CLOUD:
        _cd_update("agent_knowledge", {"consumed": True}, filters=[("id", "eq", kid)])
        return
    with get_conn() as conn:
        conn.execute("UPDATE agent_knowledge SET consumed=1 WHERE id=?", (kid,))


def knowledge_remove_by_url(url):
    """按 url 删除知识条目（标题相似度去重时移除误插）。返回是否删除。"""
    if USE_CLOUD:
        n = _cd_delete("agent_knowledge", filters=[("url", "eq", url)])
        return n > 0
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM agent_knowledge WHERE url=?", (url,))
        return cur.rowcount > 0


def knowledge_all(limit=200):
    if USE_CLOUD:
        return _cd_select("agent_knowledge", order="id.desc", limit=limit)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_knowledge ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_dict(r) for r in rows]


# ═══════════════════════════════════════════
# metadata（heartbeat / 每日发文状态）
# ═══════════════════════════════════════════


def meta_get(key):
    if USE_CLOUD:
        row = _cd_select_one("agent_metadata", filters=[("key", "eq", key)])
        return row["value"] if row else None
    with get_conn() as conn:
        r = conn.execute(
            "SELECT value FROM agent_metadata WHERE key=?", (key,)
        ).fetchone()
        return r["value"] if r else None


def meta_get_many(keys: list[str]) -> dict:
    """一次批量取多个 metadata key（云模式 1 次往返）。

    2026-09-08 性能优化：/api/agent/status 原先逐个 meta_get（云模式 N 次
    HTTPS 往返）→ 批量后降为 1 次。返回 {key: value}，缺失 key 值为 None。
    """
    if not keys:
        return {}
    if USE_CLOUD:
        rows = _cd_select(
            "agent_metadata", columns="key,value",
            # PostgREST in 过滤：key=in.(k1,k2)。key 为内部标识符（无逗号/括号）
            filters=[("key", "in", "(" + ",".join(keys) + ")")],
        )
        vals = {r["key"]: r["value"] for r in rows}
        return {k: vals.get(k) for k in keys}
    with get_conn() as conn:
        qs = ",".join("?" for _ in keys)
        rows = conn.execute(
            f"SELECT key, value FROM agent_metadata WHERE key IN ({qs})", keys
        ).fetchall()
        vals = {r["key"]: r["value"] for r in rows}
        return {k: vals.get(k) for k in keys}


def meta_set(key, value):
    if USE_CLOUD:
        _cd_upsert("agent_metadata", {"key": key, "value": value}, on_conflict="key")
        return
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO agent_metadata(key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


# ═══════════════════════════════════════════
# 活动台账（agent_activities）：状态切换时"关旧开新"，供认识页"做过的事"展示
# ═══════════════════════════════════════════


def activity_start(kind, label, started_at, source="auto"):
    """开启一条新的活动记录（= 状态切换进来时调用）。返回新记录 id。"""
    if USE_CLOUD:
        row = _cd_insert(
            "agent_activities",
            {
                "kind": kind,
                "label": label,
                "started_at": started_at,
                "source": source,
            },
        )
        return row["id"] if row else None
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agent_activities(kind, label, started_at, source) "
            "VALUES (?,?,?,?)",
            (kind, label, started_at, source),
        )
        return cur.lastrowid


def activity_open():
    """当前未结束（正在做）的活动；没有返回 None。"""
    if USE_CLOUD:
        return _cd_select_one(
            "agent_activities", filters=[("ended_at", "is", None)], order="id.desc"
        )
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM agent_activities WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return _row_dict(r) if r else None


def activity_close_open(ended_at, tokens=None):
    """结束当前未完结的活动：写入结束时间与 token 用量（真实 usage 暂无 → 保持 NULL=未计量）。

    返回被结束的记录 dict（无则 None）。tokens 参数为将来真实 usage 接入时的入口。
    """
    if USE_CLOUD:
        open_row = _cd_select_one(
            "agent_activities", filters=[("ended_at", "is", None)], order="id.desc"
        )
        if open_row is None:
            return None
        _cd_update(
            "agent_activities",
            {"ended_at": ended_at, "tokens": tokens},
            filters=[("id", "eq", open_row["id"])],
        )
        return open_row
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM agent_activities WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE agent_activities SET ended_at=?, tokens=? WHERE id=?",
            (ended_at, tokens, row["id"]),
        )
        return _row_dict(row)


def activity_set_note(activity_id, note):
    """给活动补备注（如阅读会话：读了哪几篇）。"""
    if USE_CLOUD:
        _cd_update(
            "agent_activities", {"note": note}, filters=[("id", "eq", activity_id)]
        )
        return
    with get_conn() as conn:
        conn.execute(
            "UPDATE agent_activities SET note=? WHERE id=?", (note, activity_id)
        )


def activity_count(date_filter=None):
    """活动总数（分页用）。date_filter 可选，格式 YYYY-MM-DD。"""
    if USE_CLOUD:
        # BUG-FIX(2026-09-08)：cloud_db.select 的参数名是 columns 不是 select ——
        # 原 select="id" 触发 TypeError → /api/agent/activities 500 → 前端"做过的事"加载失败。
        if date_filter:
            rows = _cd_select(
                "agent_activities",
                columns="id",
                filters=[
                    ("started_at", "gte", date_filter + " 00:00:00"),
                    ("started_at", "lt", date_filter + " 23:59:59"),
                ],
            )
            return len(rows)
        rows = _cd_select("agent_activities", columns="id")
        return len(rows)
    with get_conn() as conn:
        if date_filter:
            r = conn.execute(
                "SELECT COUNT(*) FROM agent_activities "
                "WHERE started_at >= ? AND started_at < ?",
                (date_filter + " 00:00:00", date_filter + " 23:59:59"),
            ).fetchone()
        else:
            r = conn.execute("SELECT COUNT(*) FROM agent_activities").fetchone()
        return r[0] if r else 0


def activity_list(limit=50, date_filter=None, offset=0):
    """最近活动（进行中排最前，其余按开始时间倒序）。

    date_filter: 可选，格式 YYYY-MM-DD，只返回当天开始的活动。
    offset: 分页偏移量（配合 limit 使用）。
    """
    if USE_CLOUD:
        filters = []
        if date_filter:
            filters.append(("started_at", "gte", date_filter + " 00:00:00"))
            filters.append(("started_at", "lt", date_filter + " 23:59:59"))
        rows = _cd_select(
            "agent_activities",
            filters=filters or None,
            order="ended_at.asc,started_at.desc,id.desc",
            limit=limit,
            offset=offset,
        )
        rows.sort(key=lambda r: (r.get("ended_at") is not None,))
        return rows
    with get_conn() as conn:
        if date_filter:
            rows = conn.execute(
                "SELECT * FROM agent_activities "
                "WHERE started_at >= ? AND started_at < ? "
                "ORDER BY (ended_at IS NULL) DESC, started_at DESC, id DESC LIMIT ? OFFSET ?",
                (date_filter + " 00:00:00", date_filter + " 23:59:59", limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_activities "
                "ORDER BY (ended_at IS NULL) DESC, started_at DESC, id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_row_dict(r) for r in rows]


# ═══════════════════════════════════════════
# 素材源（自定义站点/手动 URL）
# ═══════════════════════════════════════════


def source_add(name, url, kind="website", note=None):
    if USE_CLOUD:
        # BUG-FIX(2026-09-07)：agent_sources.name 已加唯一约束，改用 on_conflict upsert
        # （防双进程并发重复插入 409，且重复名返回已有 id 幂等）。
        row = _cd_upsert(
            "agent_sources",
            {
                "name": name,
                "url": url,
                "kind": kind,
                "note": note,
            },
            on_conflict="name",
        )
        return row["id"] if row else None
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agent_sources(name, url, kind, note) VALUES (?,?,?,?)",
            (name, url, kind, note),
        )
        return cur.lastrowid


def source_list(enabled_only=True):
    if USE_CLOUD:
        filters = [("enabled", "eq", True)] if enabled_only else None
        return _cd_select("agent_sources", filters=filters, order="id.asc")
    with get_conn() as conn:
        if enabled_only:
            rows = conn.execute(
                "SELECT * FROM agent_sources WHERE enabled=1 ORDER BY id"
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM agent_sources ORDER BY id").fetchall()
        return [_row_dict(r) for r in rows]


def source_get(source_id):
    if USE_CLOUD:
        return _cd_select_one("agent_sources", filters=[("id", "eq", source_id)])
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM agent_sources WHERE id=?", (source_id,)
        ).fetchone()
        return dict(r) if r else None


def source_set_enabled(source_id, enabled):
    if USE_CLOUD:
        _cd_update(
            "agent_sources",
            {"enabled": bool(enabled)},
            filters=[("id", "eq", source_id)],
        )
        return
    with get_conn() as conn:
        conn.execute(
            "UPDATE agent_sources SET enabled=? WHERE id=?",
            (1 if enabled else 0, source_id),
        )


def source_delete(source_id):
    if USE_CLOUD:
        _cd_delete("agent_sources", filters=[("id", "eq", source_id)])
        return
    with get_conn() as conn:
        conn.execute("DELETE FROM agent_sources WHERE id=?", (source_id,))


# ═══════════════════════════════════════════
# 社交平台（方案 v1.10 §9.4）：Cookie 云库存取 + 可访问性缓存
# ═══════════════════════════════════════════


def platform_cookie_get(platform_id):
    """读取平台 Cookie（云库 platform_cookies / 本地表）。无则返回 None。"""
    if USE_CLOUD:
        row = _cd_select_one(
            "platform_cookies", filters=[("platform_id", "eq", platform_id)]
        )
        return row["cookie"] if row else None
    with get_conn() as conn:
        r = conn.execute(
            "SELECT cookie FROM platform_cookies WHERE platform_id=?", (platform_id,)
        ).fetchone()
        return r["cookie"] if r else None


def platform_cookie_set(platform_id, cookie):
    """写入/更新平台 Cookie（幂等 upsert，云库与本地一致）。"""
    now = _now_str()
    if USE_CLOUD:
        _cd_upsert(
            "platform_cookies",
            {"platform_id": platform_id, "cookie": cookie, "updated_at": now},
            on_conflict="platform_id",
        )
        return
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO platform_cookies(platform_id, cookie, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(platform_id) DO UPDATE SET cookie=excluded.cookie, "
            "updated_at=excluded.updated_at",
            (platform_id, cookie, now),
        )


def reachability_get(platform_id):
    """读取平台可访问性缓存。返回 {reachable, checked_at, reason} 或 None（未判定）。"""
    if USE_CLOUD:
        row = _cd_select_one(
            "platform_reachability", filters=[("platform_id", "eq", platform_id)]
        )
        if not row:
            return None
        return {
            "reachable": bool(row.get("reachable")),
            "checked_at": row.get("checked_at"),
            "reason": row.get("reason"),
        }
    with get_conn() as conn:
        r = conn.execute(
            "SELECT reachable, checked_at, reason FROM platform_reachability "
            "WHERE platform_id=?",
            (platform_id,),
        ).fetchone()
        if not r:
            return None
        return {
            "reachable": bool(r["reachable"]),
            "checked_at": r["checked_at"],
            "reason": r["reason"],
        }


def reachability_set(platform_id, reachable, reason=None):
    """写入/更新平台可访问性缓存（幂等 upsert）。"""
    now = _now_str()
    if USE_CLOUD:
        _cd_upsert(
            "platform_reachability",
            {
                "platform_id": platform_id,
                "reachable": bool(reachable),
                "checked_at": now,
                "reason": reason,
            },
            on_conflict="platform_id",
        )
        return
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO platform_reachability(platform_id, reachable, checked_at, reason) "
            "VALUES (?,?,?,?) "
            "ON CONFLICT(platform_id) DO UPDATE SET reachable=excluded.reachable, "
            "checked_at=excluded.checked_at, reason=excluded.reason",
            (platform_id, 1 if reachable else 0, now, reason),
        )


def reachability_all():
    """读取全部平台可访问性缓存 → {platform_id: {reachable, checked_at, reason}}。"""
    if USE_CLOUD:
        rows = _cd_select("platform_reachability")
        return {
            r["platform_id"]: {
                "reachable": bool(r.get("reachable")),
                "checked_at": r.get("checked_at"),
                "reason": r.get("reason"),
            }
            for r in rows
        }
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT platform_id, reachable, checked_at, reason FROM platform_reachability"
        ).fetchall()
        return {
            r["platform_id"]: {
                "reachable": bool(r["reachable"]),
                "checked_at": r["checked_at"],
                "reason": r["reason"],
            }
            for r in rows
        }


def knowledge_titles(limit=500):
    """最近知识条目标题（标题相似度去重用）。返回 [(id, title, source)]。"""
    if USE_CLOUD:
        rows = _cd_select(
            "agent_knowledge", columns="id,title,source", order="id.desc", limit=limit
        )
        return [(r["id"], r.get("title") or "", r.get("source") or "") for r in rows]
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, source FROM agent_knowledge ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [(r["id"], r["title"] or "", r["source"] or "") for r in rows]


def title_similar(title, threshold=None, limit=500):
    """标题相似度去重：与库内既有标题做 difflib 字符级相似度比对。

    返回相似标题的 (id, title, ratio)；无相似返回 []。threshold 默认读 config
    （0.85）。不引入 embedding —— 轻量字符级足够（热点标题多为同一话题相似表述）。
    """
    import difflib

    threshold = threshold if threshold is not None else config.TITLE_SIMILARITY_THRESHOLD
    title = (title or "").strip()
    if not title:
        return []
    hits = []
    for kid, ktitle, _src in knowledge_titles(limit=limit):
        if not ktitle:
            continue
        ratio = difflib.SequenceMatcher(None, title, ktitle).ratio()
        if ratio >= threshold:
            hits.append((kid, ktitle, round(ratio, 3)))
    return hits


# ═══════════════════════════════════════════
# 提示/待办（agent_notices）：REQ-002 聊天页「📌 提示与待办」
# ═══════════════════════════════════════════

_NOTICE_KINDS = ("notice", "todo")
_NOTICE_STATUSES = ("open", "done", "dismissed")


def notice_create(kind, title, content, todo_type=None, source=None, todo_data=None):
    """创建提示/待办。返回新记录 id。

    kind: notice=提示（不需回复） | todo=待办（需回复）
    todo_type: 待办回调类型（reply 时 dispatch 用）；提示为 None
    todo_data: 待办负载 dict（如 {"platform_id": "weibo"}）→ 存 JSON
    """
    if kind not in _NOTICE_KINDS:
        raise ValueError(f"kind 必须是 {_NOTICE_KINDS} 之一")
    if USE_CLOUD:
        row = _cd_insert(
            "agent_notices",
            {
                "kind": kind,
                "status": "open",
                "title": title,
                "content": content,
                "todo_type": todo_type,
                "todo_data": json.dumps(todo_data, ensure_ascii=False) if todo_data else None,
                "source": source,
            },
        )
        return row["id"] if row else None
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agent_notices(kind, status, title, content, todo_type, todo_data, source) "
            "VALUES (?, 'open', ?, ?, ?, ?, ?)",
            (
                kind, title, content, todo_type,
                json.dumps(todo_data, ensure_ascii=False) if todo_data else None,
                source,
            ),
        )
        return cur.lastrowid


def notice_get(notice_id):
    if USE_CLOUD:
        return _cd_select_one("agent_notices", filters=[("id", "eq", notice_id)])
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM agent_notices WHERE id=?", (notice_id,)
        ).fetchone()
        return _row_dict(r) if r else None


def notice_list(kind=None, status=None, limit=50, offset=0):
    """提示/待办列表（未处理在前、已处理在后；组内新→旧），支持分页。

    未处理 = read_at IS NULL 且 status='open'；已处理 = 已阅/已回复/已忽略。
    """
    if USE_CLOUD:
        rows = _cd_select("agent_notices", columns="*")  # 全量拉取（量小），Python 侧排序
        rows = _sort_notices(rows)
        if kind:
            rows = [r for r in rows if r.get("kind") == kind]
        if status:
            rows = [r for r in rows if r.get("status") == status]
        return rows[offset:offset + limit]
    sql = "SELECT * FROM agent_notices"
    conds, args = [], []
    if kind:
        conds.append("kind=?"), args.append(kind)
    if status:
        conds.append("status=?"), args.append(status)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += (" ORDER BY CASE WHEN read_at IS NULL AND status='open' THEN 0 ELSE 1 END, "
            "id DESC LIMIT ? OFFSET ?")
    args += [limit, offset]
    with get_conn() as conn:
        rows = conn.execute(sql, tuple(args)).fetchall()
        return [_row_dict(r) for r in rows]


def notice_count(kind=None, status=None):
    """提示/待办总数（分页用）。"""
    if USE_CLOUD:
        rows = _cd_select("agent_notices", columns="id")
        if kind:
            rows = [r for r in rows if r.get("kind") == kind]
        if status:
            rows = [r for r in rows if r.get("status") == status]
        return len(rows)
    sql = "SELECT COUNT(*) FROM agent_notices"
    conds, args = [], []
    if kind:
        conds.append("kind=?"), args.append(kind)
    if status:
        conds.append("status=?"), args.append(status)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    with get_conn() as conn:
        r = conn.execute(sql, tuple(args)).fetchone()
        return r[0] if r else 0


def _sort_notices(rows):
    """未处理（未读且 open）在前，已处理在后；组内 id 新→旧。"""
    return sorted(
        rows,
        key=lambda r: (
            0 if (r.get("read_at") is None and r.get("status") == "open") else 1,
            -(r.get("id") or 0),
        ),
    )


def notice_unread_count():
    """未读数（read_at IS NULL 且未 dismiss）——聊天标题右上小红点。"""
    if USE_CLOUD:
        rows = _cd_select(
            "agent_notices",
            columns="id",
            filters=[("read_at", "is", None), ("status", "neq", "dismissed")],
        )
        return len(rows)
    with get_conn() as conn:
        r = conn.execute(
            "SELECT COUNT(*) FROM agent_notices "
            "WHERE read_at IS NULL AND status != 'dismissed'"
        ).fetchone()
        return r[0] if r else 0


def notice_mark_read(notice_id):
    """标记已读（幂等：未读才写 read_at）。"""
    if USE_CLOUD:
        row = _cd_select_one(
            "agent_notices",
            columns="id,read_at",
            filters=[("id", "eq", notice_id)],
        )
        if row and row.get("read_at") is None:
            _cd_update(
                "agent_notices",
                {"read_at": _now_str()},
                filters=[("id", "eq", notice_id)],
            )
        return
    with get_conn() as conn:
        conn.execute(
            "UPDATE agent_notices SET read_at=COALESCE(read_at, ?) WHERE id=?",
            (_now_str(), notice_id),
        )


def notice_mark_all_read():
    """全部标记已读（进入聊天页/面板时调用）。"""
    if USE_CLOUD:
        _cd_update(
            "agent_notices",
            {"read_at": _now_str()},
            filters=[("read_at", "is", None)],
        )
        return
    with get_conn() as conn:
        conn.execute(
            "UPDATE agent_notices SET read_at=COALESCE(read_at, ?) WHERE read_at IS NULL",
            (_now_str(),),
        )


def notice_reply(notice_id, reply, result=None, success=True):
    """待办回复（状态机）：open → replied → done / 失败回 open。

    - success=True:  status='done'，result=小满处理成功的回复，read_at 置为已读
    - success=False: status='open'（重置未处理，可重试），result=小满的失败原因，
                     read_at 清空（重新计未读 → 小红点重新提醒）
    reply 始终记录用户回复与时间。
    """
    now = _now_str()
    if USE_CLOUD:
        if success:
            _cd_update(
                "agent_notices",
                {"reply": reply, "reply_at": now, "result": result, "status": "done",
                 "read_at": now},
                filters=[("id", "eq", notice_id)],
            )
        else:
            _cd_update(
                "agent_notices",
                {"reply": reply, "reply_at": now, "result": result, "status": "open",
                 "read_at": None},
                filters=[("id", "eq", notice_id)],
            )
        return
    with get_conn() as conn:
        if success:
            conn.execute(
                "UPDATE agent_notices SET reply=?, reply_at=?, result=?, "
                "status='done', read_at=COALESCE(read_at, ?) WHERE id=?",
                (reply, now, result, now, notice_id),
            )
        else:
            conn.execute(
                "UPDATE agent_notices SET reply=?, reply_at=?, result=?, "
                "status='open', read_at=NULL WHERE id=?",
                (reply, now, result, notice_id),
            )


def notice_set_status(notice_id, status):
    """状态流转：open | done | dismissed。"""
    if status not in _NOTICE_STATUSES:
        raise ValueError(f"status 必须是 {_NOTICE_STATUSES} 之一")
    if USE_CLOUD:
        _cd_update(
            "agent_notices", {"status": status}, filters=[("id", "eq", notice_id)]
        )
        return
    with get_conn() as conn:
        conn.execute(
            "UPDATE agent_notices SET status=? WHERE id=?", (status, notice_id)
        )
