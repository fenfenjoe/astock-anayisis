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

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from agent import config

_DB_PATH = config.DB_PATH

# ── 严格零本地：DB_MODE=memory 时用内存库（:memory:），
#    启动从 TOS 载入最新快照（cloud_restore），定时/退出快照回传（cloud_backup）。
#    默认 file 模式（测试/降级）。
USE_MEMORY = os.environ.get("DB_MODE", "").lower() == "memory"

# ── 云端权威数据库后端（AGENT_DB_BACKEND=cloud 时启用）：
#    所有 CRUD 直接读写火山 Supabase Postgres（PostgREST Data API），
#    替代本地 SQLite 权威存储 → 跨机器/多进程天然一致。
USE_CLOUD = os.environ.get("AGENT_DB_BACKEND", "").lower() == "cloud"

_mem_lock = threading.RLock()
_mem_conn: sqlite3.Connection | None = None
_SNAPSHOT_KEY = "agent.db"  # TOS 内 sqlite/<ts>/agent.db

try:
    from cloud_store import (
        get_object as _cs_get,
        put_object as _cs_put,
        list_objects as _cs_list,
    )
except ImportError:
    _cs_get = _cs_put = _cs_list = None

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


def _memory_conn() -> sqlite3.Connection:
    global _mem_conn
    if _mem_conn is None:
        _mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
        _mem_conn.row_factory = sqlite3.Row
        _mem_conn.execute("PRAGMA foreign_keys=ON")
    return _mem_conn


def _deserialize_mem(data: bytes) -> bool:
    """把快照字节载入内存库：临时文件 + sqlite3 backup（即时删除，零持久文件）。

    不用 deserialize()：其对 WAL 库半成功（返回但连接损坏，Python 3.11 已知行为）。
    """
    tmp = None
    try:
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            f.write(data)
            tmp = f.name
        src = sqlite3.connect(tmp)
        try:
            src.backup(_memory_conn())
        finally:
            src.close()
        return True
    except Exception:
        return False
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def cloud_restore() -> bool:
    """memory 模式：从 TOS 最新 agent.db 快照载入。"""
    if not USE_MEMORY or _cs_get is None or _cs_list is None:
        return False
    try:
        keys = [k for k in _cs_list("sqlite/") if k.endswith("/agent.db")]
        if not keys:
            return False
        data = _cs_get(max(keys))
        if not data:
            return False
        return _deserialize_mem(data)
    except Exception:
        return False


