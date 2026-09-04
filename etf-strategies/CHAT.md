# 小满行为状态机 — 设计方案 v3

## 核心调整（相对于 v2）

1. **RSSHub 拉取并入"阅读"Prompt**：不再是 tick 的固定步骤，而是小满进入"阅读"时，Prompt 指导她用 RSSHub 工具浏览他有订阅的源（财联社电报、华尔街见闻、知乎热榜、雪球热帖），按自己的喜好挑文章 → 用 web 工具读全文 → 生成感受和动态
2. **状态决策硬编码**：不浪费 LLM 调用，行为池用 Python 随机+权重选，只有"阅读"才调用 LLM
3. **非阅读活动纯状态标记**：发呆/打游戏/睡觉等只是改 metadata + 计时间，不需要 LLM

## 改动点清单（与现状代码的 diff）

| 文件 | 动作 | 改动 |
|------|------|------|
| `agent/config.py` | 改 | 加 `BEHAVIORS_FILE`、`READING_PROMPT_FILE`、`STATE_CHECK_INTERVAL_SECONDS`；移除 `POST_ACTIVE_HOURS`（动态由 Prompt 自由决定） |
| `personas/xiaoman/behaviors.md` | **新增** | 30+ 种行为池，JSON 格式供 Python 直接解析 |
| `personas/xiaoman/reading.md` | **新增** | 完整的阅读 Prompt 模板（RSSHub 浏览 → 选文章 → 读全文 → 感受 → 动态） |
| `agent/core/behavior.py` | 改 | 删 `should_trigger_post`、`compose_post_from_group`（已删）；新增 `pick_random_state()`、`execute_reading()`；简化 `dsh_task_llm` 不变 |
| `agent/core/lifecycle.py` | 改 | tick 简化：删 `_cluster_viewpoints`、`_max_posts`、`_label_group`；RSS 拉取从 tick 删掉；状态管理用硬编码 |
| `agent/core/knowledge.py` | 不变 | `fetch_and_store` 保留供 reading.md 调用，但不再由 tick 触发 |
| `agent/db.py` | 不改 | `agent_metadata` 已有 `xiaoman_current_state` / `xiaoman_state_until`（无需新增列） |
| `agent/dashboard/api_agent.py` | 改 | `/status` 返回中加入 `current_state`、`state_until` |
| 前端 `pet.js` | 可选 | 根据状态切换台词 |

---

## 新增文件

### 1. `personas/xiaoman/behaviors.md`

```json
{
  "behaviors": [
    {"id": "reading",    "label": "📖 阅读",  "weight": 15, "duration_min": 30, "duration_max": 60,  "require_llm": true},
    {"id": "gaming",     "label": "🎮 打游戏", "weight": 12, "duration_min": 30, "duration_max": 90,  "require_llm": false},
    {"id": "drama",      "label": "🎬 煲剧",   "weight": 10, "duration_min": 30, "duration_max": 60,  "require_llm": false},
    {"id": "shopping",   "label": "🛍️ 逛淘宝", "weight": 8,  "duration_min": 15, "duration_max": 45,  "require_llm": false},
    {"id": "music",      "label": "🎧 听歌",   "weight": 8,  "duration_min": 10, "duration_max": 30,  "require_llm": false},
    {"id": "cooking",    "label": "🍳 煮泡面", "weight": 6,  "duration_min": 10, "duration_max": 25,  "require_llm": false},
    {"id": "cat",        "label": "🐱 撸猫",   "weight": 7,  "duration_min": 15, "duration_max": 45,  "require_llm": false},
    {"id": "yoga",       "label": "🧘 做瑜伽", "weight": 5,  "duration_min": 15, "duration_max": 30,  "require_llm": false},
    {"id": "tea",        "label": "☕ 喝奶茶", "weight": 8,  "duration_min": 10, "duration_max": 25,  "require_llm": false},
    {"id": "drawing",    "label": "🎨 画画",   "weight": 5,  "duration_min": 30, "duration_max": 60,  "require_llm": false},
    {"id": "social",     "label": "📱 刷朋友圈", "weight": 8,  "duration_min": 8,  "duration_max": 20,  "require_llm": false},
    {"id": "cleaning",   "label": "🧹 收拾房间", "weight": 4,  "duration_min": 15, "duration_max": 30,  "require_llm": false},
    {"id": "takeout",    "label": "🍜 叫外卖", "weight": 6,  "duration_min": 8,  "duration_max": 20,  "require_llm": false},
    {"id": "nap",        "label": "💤 补觉",   "weight": 6,  "duration_min": 20, "duration_max": 60,  "require_llm": false},
    {"id": "daydream",   "label": "🌙 发呆",   "weight": 10, "duration_min": 8,  "duration_max": 30,  "require_llm": false},
    {"id": "sleep",      "label": "😴 睡觉",   "weight": 0,  "duration_min": 120, "duration_max": 360, "require_llm": false},
    {"id": "emo",        "label": "🌧️ emo",   "weight": 3,  "duration_min": 10, "duration_max": 30,  "require_llm": false},
    {"id": "writing",    "label": "📝 写日记", "weight": 5,  "duration_min": 10, "duration_max": 25,  "require_llm": false},
    {"id": "thinking",   "label": "💡 思考",   "weight": 6,  "duration_min": 10, "duration_max": 30,  "require_llm": false}
  ],
  "time_modifiers": {
    "sleep":      {"after_hour": 23, "weight_bonus": 80},
    "gaming":     {"after_hour": 18, "weight_bonus": 15},
    "drama":      {"after_hour": 19, "weight_bonus": 10},
    "nap":        {"hour_range": [13, 15], "weight_bonus": 25}
  },
  "unread_bonus": {
    "target": "reading",
    "per_article_weight": 3
  },
  "cooldown": {
    "max_repeat": 2,
    "prevent_for_ticks": 0
  }
}
```

