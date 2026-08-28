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
_mem_lock = threading.RLock()
_mem_conn: sqlite3.Connection | None = None
_SNAPSHOT_KEY = "agent.db"  # TOS 内 sqlite/<ts>/agent.db

try:
    from cloud_store import (get_object as _cs_get, put_object as _cs_put,
                             list_objects as _cs_list)
except ImportError:
    _cs_get = _cs_put = _cs_list = None


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
"""

_JSON_FIELDS = ("sources", "topics")


def init_db(db_path=None):
    """设置数据库路径并建表（幂等）。db_path=None 复位为默认路径。

    memory 模式：忽略 db_path，从 TOS 载入最新快照；无快照建空 schema。
    """
    global _DB_PATH
    _DB_PATH = Path(db_path) if db_path else config.DB_PATH
    if USE_MEMORY:
        if not cloud_restore():
            _memory_conn().executescript(SCHEMA)
            _migrate(_memory_conn())
        return
    with get_conn():
        pass  # 建表 + 迁移在 get_conn 首次打开时执行


def _migrate(conn):
    """轻量列迁移（幂等）：老库补 kind 列。"""
    cols = [r["name"] for r in conn.execute(
        "PRAGMA table_info(agent_articles)")]
    if "kind" not in cols:
        conn.execute(
            "ALTER TABLE agent_articles "
            "ADD COLUMN kind TEXT NOT NULL DEFAULT 'article'")


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


# ═══════════════════════════════════════════
# Schema 检查（测试用）
# ═══════════════════════════════════════════

def list_tables():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return [r["name"] for r in rows]


# ═══════════════════════════════════════════
# 会话 / 消息
# ═══════════════════════════════════════════

def session_create(title="新会话", persona=config.PERSONA_ID):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agent_sessions(persona, title) VALUES (?, ?)",
            (persona, title))
        return cur.lastrowid


def session_list():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_sessions ORDER BY updated_at DESC").fetchall()
        return [_row_dict(r) for r in rows]


def session_get(session_id):
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM agent_sessions WHERE id=?", (session_id,)).fetchone()
        return dict(r) if r else None


def session_rename(session_id, title):
    with get_conn() as conn:
        conn.execute(
            "UPDATE agent_sessions SET title=?, updated_at=datetime('now','localtime') "
            "WHERE id=?", (title, session_id))


def session_delete(session_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM agent_sessions WHERE id=?", (session_id,))


def message_add(session_id, role, content, sources=None):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agent_messages(session_id, role, content, sources) "
            "VALUES (?,?,?,?)",
            (session_id, role, content,
             json.dumps(sources or [], ensure_ascii=False)))
        conn.execute(
            "UPDATE agent_sessions SET updated_at=datetime('now','localtime') "
            "WHERE id=?", (session_id,))
        return cur.lastrowid


def messages_by_session(session_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_messages WHERE session_id=? ORDER BY id",
            (session_id,)).fetchall()
        return [_row_dict(r) for r in rows]


def messages_all():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM agent_messages ORDER BY id").fetchall()
        return [_row_dict(r) for r in rows]


# ═══════════════════════════════════════════
# 文章
# ═══════════════════════════════════════════

def article_create(title, summary, content, topics=None, sources=None,
                   status="published", kind="article"):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agent_articles(title, summary, content, topics, sources, status, kind) "
            "VALUES (?,?,?,?,?,?,?)",
            (title, summary, content,
             json.dumps(topics or [], ensure_ascii=False),
             json.dumps(sources or [], ensure_ascii=False),
             status, kind))
        return cur.lastrowid


def article_list(limit=50, kind=None):
    with get_conn() as conn:
        if kind:
            rows = conn.execute(
                "SELECT * FROM agent_articles WHERE kind=? "
                "ORDER BY published_at DESC, id DESC LIMIT ?",
                (kind, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_articles "
                "ORDER BY published_at DESC, id DESC LIMIT ?",
                (limit,)).fetchall()
        return [_row_dict(r) for r in rows]


def article_get(article_id):
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM agent_articles WHERE id=?", (article_id,)).fetchone()
        return _row_dict(r) if r else None


# ═══════════════════════════════════════════
# 观点库
# ═══════════════════════════════════════════

def opinion_add(topic, opinion, article_id=None):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agent_opinions(topic, opinion, article_id) VALUES (?,?,?)",
            (topic, opinion, article_id))
        return cur.lastrowid


def opinions_by_topic(topic):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_opinions WHERE topic=? ORDER BY id",
            (topic,)).fetchall()
        return [_row_dict(r) for r in rows]


def opinions_all():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_opinions ORDER BY id").fetchall()
        return [_row_dict(r) for r in rows]


# ═══════════════════════════════════════════
# 知识条目（RSS/搜索素材）
# ═══════════════════════════════════════════

def knowledge_upsert(source, title, url, summary=None, content=None,
                     published_at=None):
    """按 url 去重入库。返回 True=新增；False=已存在（不更新，保序）。"""
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM agent_knowledge WHERE url=?", (url,)).fetchone()
        if exists:
            return False
        conn.execute(
            "INSERT INTO agent_knowledge(source, title, url, summary, content, published_at) "
            "VALUES (?,?,?,?,?,?)",
            (source, title, url, summary, content, published_at))
        return True


def knowledge_unconsumed(limit=20):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_knowledge WHERE consumed=0 "
            "ORDER BY fetched_at DESC, id DESC LIMIT ?",
            (limit,)).fetchall()
        return [_row_dict(r) for r in rows]


def knowledge_mark_consumed(kid):
    with get_conn() as conn:
        conn.execute(
            "UPDATE agent_knowledge SET consumed=1 WHERE id=?", (kid,))


def knowledge_all(limit=200):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_knowledge ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
        return [_row_dict(r) for r in rows]


# ═══════════════════════════════════════════
# metadata（heartbeat / 每日发文状态）
# ═══════════════════════════════════════════

def meta_get(key):
    with get_conn() as conn:
        r = conn.execute(
            "SELECT value FROM agent_metadata WHERE key=?", (key,)).fetchone()
        return r["value"] if r else None


def meta_set(key, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO agent_metadata(key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value))


# ═══════════════════════════════════════════
# 素材源（自定义站点/手动 URL）
# ═══════════════════════════════════════════

def source_add(name, url, kind="website", note=None):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agent_sources(name, url, kind, note) VALUES (?,?,?,?)",
            (name, url, kind, note))
        return cur.lastrowid


def source_list(enabled_only=True):
    with get_conn() as conn:
        if enabled_only:
            rows = conn.execute(
                "SELECT * FROM agent_sources WHERE enabled=1 "
                "ORDER BY id").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_sources ORDER BY id").fetchall()
        return [_row_dict(r) for r in rows]


def source_get(source_id):
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM agent_sources WHERE id=?", (source_id,)).fetchone()
        return dict(r) if r else None


def source_set_enabled(source_id, enabled):
    with get_conn() as conn:
        conn.execute(
            "UPDATE agent_sources SET enabled=? WHERE id=?",
            (1 if enabled else 0, source_id))


def source_delete(source_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM agent_sources WHERE id=?", (source_id,))