def cloud_backup() -> bool:
    """memory 模式：导出快照并上传 TOS（sqlite/<ts>/agent.db）。"""
    if not USE_MEMORY or _cs_put is None:
        return False
    try:
        data = _memory_conn().serialize()
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        _cs_put(f"sqlite/{ts}/{_SNAPSHOT_KEY}", data)
        return True
    except Exception:
        return False


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
"""

_JSON_FIELDS = ("sources", "topics")


def init_db(db_path=None):
    """设置数据库路径并建表（幂等）。db_path=None 复位为默认路径。

    cloud 模式：仅校验云连接（不落本地文件）。
    memory 模式：忽略 db_path，从 TOS 载入最新快照；无快照建空 schema。
    """
    global _DB_PATH
    _DB_PATH = Path(db_path) if db_path else config.DB_PATH
    if USE_CLOUD:
        return  # 云表已由 schema 建好；连接由 cloud_db 惰性建立
    if USE_MEMORY:
        if not cloud_restore():
            _memory_conn().executescript(SCHEMA)
            _migrate(_memory_conn())
        return
    with get_conn():
        pass  # 建表 + 迁移在 get_conn 首次打开时执行


def _migrate(conn):
    """轻量列迁移（幂等）：老库补 kind / viewpoint / emotion / memory / read_at 列。"""
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


@contextmanager
def get_conn():
    if USE_MEMORY:
        conn = _memory_conn()
        with _mem_lock:
            yield conn
            conn.commit()
        return
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
            "agent_sessions", "agent_messages", "agent_articles",
            "agent_opinions", "agent_knowledge", "agent_metadata",
            "agent_sources", "agent_activities",
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
        _cd_update("agent_sessions", {"title": title, "updated_at": _now_str()},
                   filters=[("id", "eq", session_id)])
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
        row = _cd_insert("agent_messages", {
            "session_id": session_id, "role": role, "content": content,
            "sources": sources or [],
        })
        _cd_update("agent_sessions", {"updated_at": _now_str()},
                   filters=[("id", "eq", session_id)])
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
        return _cd_select("agent_messages", filters=[("session_id", "eq", session_id)],
                          order="id.asc")
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
        row = _cd_insert("agent_articles", {
            "title": title, "summary": summary, "content": content,
            "topics": topics or [], "sources": sources or [],
            "status": status, "kind": kind,
        })
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
        return _cd_select("agent_articles", filters=filters,
                          order="published_at.desc,id.desc", limit=limit)
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
        row = _cd_insert("agent_opinions", {
            "topic": topic, "opinion": opinion, "article_id": article_id,
        })
        return row["id"] if row else None
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agent_opinions(topic, opinion, article_id) VALUES (?,?,?)",
            (topic, opinion, article_id),
        )
        return cur.lastrowid


def opinions_by_topic(topic):
    if USE_CLOUD:
        return _cd_select("agent_opinions", filters=[("topic", "eq", topic)],
                          order="id.asc")
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
        exists = _cd_select_one("agent_knowledge", filters=[("url", "eq", url)],
                                columns="id")
        if exists:
            return False
        _cd_insert("agent_knowledge", {
            "source": source, "title": title, "url": url,
            "summary": summary, "content": content, "published_at": published_at,
        })
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
        for k, v in (("viewpoint", viewpoint), ("emotion", emotion),
                     ("memory", memory), ("read_at", read_at)):
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
        return _cd_select("agent_knowledge",
                          filters=[("memory", "not.is", None)], order="read_at.desc,id.desc",
                          limit=limit)
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
        return _cd_select("agent_knowledge",
                          filters=[("read_at", "is", None), ("consumed", "eq", 0)],
                          order="fetched_at.desc,id.desc", limit=limit)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_knowledge WHERE read_at IS NULL AND consumed=0 "
            "ORDER BY fetched_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_dict(r) for r in rows]


def knowledge_unconsumed(limit=20):
    if USE_CLOUD:
        return _cd_select("agent_knowledge", filters=[("consumed", "eq", 0)],
                          order="fetched_at.desc,id.desc", limit=limit)
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
        row = _cd_insert("agent_activities", {
            "kind": kind, "label": label, "started_at": started_at, "source": source,
        })
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
        return _cd_select_one("agent_activities", filters=[("ended_at", "is", None)],
                              order="id.desc")
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
        open_row = _cd_select_one("agent_activities",
                                  filters=[("ended_at", "is", None)], order="id.desc")
        if open_row is None:
            return None
        _cd_update("agent_activities", {"ended_at": ended_at, "tokens": tokens},
                   filters=[("id", "eq", open_row["id"])])
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
        _cd_update("agent_activities", {"note": note}, filters=[("id", "eq", activity_id)])
        return
    with get_conn() as conn:
        conn.execute(
            "UPDATE agent_activities SET note=? WHERE id=?", (note, activity_id)
        )


def activity_list(limit=50):
    """最近活动（进行中排最前，其余按开始时间倒序）。"""
    if USE_CLOUD:
        # 进行中(ended_at IS NULL)排前：PostgREST order 用 ended_at.asc（nulls first 需 Postgres 参数）
        rows = _cd_select("agent_activities", order="ended_at.asc,started_at.desc,id.desc",
                          limit=limit)
        # 简单重排：无 ended_at 在前
        rows.sort(key=lambda r: (r.get("ended_at") is not None, ))
        return rows
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_activities "
            "ORDER BY (ended_at IS NULL) DESC, started_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_dict(r) for r in rows]


# ═══════════════════════════════════════════
# 素材源（自定义站点/手动 URL）
# ═══════════════════════════════════════════


def source_add(name, url, kind="website", note=None):
    if USE_CLOUD:
        # BUG-FIX(2026-09-07)：agent_sources.name 已加唯一约束，改用 on_conflict upsert
        # （防双进程并发重复插入 409，且重复名返回已有 id 幂等）。
        row = _cd_upsert("agent_sources", {
            "name": name, "url": url, "kind": kind, "note": note,
        }, on_conflict="name")
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
        _cd_update("agent_sources", {"enabled": bool(enabled)},
                   filters=[("id", "eq", source_id)])
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
