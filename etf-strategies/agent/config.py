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
REPO_ROOT = Path(os.environ.get("DASHBOARD_REPO_ROOT")
                 or AGENT_DIR.parent.parent)
DSH_TIMEOUT_SECONDS = 120

PERSONA_ID = "xiaoman"

# ── RSS 订阅源（RSSHub 路由；实例按优先序尝试）──
RSSHUB_INSTANCES = [
    "https://rsshub.app",
    "https://rsshub.rssforever.com",
]
RSS_FEEDS = [
    {"id": "cls", "name": "财联社电报", "path": "/cls/telegraph"},
    {"id": "wallstreetcn", "name": "华尔街见闻", "path": "/wallstreetcn/live"},
    {"id": "zhihu", "name": "知乎热榜", "path": "/zhihu/hotlist"},
    {"id": "xueqiu", "name": "雪球热帖", "path": "/xueqiu/hots"},
]

# ── LLM（由 dsh 管理：dsh --profile xiaoman，凭据在 ~/.dsh/.credentials.yaml）──

# ── 发文节奏（D3：每天 1 篇）──
PUBLISH_HOUR = 17              # 每日发文目标时刻（17:30 收盘后）
PUBLISH_MINUTE = 30
MAX_ARTICLES_PER_DAY = 1
MIN_TOPIC_ITEMS = 3            # 一个主题至少凑齐 N 条素材才发文
TICK_SECONDS = 300             # 常驻轮询间隔
RSS_FETCH_INTERVAL_SECONDS = 3600
CUSTOM_SOURCE_FETCH_INTERVAL_SECONDS = 6 * 3600  # 自定义站点采集间隔

# ── 动态（③ 微博式短文本）──
POST_INTERVAL_MINUTES = 360    # 距上一条动态最短间隔（6 小时）
POST_ACTIVE_HOURS = (18, 23)   # 动态活跃时段 18:00-23:00

# ── 合规（D6：允许点评个股 + 强约束）──
DISCLAIMER = "以上仅为小满的个人学习笔记与观点，不构成投资建议。"
# 输出中禁止出现的确定性买卖指令动词
FORBIDDEN_VERBS = ("买入", "卖出", "加仓", "清仓", "建仓", "止损", "止盈", "赶紧买", "赶紧卖")
