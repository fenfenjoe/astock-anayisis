"""channels/web.py — Web 渠道：聊天 directive 组装 + 文章呈现数据.

核心原则（方案 §5.1）：Persona 不知道 Channel 存在；本模块只把角色能力
映射成 web API 需要的数据形态。
dsh 化后：人设由 `dsh --profile xiaoman` 注入（system-prompt persona），
聊天只需组装「历史 + 用户消息」作为 task 文本。
"""
from agent import db as agent_db
from agent.core import memory


def chat_task(session_id, user_input, db=None):
    """组装聊天 directive：今日素材 + 会话历史 + 用户消息。

    返回 (task_text, knowledge_items)。
    """
    db = db or agent_db
    history = memory.build_chat_context(session_id, db=db)
    knowledge = db.knowledge_unconsumed(limit=5)

    lines = []
    if knowledge:
        lines.append("今天学到的素材（可引用，注意区分事实与观点）：")
        lines.extend(
            f"- [{k['source']}] {k['title']} ({k['url']})" for k in knowledge)
        lines.append("")
    for m in history:
        speaker = "用户" if m["role"] == "user" else "小满"
        lines.append(f"{speaker}：{m['content']}")
    lines.append(f"用户：{user_input}")
    lines.append("")
    lines.append("请以小满的身份直接回复这条用户消息，不要复述人设，不要复述历史。")
    return "\n".join(lines), knowledge


def article_card(article):
    """文章/动态呈现数据（列表项用）。"""
    return {
        "id": article["id"],
        "title": article["title"],
        "summary": article.get("summary") or "",
        "published_at": article.get("published_at"),
        "topics": article.get("topics") or [],
        "sources": article.get("sources") or [],
        "status": article.get("status"),
        "kind": article.get("kind") or "article",
    }