### 2. `personas/xiaoman/reading.md`

```markdown
你是小满。现在你进入了「📖 阅读」状态。

## 你的工具

有一个专门的函数 `rsshub_browse()` 可以帮你：
- 浏览你订阅的财经源：财联社电报、华尔街见闻、知乎热榜、雪球热帖
- 它会返回最近的文章（标题 + 链接 + 摘要）

你也可以用 web 工具：
- 打开任意文章链接阅读全文

## 第一步：逛 RSSHub 找文章

调用 rsshub_browse() 拉取你订阅的 4 个源。
浏览返回的文章列表，按你自己的喜好挑选 3~8 篇你真正想读的文章——
挑你感兴趣的话题、让你好奇的标题、你觉得有价值的。

不要全部拉取，只挑你真的想看的。

## 第二步：读文章

对每一篇挑中的文章，用 web 工具打开链接阅读全文。
注意：有些链接可能需要你的 dsh web 工具能访问，不行就跳过。

## 第三步：记录你的感受

对每篇读过的文章，在心里（不需要输出）记下：
- 这篇文章的核心观点是什么？
- 你读完是什么感觉？（激动 / 生气 / 好奇 / 平静 / 怀疑）
- 有没有联想到什么？（你过去读过的东西、生活中的小事…）

## 第四步：发动态（可选）

你可以发，也可以不发。但如果有文章：
- 观点让你眼前一亮（有参考价值）
- 情绪被强烈触动
- 你觉得朋友圈的人会感兴趣
——那就发一条。

格式：像发朋友圈，50 字左右，内容多则将内容归类，然后分开成多条动态发送，口语化，你的风格。
你可以综合多篇文章一起发，也可以单独写。

## 最后

结束时输出一个 JSON（放在最后面，不要夹在中间）：

{
  "read_count": 读了几篇,
  "articles": [
    {
      "title": "原文标题",
      "url": "原文链接（用于匹配）",
      "viewpoint": "核心观点（30字内）",
      "emotion": "excited|angry|curious|calm|skeptical",
      "memory": "你的个人感受（50字内）"
    }
  ],
  "posts": [
    {"content": "动态全文（含不构成投资建议声明）"}
  ]
}

## 重要
- 不要硬凑，真诚就好
- 无聊就不发动态
- 不要变成机器人在做任务，你是小满
```

---

## 修改文件

### 3. `agent/config.py`

```python
# 在现有内容后追加

# ══ 行为状态机 ══
BEHAVIORS_FILE = PERSONAS_DIR / PERSONA_ID / "behaviors.md"
READING_PROMPT_FILE = PERSONAS_DIR / PERSONA_ID / "reading.md"
# 状态至少持续这么久才可能切换（秒），避免高频决策
STATE_MIN_DURATION_SECONDS = 60
# 阅读节流：距上次阅读至少间隔（秒），避免刚读完又读
READING_COOLDOWN_SECONDS = 1200  # 20 分钟
```

### 4. `agent/core/behavior.py`

删掉现有 `should_trigger_post`、`compose_post_from_group`（已删）、`run_post_pipeline`（不再需要定时动态）。

新增：

