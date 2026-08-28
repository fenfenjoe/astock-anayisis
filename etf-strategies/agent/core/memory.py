"""memory.py — 记忆系统：会话上下文 / 观点记忆 / 偏好（薄封装 db）.

短期记忆：build_chat_context() 把会话历史转成 LLM messages。
长期记忆：观点库 opinions（供 persona 自洽校验）+ preferences（metadata 预留）。
"""
from agent import db as agent_db


def build_chat_context(session_id, db=None, limit=30):
    """组装会话历史 → [{role, content}]（给 LLM 的上下文，最近 limit 条）。"""
    db = db or agent_db
    msgs = db.messages_by_session(session_id)[-limit:]
    return [{"role": m["role"], "content": m["content"]} for m in msgs]


def remember_opinion(topic, opinion, article_id=None, db=None):
    """把观点归档进观点库（长期记忆，persona 自洽校验的数据源）。"""
    db = db or agent_db
    return db.opinion_add(topic, opinion, article_id=article_id)


def remember_preference(key, value, db=None):
    """偏好记忆（预留：用户偏好存 metadata，key 加 pref_ 前缀）。"""
    db = db or agent_db
    db.meta_set(f"pref_{key}", value)


def get_preference(key, db=None):
    db = db or agent_db
    return db.meta_get(f"pref_{key}")
