"""拟人 Agent「小满」配置 — 单一事实源（RSS 源/LLM/发文节奏/路径）。

所有可调参数集中于此；运行时读取，改配置即生效（不缓存）。
"""

import os
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
DATA_DIR = AGENT_DIR / "data"
DB_PATH = DATA_DIR / "agent.db"
PERSONAS_DIR = AGENT_DIR / "personas"

# dsh 任务执行：仓库根（dsh cwd，可被 DASHBOARD_REPO_ROOT 覆盖）+ 超时
REPO_ROOT = Path(os.environ.get("DASHBOARD_REPO_ROOT") or AGENT_DIR.parent.parent)
DSH_TIMEOUT_SECONDS = 240  # 阅读要读资料包文件 + web 读多篇全文，120 太紧

PERSONA_ID = "xiaoman"

# ── RSS 订阅源（RSSHub 路由；实例按优先序尝试）──
# 实测（2026-09-09）：rsshub.app 官方实例在大陆网络 ConnectTimeout（不可达），已移除；
# 剩余实例为实测可用（wallstreetcn 全通；cls 在 pseudoyu/slarker/ktachibana 通）。
RSSHUB_INSTANCES = [
    "https://rsshub.pseudoyu.com",
    "https://hub.slarker.me",
    "https://rsshub.ktachibana.party",
    "https://rsshub.rssforever.com",
]
RSS_FEEDS = [
    {"id": "cls", "name": "财联社电报", "path": "/cls/telegraph"},
    {"id": "wallstreetcn", "name": "华尔街见闻", "path": "/wallstreetcn/live"},
]

# ── LLM（由 dsh 管理：dsh --profile xiaoman，凭据在 ~/.dsh/.credentials.yaml）──

# ── 发文节奏（D3：每天 1 篇）──
PUBLISH_HOUR = 17  # 每日发文目标时刻（17:30 收盘后）
PUBLISH_MINUTE = 30
MAX_ARTICLES_PER_DAY = 1
MIN_TOPIC_ITEMS = 3  # 一个主题至少凑齐 N 条素材才发文
TICK_SECONDS = 300  # 常驻轮询间隔
RSS_FETCH_INTERVAL_SECONDS = 3600
CUSTOM_SOURCE_FETCH_INTERVAL_SECONDS = 6 * 3600  # 自定义站点采集间隔

# ── 动态（③ 微博式短文本）──
POST_INTERVAL_MINUTES = 360  # 距上一条动态最短间隔（6 小时）
POST_ACTIVE_HOURS = (18, 23)  # 动态活跃时段 18:00-23:00

# ── 行为状态机 ──
BEHAVIORS_FILE = PERSONAS_DIR / "xiaoman" / "behaviors.md"
READING_PROMPT_FILE = PERSONAS_DIR / "xiaoman" / "reading.md"
STATE_MIN_DURATION_SECONDS = 60
READING_COOLDOWN_SECONDS = 1200  # 20 分钟

# ── 社交平台/爱逛的地方（认识小满页「爱逛的地方」+ 素材源；方案 v1.10 §9.4）──
# kind: 可达性来源分类
#   rss    = RSSHub 阅读源（财联社/华尔街见闻）：RSS 能拉到条目即可达
#   cookie = 登录态采集（微博/小红书/知乎/雪球）：有 Cookie 且探测通过即可达
#   none   = 未实施访问逻辑（X）：固定置灰，仅展示图标
# needs_cookie: 走 Cookie 登录态采集
# playable:     可成为"逛"状态素材源；X 暂不实施（仅展示图标置灰）
# cookie_keys:  该平台 Cookie 的关键 key（提示用户去浏览器 Cookie 里找哪几项）
SOCIAL_PLATFORMS = [
    {"id": "weibo",       "name": "微博",       "url": "https://weibo.com",
     "icon": "weibo",       "kind": "cookie", "needs_cookie": True,  "playable": True,
     "cookie_keys": ["SUB", "SUBP"]},
    {"id": "xhs",         "name": "小红书",     "url": "https://www.xiaohongshu.com",
     "icon": "xhs",         "kind": "cookie", "needs_cookie": True,  "playable": True,
     "cookie_keys": ["web_session", "a1", "webId"]},
    {"id": "x",           "name": "X",          "url": "https://x.com",
     "icon": "x",           "kind": "none",   "needs_cookie": False, "playable": False},
    {"id": "zhihu",       "name": "知乎",       "url": "https://www.zhihu.com/hot",
     "icon": "zhihu",       "kind": "cookie", "needs_cookie": True,  "playable": True,
     "cookie_keys": ["z_c0", "d_c0"]},
    {"id": "xueqiu",      "name": "雪球",       "url": "https://xueqiu.com/today",
     "icon": "xueqiu",      "kind": "cookie", "needs_cookie": True,  "playable": True,
     "cookie_keys": ["xq_a_token", "xq_r_token", "u"]},
    {"id": "cls",         "name": "财联社",     "url": "https://www.cls.cn/telegraph",
     "icon": "cls",         "kind": "rss",    "needs_cookie": False, "playable": False},
    {"id": "wallstreetcn", "name": "华尔街见闻", "url": "https://wallstreetcn.com/news/global",
     "icon": "wallstreetcn", "kind": "rss",   "needs_cookie": False, "playable": False},
]

# Playwright 采集源（微博/小红书/知乎/雪球）：随状态机"逛"状态触发，同轮串行
PLAYWRIGHT_SOURCES = [p for p in SOCIAL_PLATFORMS if p.get("playable")]

# 逛状态 id → 平台 id 映射（如 "weibo_browse" → "weibo"）；仅 playable 平台参与
_BROWSE_STATES = {
    f"{p['id']}_browse": p["id"]
    for p in SOCIAL_PLATFORMS
    if p.get("playable")
}


def browse_state_to_platform(state_id):
    """状态机逛状态 id → 平台 id；非逛状态返回 None。"""
    return _BROWSE_STATES.get(state_id)


def browse_state_ids():
    """全部逛状态 id 集合（如 {'weibo_browse', 'zhihu_browse', ...}）。"""
    return set(_BROWSE_STATES.keys())

# 逛状态冷却：与 READING_COOLDOWN_SECONDS 对齐但**独立**（逛完仍可进 reading）
BROWSE_COOLDOWN_SECONDS = 1200  # 20 分钟

# 标题相似度去重阈值（difflib.SequenceMatcher 字符级，0.85，不引 embedding）
TITLE_SIMILARITY_THRESHOLD = 0.85

# 逛状态采集/浏览超时（秒）与采集条数上限
BROWSE_COLLECT_TIMEOUT_SECONDS = 90
BROWSE_COLLECT_LIMIT = 15
BROWSE_READ_LIMIT = 5

# ── 合规（允许点评个股 + 强约束）──
# 输出中禁止出现的确定性买卖指令动词
FORBIDDEN_VERBS = (
    "买入",
    "卖出",
    "加仓",
    "清仓",
    "建仓",
    "止损",
    "止盈",
    "赶紧买",
    "赶紧卖",
)