```python
import json as _json
import random
from datetime import datetime, timedelta

from agent import config, db as agent_db, dsh_runner
from agent.core import persona


def dsh_task_llm(task):
    # 保持不变
    status, out = dsh_runner.run_task(task)
    if status != "success":
        raise dsh_runner.DshRunnerError(f"dsh {status}: {out}")
    return out


def load_behaviors():
    """加载行为池 → Python dict。"""
    raw = config.BEHAVIORS_FILE.read_text(encoding="utf-8")
    return _json.loads(raw)


def load_reading_prompt():
    """加载阅读 Prompt 模板。"""
    return config.READING_PROMPT_FILE.read_text(encoding="utf-8")


def pick_random_state(now=None, db=None):
    """硬编码权重随机选状态。

    根据当前时间调整权重（晚上给 sleep/gaming 加权）、
    未读数量给 reading 加权。

    返回 {"id","label","duration_minutes","until_iso"}。
    """
    now = now or datetime.now()
    db = db or agent_db
    pool = load_behaviors()
    behaviors = pool["behaviors"]
    time_mods = pool.get("time_modifiers", {})
    unread_bonus = pool.get("unread_bonus", {})
    cooldown = pool.get("cooldown", {})

    # 防重复：上一个状态如果是 reading，给其他加权
    last_state = db.meta_get("xiaoman_current_state") or ""

    # 计算每个行为的有效权重
    weights = []
    for b in behaviors:
        w = b["weight"]
        # 时间修正
        mod = time_mods.get(b["id"])
        if mod:
            ah = mod.get("after_hour")
            hr = mod.get("hour_range")
            if ah and now.hour >= ah:
                w += mod.get("weight_bonus", 0)
            if hr and hr[0] <= now.hour <= hr[1]:
                w += mod.get("weight_bonus", 0)
        # 未读修正（有文章时，"阅读"权重更高）
        if b["id"] == unread_bonus.get("target"):
            unread_count = len(db.knowledge_unread(limit=200))
            w += unread_bonus.get("per_article_weight", 0) * unread_count
        # 冷却：上次是 reading，降低本次 reading 权重
        if b["id"] == "reading" and last_state == "reading":
            w = max(1, w // 2)
        # sleep 深夜才能选
        if b["id"] == "sleep" and w == 0 and now.hour < 23:
            w = 0
        weights.append(max(1, w))

    # 轮盘赌
    chosen = random.choices(behaviors, weights=weights, k=1)[0]
    duration = random.randint(chosen["duration_min"], chosen["duration_max"])
    until = now + timedelta(minutes=duration)

    return {
        "id": chosen["id"],
        "label": chosen["label"],
        "require_llm": chosen.get("require_llm", False),
        "duration_minutes": duration,
        "until_iso": until.isoformat(),
        "until_display": until.strftime("%H:%M"),
    }


def execute_reading(db=None, llm_fn=None):
    """执行阅读行为（进入"阅读"时调用一次）。

    加载 reading.md → 注入当前时间 → dsh 调用 → LLM 自由执行
    （浏览 RSSHub → 挑文章 → 读全文 → 感受 → 动态）。

    返回 {"read_count", "posted_count", "error": str|None}。
    """
    db = db or agent_db
    llm_fn = llm_fn or dsh_task_llm

    template = load_reading_prompt()
    now = datetime.now()
    task = template + f"\n\n（现在是 {now.strftime('%Y-%m-%d %H:%M')}）"

    text = llm_fn(task)
    result = _parse_reading_output(text)

    # 写入记忆
    for art in result.get("articles", []):
        url = art.get("url") or ""
        if not url:
            continue
        matched = next(
            (k for k in db.knowledge_all(limit=500) if k["url"] == url), None
        )
        if matched:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db.knowledge_set_memory(
                matched["id"],
                viewpoint=art.get("viewpoint"),
                emotion=art.get("emotion"),
                memory=art.get("memory"),
                read_at=now_str,
            )

    # 写入动态
    posted = 0
    for post in result.get("posts", []):
        content = (post.get("content") or "").strip()
        if not content:
            continue
        content = persona.append_disclaimer(content)
        if not validate_article(content, min_len=10)["ok"]:
            continue
        db.article_create(
            datetime.now().strftime("%Y-%m-%d"),
            content[:120],
            content,
            topics=["动态"],
            sources=[],
            kind="post",
        )
        posted += 1

    err = result.get("_parse_error")
    return {
        "read_count": result.get("read_count", 0),
        "posted_count": posted,
        "error": err,
    }


def _parse_reading_output(text):
    """解析阅读输出 → {read_count, articles[], posts[], _parse_error}。

    容错策略：取最后一个完整的 {...} JSON 块，不依赖 LLM 输出纯净。
    """
    if not text:
        return {"read_count": 0, "articles": [], "posts": [], "_parse_error": "empty"}
    raw = text.strip()
    start, end = raw.rfind("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return {"read_count": 0, "articles": [], "posts": [],
                "_parse_error": "no_json_block"}
    raw = raw[start:end + 1]
    try:
        obj = _json.loads(raw)
    except Exception as e:
        return {"read_count": 0, "articles": [], "posts": [],
                "_parse_error": f"json_parse: {e}"}
    return {
        "read_count": int(obj.get("read_count") or 0),
        "articles": obj.get("articles") or [],
        "posts": obj.get("posts") or [],
        "_parse_error": None,
    }


# ══ 以下的 validate_article、run_publish_pipeline、compose_article 保持不变 ══
```

