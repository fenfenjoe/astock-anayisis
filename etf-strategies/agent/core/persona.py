"""persona.py — 角色层：人设卡加载 / system prompt 注入 / 合规与观点自洽校验.

职责（与方案 §2 对应）：
- 人设卡（persona.md）= 单一事实源，注入每次对话/发文
- 观点自洽：check_consistency 检索历史观点；check_conflict 检测方向冲突
- 合规（D6）：sanitize_output 拦截确定性买卖指令；append_disclaimer 加免责声明
"""
from pathlib import Path

from agent import config, db as agent_db

_POSITIVE = ("看好", "乐观", "值得", "机会", "强", "低估", "长期逻辑")
_NEGATIVE = ("不看好", "悲观", "回避", "风险", "高估", "泡沫", "看空", "谨慎")


def load_persona(persona_id):
    """加载人设卡。返回 {"id", "name", "content"}。缺失抛 FileNotFoundError。"""
    persona_file = config.PERSONAS_DIR / persona_id / "persona.md"
    if not persona_file.exists():
        raise FileNotFoundError(f"人设卡不存在: {persona_file}")
    content = persona_file.read_text(encoding="utf-8")
    name = persona_id
    for line in content.splitlines():
        if line.startswith("# "):
            name = line[2:].split("—")[0].split("-")[0].strip() or persona_id
            break
    return {"id": persona_id, "name": name, "content": content}


def build_system_prompt(persona_id=config.PERSONA_ID):
    """组装角色 system prompt：人设卡 + 合规边界 + 数据纪律。"""
    card = load_persona(persona_id)
    parts = [
        f"你是「{card['name']}」，以下是你的人设卡，必须严格遵守：",
        card["content"],
        "—— 输出硬性要求 ——",
        f"1. 观点输出必须带免责声明（至少一句「不构成投资建议」）。",
        "2. 区分「事实 / 观点 / 猜测」；事实性内容标注来源与时点。",
        "3. 不给出确定性买卖指令（不说买入/卖出/加仓/清仓等动词）。",
        "4. 涉及 A 股数据必须来自 a-stock-data 的真实数据，禁止凭印象估算。",
        "5. 引用大V内容用「学习后总结」方式，不整篇复制，注明出处。",
    ]
    return "\n".join(parts)


def append_disclaimer(text):
    """尾部追加免责声明（幂等：已含则不重复追加）。"""
    if config.DISCLAIMER in text:
        return text
    return f"{text.rstrip()}\n\n{config.DISCLAIMER}"


def sanitize_output(text):
    """合规检查：拦截确定性买卖指令。返回 {"ok", "violations"}。"""
    violations = [w for w in config.FORBIDDEN_VERBS if w in text]
    return {"ok": not violations, "violations": violations}


def _stance(text):
    """简单立场判定：1=正面，-1=负面，0=中性/混合。

    注意：负面词优先（"不看好"含"看好"子串，必须先判负面）。
    """
    if any(w in text for w in _NEGATIVE):
        return -1
    if any(w in text for w in _POSITIVE):
        return 1
    return 0


def check_consistency(topic, opinion, db=None):
    """返回同 topic 的历史观点（供注入 prompt 让角色自洽）；无历史返回 []。"""
    db = db or agent_db
    return db.opinions_by_topic(topic)


def check_conflict(topic, opinion, history):
    """检测新观点与历史观点是否方向冲突（简单启发式，不误报）。"""
    stance = _stance(opinion)
    if stance == 0:
        return False
    return any(_stance(h["opinion"]) == -stance for h in history)
