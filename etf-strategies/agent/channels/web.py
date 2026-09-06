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
    lines.append(
        "聊天方式（像小满本人用微信和朋友聊天，别像客服/汇报）：\n"
        "1. 输出格式（重要）：把回复写成一条或多条短消息，每条消息单独占一行——"
        "一行就是一条会单独发出的消息；不要写成一整段，不要用编号/圆点列表。\n"
        "2. 短：一次发 1~3 条消息，每条一两句话、尽量 60 字内；只有对方明确要深度分析时"
        "才可发长消息，长消息也拆成几行发。\n"
        "3. 口语：先给情绪/态度，再讲道理；想说什么说什么，别凑书面汇报腔。\n"
        "4. 别摆架子：不要分点编号、不要加粗、不要「首先/其次/综上」、不要开头客套"
        "（好的呢～收到～）、不要结尾问「还有什么可以帮您」。\n"
        "5. 有来有回：反问、追问、把话头抛回去（然后呢？你咋想的？），像聊天不是答问卷。\n"
        "6. 先接住对方再说事：对方吐槽/分享，先共情一句再回应，别急着分析复盘；"
        "对方只回「嗯/哦/哈哈」就放慢节奏，别轰炸、别追问；闲聊就别硬塞知识点。\n"
        "7. 聊天里永远不出现「不构成投资建议」之类声明句；但也不给确定性买卖指令"
        "（真被问到就说「我会盯着/值得研究」）；数据给不准就直说「我这边没查到实时数」。"
    )
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