### 5. `agent/core/lifecycle.py`

删掉现有的 `_cluster_viewpoints`、`_max_posts`、`_label_group`（约 50 行）。
删掉 tick 中的 RSS 拉取步骤和阅读/动态硬编码逻辑。

tick 简化后：

```python
def tick(now=None, db=None, llm_fn=None):
    """一轮例行工作。

    1. heartbeat
    2. 自定义源采集（节流，高成本）
    3. 状态机：检查过期 → 硬编码选状态 → 选到阅读时执行阅读 Prompt
    4. 每日发文调度
    5. cloud backup
    """
    now = now or datetime.now()
    db = db or agent_db
    today = now.strftime("%Y-%m-%d")
    heartbeat(db)

    result = {
        "today": today,
        "custom": None,
        "state": None,
        "read": None,
        "publish": None,
    }

    # 1. 自定义源采集（节流，保留：不频繁的LLM调用）
    if _custom_due(db, now):
        try:
            result["custom"] = knowledge.collect_custom_sources(
                db=db, llm_fn=llm_fn
            )
            db.meta_set(
                "last_custom_fetch_at", now.strftime("%Y-%m-%d %H:%M:%S")
            )
        except Exception as e:
            result["custom"] = {"error": str(e)}

    # 2. 状态机：检查当前状态是否过期
    state_current = db.meta_get("xiaoman_current_state")
    state_until = db.meta_get("xiaoman_state_until")
    state_expired = True
    if state_until:
        try:
            if datetime.strptime(state_until, "%Y-%m-%d %H:%M:%S") > now:
                state_expired = False
        except ValueError:
            pass

    # 3. 状态过期 → 硬编码随机选新状态
    if state_expired:
        decision = behavior.pick_random_state(db=db, now=now)
        until_dt = datetime.fromisoformat(decision["until_iso"])
        db.meta_set("xiaoman_current_state", decision["id"])
        db.meta_set(
            "xiaoman_state_until", until_dt.strftime("%Y-%m-%d %H:%M:%S")
        )

        # 如果选到"阅读"，立即执行阅读 Prompt（这会产生一次 LLM 调用）
        if decision["require_llm"] and decision["id"] == "reading":
            try:
                result["read"] = behavior.execute_reading(
                    db=db, llm_fn=llm_fn
                )
            except Exception as e:
                result["read"] = {"error": str(e)}

        result["state"] = {
            "id": decision["id"],
            "label": decision["label"],
            "duration_minutes": decision["duration_minutes"],
            "until": decision["until_display"],
        }
    else:
        result["state"] = {
            "id": state_current or "daydream",
            "label": _state_label(state_current or "daydream"),
            "active": True,
        }

    # 4. 每日发文
    try:
        result["publish"] = behavior.run_publish_pipeline(
            today, now=(now.hour, now.minute), llm_fn=llm_fn, db=db
        )
    except Exception as e:
        result["publish"] = {
            "published": False,
            "reason": f"error: {e}",
        }

    # 5. cloud backup
    try:
        result["backup"] = agent_db.cloud_backup()
    except Exception as e:
        result["backup"] = {"error": str(e)}
    return result


def _state_label(state_id):
    """给 state_id 返回一个人类可读标签（用于前端展示）。"""
    labels = {
        "reading": "📖 阅读",
        "gaming": "🎮 打游戏",
        "drama": "🎬 煲剧",
        "shopping": "🛍️ 逛淘宝",
        "music": "🎧 听歌",
        "cooking": "🍳 煮泡面",
        "cat": "🐱 撸猫",
        "yoga": "🧘 做瑜伽",
        "tea": "☕ 喝奶茶",
        "drawing": "🎨 画画",
        "social": "📱 刷朋友圈",
        "cleaning": "🧹 收拾房间",
        "takeout": "🍜 叫外卖",
        "nap": "💤 补觉",
        "daydream": "🌙 发呆",
        "sleep": "😴 睡觉",
        "emo": "🌧️ emo",
        "writing": "📝 写日记",
        "thinking": "💡 思考",
    }
    return labels.get(state_id, "🌙 发呆")
```

### 6. `agent/dashboard/api_agent.py`

`/status` 返回中加入：

```python
state = agent_db.meta_get("xiaoman_current_state")
until = agent_db.meta_get("xiaoman_state_until")
# ... 在返回 dict 中增加字段
"current_state": state or "daydream",
"current_state_label": _state_label(state or "daydream"),
"state_until": until,
```

---

## 数据流（新版完整）

```
tick() 每 300s 执行一次
│
├─ heartbeat
│
├─ [若超过 6h] 自定义站点采集（LLM 调用）
│     → knowledge.collect_custom_sources()
│     → dsh 逛站找文章 → 入库
│
├─ 状态机检查
│   │
│   ├─ 当前状态未过期 → 跳过（什么都不做）
│   │
│   └─ 当前状态过期 → pick_random_state()
│         │
│         ├─ 权重：未读文章越多 → "阅读"权重越高
│         ├─ 时间：晚上 gaming/drama 加权，深夜 sleep 才出现
│         ├─ 冷却：刚读完不连读
│         │
│         ├─ 选到 "reading"（唯一需要 LLM 的状态）
│         │     → execute_reading()
│         │     → dsh 执行 reading.md Prompt（一次 LLM 调用）
│         │     → LLM 在 dsh session 内：
│         │         ① 调用 rsshub_browse() 拉取 4 个订阅源
│         │         ② 按自己的喜好从返回列表中挑文章
│         │         ③ 用 web 工具逐一读全文
│         │         ④ 生成观点/情绪/记忆
│         │         ⑤ 自己决定发几条动态
│         │     → Python 后处理：
│         │         - 解析 JSON → 写 memory 到 knowledge
│         │         - 动态写入 agent_articles
│         │
│         └─ 选到其他状态（gaming/sleep/发呆...）
│               → 只写 metadata（current_state + state_until）
│               → 前端状态栏显示对应图标+标签
│
├─ 每日发文（17:30 后触发，仅一次 LLM 调用）
│
└─ cloud backup
```

---

## LLM 调用成本分析

| 场景 | 调用 | 频率 | 说明 |
|------|------|------|------|
| 小满选中"阅读" | 1 次 dsh | 概率 ~15-30%/tick | 30分钟状态结束后，下次 tick 重新选。若天天有新文章，每天约读2-4次 |
| 自定义源采集 | 1 次 dsh | 每 6 小时 | 自定义站点逛站 |
| 每日发文 | 1 次 dsh | 每天 1 次 | 17:30 收盘后 |
| 用户聊天 | 1 次 dsh/条 | 用户触发 | 聊天回复 |
| **合计（非聊天）** | | **约 3~7 次/天** | 不聊天的话，主要是阅读（2~4次）+ 采集（最多4次）+ 发文（1次） |

对比旧方案旧方案每天仅 300/60= 5 次 LLM 决策 + 同样数量的阅读动态调用。新方案反而更省：状态决策是硬编码的，不产生 LLM 调用。

---

## 关键实现细节

### rsshub_browse() 在 dsh 中的暴露方式
当前知识体系：`fetch_and_store()` 是 Python 函数，dsh 不能直接调用。
选项A（推荐）：在 reading.md 中点名 — "你有一个工具叫 'rsshub_browse'，它会拉取 4 个源的最近文章..." —— 但实际上 LLM 没有这个工具，因为它不在 dsh 的 sandbox 中。
方案：**tick 中 RSS 拉取仍然保留**，但在 reading.md 中这样写：

> "自动拉取"方式：tick 中执行 `fetch_and_store()` 入库（服务器端完成），小满进入阅读时，Prompt 中注入已入库的未读摘要，小满按喜好挑文章，用 `web` 工具读全文。

这样的话：RSSHub 拉取虽然仍在 tick 里面做，但"阅读"Prompt 告诉小满从已拉取的列表中「按喜好挑选」，这更符合"小满有自主权"的感觉。

---

## 标注：后面实际实现时可能遇到的卡点

1. **JSON 解析容错**：LLM 在 reading.md 流程中输出的 JSON 可能被创造性文字污染，`_parse_reading_output` 只取最后一个 `{...}` 块是防御策略
2. **dsh 内的 web 工具可用性**：一些付费墙或国内网站可能 dsh web fetch 不了，需要在 Prompt 写明"不行就跳过"
3. **state_until 时间格式**：ISO 格式 vs `%Y-%m-%d %H:%M:%S` 格式要统一
