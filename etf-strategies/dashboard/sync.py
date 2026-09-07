"""数据同步模块 — 增量刷新 K 线 / 策略指标 / 信号 / NAV 到 SQLite.

所有网络 I/O 集中在此模块；app.py 仅调用 sync 函数完成数据刷新。
"""
import sys
import json
import traceback
from pathlib import Path
from datetime import date, timedelta

_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from dashboard.db import (
    get_conn, init_db, is_seeded, mark_seeded,
    kline_latest_date, kline_upsert_batch,
    metrics_upsert, metrics_get_one, metrics_get_all,
    signals_upsert, signals_delete_old,
    kb_upsert,
    nav_upsert_batch, nav_has_data,
)
try:
    from cloud_db import select as _cd_select
except Exception:  # 云未配置时保持可导入（非云模式不触发）
    _cd_select = None

import threading

# ── All unique ETF codes used across 16 strategies ──
ALL_ETF_CODES = [
    "510300", "510500", "510180", "159915", "588000",  # 宽基
    "511260", "511880", "511010",                        # 债券/货币
    "518880", "513100", "159949",                        # 商品/海外
    "512010", "512880", "512800", "512660",              # 行业
    "512480", "512690", "512400", "512720",
    "515790", "515030", "512100",
]

# ── Strategy definitions (for seeding + backtest) ──
STRATEGY_DEFS = [
    {"id": "S1",  "name": "买入持有",           "category": "被动投资", "category_cn": "被动投资 / 基准",
     "assets": ["510300"], "desc": "恒满仓沪深300ETF不动，作为所有策略对照基准。",
     "window": "2012-05-28~2026-08-31 (约14年)",
     "cls": "BuyHold", "mod": "backtest.strategies.buy_hold",
     "kwargs": {"code": "510300"}},
    {"id": "S2",  "name": "双动量",             "category": "动量",     "category_cn": "动量 / 避险",
     "assets": ["510300", "511260", "511880"], "desc": "Gary Antonacci双动量：绝对+相对动量，股票/债券/货币三态切换。",
     "window": "2017-08-24~2026-08-31 (约9年)",
     "cls": "DualMomentum", "mod": "backtest.strategies.dual_momentum",
     "kwargs": {"lookback": 250}},
    {"id": "S3",  "name": "均线趋势",           "category": "趋势",     "category_cn": "趋势跟踪",
     "assets": ["510300", "511880"], "desc": "MA20上穿MA60→满仓持股，下穿→空仓持货币，月末评估。",
     "window": "2013-04-18~2026-08-31 (约13年)",
     "cls": "MATrend", "mod": "backtest.strategies.ma_trend",
     "kwargs": {"short": 20, "long": 60}},
    {"id": "S4",  "name": "多资产动量轮动",     "category": "动量",     "category_cn": "动量轮动",
     "assets": ["518880", "513100", "159915", "510180"], "desc": "25日log-price OLS，年化收益×R²打分，四资产轮动，每日调仓。",
     "window": "2013-07-29~2026-08-31 (约13年)",
     "cls": "MomentumRotation", "mod": "backtest.strategies.momentum_rotation",
     "kwargs": {"lookback": 25, "top_n": 1}},
    {"id": "S5",  "name": "等权组合",           "category": "因子",     "category_cn": "因子 / 等权",
     "assets": ["510300", "510500", "159915", "511260"], "desc": "四资产各25%等权，季末再平衡自带逆向Alpha。",
     "window": "2017-08-24~2026-08-31 (约9年)",
     "cls": "EqualWeight", "mod": "backtest.strategies.equal_weight", "kwargs": {}},
    {"id": "S6",  "name": "60-40股债平衡",      "category": "资产配置", "category_cn": "资产配置",
     "assets": ["510300", "511260"], "desc": "60%股票+40%债券，季末再平衡，经典配置基准。",
     "window": "2017-08-24~2026-08-31 (约9年)",
     "cls": "Portfolio6040", "mod": "backtest.strategies.portfolio_6040", "kwargs": {}},
    {"id": "S7",  "name": "目标波动率",         "category": "风控",     "category_cn": "风险控制",
     "assets": ["510300", "511880"], "desc": "目标15%年化波动，实现波动率↑→降仓，↓→加仓，自适应风控。",
     "window": "2013-04-18~2026-08-31 (约13年)",
     "cls": "TargetVol", "mod": "backtest.strategies.target_vol",
     "kwargs": {"target_vol": 0.15, "window": 20}},
    {"id": "S8",  "name": "三因子动量轮动",     "category": "多因子",   "category_cn": "多因子动量",
     "assets": ["513100", "159915", "510180", "518880"], "desc": "斜率+乖离+效率三因子加权，阈值1.5×过滤冗余切换。",
     "window": "2013-07-29~2026-08-31 (约13年)",
     "cls": "ThreeFactorMomentum", "mod": "backtest.strategies.three_factor_momentum",
     "kwargs": {"lookback": 25, "top_n": 1, "threshold": 1.5}},
    {"id": "S9",  "name": "行业动量轮动",       "category": "行业",     "category_cn": "行业轮动",
     "assets": ["512010", "512880", "512800", "512660", "510300"], "desc": "5行业+1宽基按60日动量排名，选Top-3，月末调仓。",
     "window": "2017-08-03~2026-08-31 (约9年)",
     "cls": "IndustryMomentum", "mod": "backtest.strategies.industry_momentum",
     "kwargs": {"lookback": 60, "top_n": 3}},
    {"id": "S10", "name": "低波动因子",         "category": "因子",     "category_cn": "多因子 / 低波动",
     "assets": ["510300", "511260", "518880", "510500", "159915", "512800"], "desc": "低波异象：60日波动率排序选最低3只，全库最优夏普+最低回撤。",
     "window": "2017-08-24~2026-08-31 (约9年)",
     "cls": "LowVol", "mod": "backtest.strategies.low_vol",
     "kwargs": {"window": 60, "top_n": 3}},
    {"id": "S11", "name": "布林带均值回归",     "category": "均值回归", "category_cn": "均值回归",
     "assets": ["510300", "511880"], "desc": "20日均线±2σ布林带，近下轨加仓/近上轨减仓，动态仓位。",
     "window": "2013-04-18~2026-08-31 (约13年)",
     "cls": "Bollinger", "mod": "backtest.strategies.bollinger",
     "kwargs": {"etf": "510300", "cash": "511880", "ma_period": 20, "sigma": 2.0}},
    {"id": "S12", "name": "量价情绪多因子",     "category": "多因子",   "category_cn": "多因子 / 情绪",
     "assets": ["513100", "159915", "510180", "518880"], "desc": "动量(30%)+量价情绪(25%)+低波(20%)+量价关系(25%)，放量下跌避险。",
     "window": "待回测",
     "cls": "SentimentMomentum", "mod": "backtest.strategies.sentiment_momentum",
     "kwargs": {"lookback": 20, "top_n": 1}},
    {"id": "S13", "name": "多因子综合打分",     "category": "多因子",   "category_cn": "多因子",
     "assets": ["512010", "512880", "512800", "512660", "510300"], "desc": "动量(40%)+低波(25%)+趋势质量(20%)+成交量(15%)，选Top-3。",
     "window": "待回测",
     "cls": "MultiFactor", "mod": "backtest.strategies.multi_factor",
     "kwargs": {"lookback": 60, "top_n": 3}},
    {"id": "S14", "name": "动态波动率调整动量", "category": "动量",     "category_cn": "动量 / 自适应",
     "assets": ["513100", "159915", "510180", "518880"], "desc": "波动率环境自适应回看期(15~120日)，高波短看/低波长看，选Top-2。",
     "window": "待回测",
     "cls": "AdaptiveMomentum", "mod": "backtest.strategies.adaptive_momentum",
     "kwargs": {"lb_min": 15, "lb_max": 120, "top_n": 2}},
    {"id": "S15", "name": "趋势过滤动量增强",   "category": "动量",     "category_cn": "动量 / 趋势过滤",
     "assets": ["513100", "159915", "510180", "518880", "510300", "512480"], "desc": "双过滤：200日MA之上+20日斜率为正→才进入25日动量打分，选Top-2。",
     "window": "待回测",
     "cls": "TrendFilterMomentum", "mod": "backtest.strategies.rsrs_momentum",
     "kwargs": {"ma_long": 200, "ma_short": 20, "top_n": 2}},
    {"id": "S16", "name": "金丝雀防御动量",     "category": "动量",     "category_cn": "动量 / 风险预警",
     "assets": ["513100", "159915", "510180", "510300"], "desc": "三层金丝雀预警(债券/波动率/宽度)→渐进仓位(100/70/40/0%)，选Top-2。",
     "window": "待回测",
     "cls": "CanaryDefense", "mod": "backtest.strategies.canary_defense",
     "kwargs": {"mom_lookback": 25, "top_n": 2}},
    {"id": "S17", "name": "金丝雀防御动量(日频)", "category": "动量",     "category_cn": "动量 / 风险预警",
     "assets": ["513100", "159915", "510180", "510300"], "desc": "S16每日调仓版：三层金丝雀预警→渐进仓位(100/70/40/0%)，选Top-2，每日调仓反应更快。",
     "window": "待回测",
     "cls": "CanaryDefenseDaily", "mod": "backtest.strategies.canary_defense",
     "kwargs": {"mom_lookback": 25, "top_n": 2, "rebalance": "daily"}},
    {"id": "S18", "name": "RSRS增强反转动量", "category": "动量",     "category_cn": "动量 / 反转",
     "assets": ["513100", "159915", "510180", "518880", "510300", "512480", "511880"],
     "desc": "RSRS Beta z-score过滤+25d/200d反转动量打分。市场结构弱化时排除，反转因子避免追高。选Top-1，每日调仓。",
     "window": "2019-06-12~2026-08-31 (约7年)",
     "cls": "RsrsReversalMomentum", "mod": "backtest.strategies.rsrs_reversal_momentum",
     "kwargs": {"mom_short": 25, "mom_long": 200, "reversal_scale": 6.0,
               "rsrs_window": 20, "rsrs_zscore_window": 60, "rsrs_zscore_threshold": -2.0,
               "score_range_min": 0.02, "top_n": 1}},
    {"id": "S19", "name": "低相关ETF轮动", "category": "动量",     "category_cn": "动量 / 低相关",
     "assets": ["518880", "513100", "159915", "511260", "510300"],
     "desc": "五类低相关ETF（黄金/纳指/创业板/国债/沪深300）轮动。25日动量打分选Top-1，低相关池=天然风控。周度调仓。",
     "window": "2017-08-24~2026-08-31 (约9年)",
     "cls": "LowCorrelationRotation", "mod": "backtest.strategies.low_correlation_rotation",
     "kwargs": {"lookback": 25, "top_n": 1}},
]

# Benchmark metrics (from the last full backtest run) — initial seed
BENCHMARKS = {
    "S1":  {"ann": 8.19,  "sharpe": 0.30, "dd": -52.97, "calmar": 0.15, "wr": 52.1, "to": 0.0,  "ex": 0.0},
    "S2":  {"ann": 5.60,  "sharpe": 0.39, "dd": -24.58, "calmar": 0.23, "wr": 53.9, "to": 4.8,  "ex": -2.59},
    "S3":  {"ann": 6.99,  "sharpe": 0.35, "dd": -51.17, "calmar": 0.14, "wr": 52.3, "to": 4.1,  "ex": -1.20},
    "S4":  {"ann": 33.62, "sharpe": 1.21, "dd": -28.51, "calmar": 1.18, "wr": 54.5, "to": 29.9, "ex": 25.43},
    "S5":  {"ann": 7.70,  "sharpe": 0.44, "dd": -35.91, "calmar": 0.21, "wr": 54.4, "to": 0.1,  "ex": -0.49},
    "S6":  {"ann": 5.71,  "sharpe": 0.45, "dd": -22.00, "calmar": 0.26, "wr": 54.2, "to": 0.2,  "ex": -2.48},
    "S7":  {"ann": 9.55,  "sharpe": 0.57, "dd": -40.90, "calmar": 0.23, "wr": 53.3, "to": 5.5,  "ex": 1.36},
    "S8":  {"ann": 34.82, "sharpe": 1.27, "dd": -28.51, "calmar": 1.22, "wr": 54.9, "to": 36.2, "ex": 26.63},
    "S9":  {"ann": 2.95,  "sharpe": 0.14, "dd": -46.03, "calmar": 0.06, "wr": 50.5, "to": 9.6,  "ex": -5.24},
    "S10": {"ann": 11.79, "sharpe": 1.39, "dd": -9.68,  "calmar": 1.22, "wr": 55.0, "to": 2.3,  "ex": 3.60},
    "S11": {"ann": 10.78, "sharpe": 0.47, "dd": -43.62, "calmar": 0.25, "wr": 52.0, "to": 24.9, "ex": 2.59},
    "S16": {"ann": None, "sharpe": None, "dd": None, "calmar": None, "wr": None, "to": None, "ex": None},
    "S17": {"ann": None, "sharpe": None, "dd": None, "calmar": None, "wr": None, "to": None, "ex": None},
    "S18": {"ann": 34.75, "sharpe": 1.16, "dd": -25.50, "calmar": 1.36, "wr": 55.0, "to": 38.5, "ex": None},
    "S19": {"ann": 21.84, "sharpe": 0.87, "dd": -32.01, "calmar": 0.68, "wr": 53.5, "to": 30.9, "ex": None},
}


# ═══════════════════════════════════════════════════════════════
# Seed
# ═══════════════════════════════════════════════════════════════

def _update_source_urls():
    """Update strategy_kb.source_url for all strategies (idempotent, always runs)."""
    _SOURCE_URLS = {
        "S1":  "沪深300买入持有策略 — A股市场基准收益参照",
        "S2":  "https://www.optimalmomentum.com/ — Gary Antonacci《Dual Momentum Investing》",
        "S3":  "经典双均线趋势跟踪策略",
        "S4":  "https://papers.ssrn.com/ — 多资产动量轮动（Moskowitz, Ooi & Pedersen 2012, Time Series Momentum）",
        "S5":  "经典等权组合理论（DeMiguel, Garlappi & Uppal 2009）",
        "S6":  "经典60/40股债配置基准",
        "S7":  "目标波动率策略（Target Volatility / Risk Parity）",
        "S8":  "三因子（斜率+乖离+效率）加权动量轮动 — 内部研发",
        "S9":  "行业动量轮动（Jegadeesh & Titman 1993, Returns to Buying Winners）",
        "S10": "低波动异象（Ang, Hodrick, Xing & Zhang 2006, The Cross-Section of Volatility）",
        "S11": "John Bollinger《Bollinger on Bollinger Bands》— 布林带均值回归",
        "S12": "量价情绪多因子 — 聚宽/BigQuant 社区策略转化",
        "S13": "多因子综合打分 — 聚宽/BigQuant 社区策略转化",
        "S14": "动态波动率调整动量 — 内部研发（自适应回看期）",
        "S15": "趋势过滤动量增强 — 聚宽/BigQuant 社区策略转化",
        "S16": "金丝雀防御动量 — 内部研发（三层风险预警）",
        "S17": "S16每日调仓变体 — 内部研发（三层风险预警+日频调仓）",
        "S18": "JoinQuant @hayy — RSRS Beta增强反转动量轮动 (post/23696793, 398克隆, 8年回测年化35.29%)",
        "S19": "知乎专栏 — 低相关ETF动量轮动 (zhuanlan.zhihu.com/p/24155902542, 实盘验证1年+, Sharpe 2.69)",
    }
    try:
        with get_conn() as conn:
            for sid, url in _SOURCE_URLS.items():
                conn.execute(
                    "UPDATE strategy_kb SET source_url=? WHERE strategy_id=?",
                    (url, sid)
                )
    except Exception:
        pass


def _update_process_descs():
    """Update strategy_kb.process_desc with Chinese execution descriptions."""
    _PROCESS_DESCS = {
        "S1": "1. 加载沪深300ETF（510300）历史价格\n2. 初始资金全仓买入沪深300ETF\n3. 持有不动，不调仓、不止损\n4. 每日净值随沪深300指数波动",
        "S2": "1. 加载股票（510300）、债券（511260）和货币（511880）价格\n2. 计算过去250日绝对动量：股票和债券各自年化收益\n3. 绝对动量过滤：任一资产收益<0则该资产切换至货币\n4. 相对动量比较：在通过过滤的资产中选收益最高者\n5. 满仓持有选中的单一资产，每月末评估一次",
        "S3": "1. 加载沪深300（510300）和货币（511880）价格\n2. 计算MA20和MA60两条均线\n3. MA20上穿MA60→满仓沪深300\n4. MA20下穿MA60→空仓持货币\n5. 月末评估一次，盘中不操作",
        "S4": "1. 加载黄金（518880）、纳指（513100）、创业板（159915）、上证180（510180）价格\n2. 用过去25日log-price做OLS线性回归\n3. 计算年化收益×R²作为动量得分\n4. 选得分最高的1个资产满仓持有\n5. 每日调仓，无防御机制",
        "S5": "1. 加载4个ETF（沪深300/中证500/创业板/债券）价格\n2. 每个资产分配25%固定权重\n3. 每季度末再平衡一次，恢复至目标权重\n4. 再平衡自带逆向Alpha（涨多卖、跌多买）",
        "S6": "1. 加载股票（510300）和债券（511260）价格\n2. 固定配置60%股票+40%债券\n3. 每季度末再平衡一次",
        "S7": "1. 加载沪深300（510300）和货币（511880）价格\n2. 计算过去20日实现波动率\n3. 目标年化波动率15%：实现波动率×仓位=目标波动率\n4. 波动率升高→降低仓位（多持货币）\n5. 波动率降低→增加仓位（多持股票）\n6. 每日调仓，仓位限制在0%~100%",
        "S8": "1. 加载纳指（513100）、创业板（159915）、上证180（510180）、黄金（518880）价格\n2. 计算三因子得分：\n   a) 斜率因子（40%）：25日log-price OLS年化收益×R²\n   b) 乖离因子（30%）：价格偏离均线程度×方向\n   c) 效率因子（30%）：价格路径效率（方向/波动）\n3. 三因子加权求和得综合分\n4. 若最优分<次优分×1.5，维持原仓位（减少冗余切换）\n5. 否则切换至得分最高的1个资产\n6. 每日调仓",
        "S9": "1. 加载5个行业ETF+1个宽基（沪深300）价格\n2. 计算过去60日动量（累计收益）排名\n3. 选Top-3行业ETF等权持有\n4. 月末调仓一次",
        "S10": "1. 加载6个ETF（沪深300/债券/黄金/中证500/创业板/银行）价格\n2. 计算过去60日年化波动率\n3. 按波动率升序排列，选最低的3个\n4. 等权持有选中的3个低波ETF\n5. 月末调仓一次",
        "S11": "1. 加载沪深300（510300）和货币（511880）价格\n2. 计算20日均线和±2σ布林带\n3. 价格接近下轨→加仓（最多100%）\n4. 价格接近上轨→减仓（最少0%）\n5. 仓位=1-(价格-下轨)/(上轨-下轨)\n6. 每日动态调整仓位",
        "S12": "1. 加载纳指/创业板/上证180/黄金价格及成交量\n2. 计算四因子得分：\n   a) 动量因子（30%）：20日年化收益\n   b) 量价情绪因子（25%）：量价配合度+成交量趋势\n   c) 低波动因子（20%）：波动率倒数\n   d) 量价关系因子（25%）：放量下跌→避险信号\n3. 四因子加权得综合分\n4. 放量下跌触发时切换至货币\n5. 选Top-1资产满仓持有\n6. 每日调仓",
        "S13": "1. 加载5个行业ETF+1个宽基价格\n2. 计算四因子得分：\n   a) 动量因子（40%）：60日年化收益\n   b) 低波动因子（25%）：波动率倒数\n   c) 趋势质量因子（20%）：R²+趋势一致性\n   d) 成交量因子（15%）：量价关系\n3. 四因子加权得综合分\n4. 选Top-3资产等权持有\n5. 月末调仓",
        "S14": "1. 加载纳指/创业板/上证180/黄金价格\n2. 计算波动率环境：短波(10日)/长波(60日)比率\n3. 根据波动率比率自适应调整回看期：\n   - 高波动→短回看(15日)\n   - 低波动→长回看(120日)\n   - 中等→线性插值\n4. 用自适应回看期计算动量得分（年化收益×R²）\n5. 选Top-2资产等权持有\n6. 每日调仓",
        "S15": "1. 加载6个ETF（纳指/创业板/上证180/黄金/沪深300/半导体）价格\n2. 双层过滤：\n   a) 200日均线之上（长期趋势向上）\n   b) 20日斜率为正（短期动能向上）\n3. 通过双层过滤的资产进入动量打分池\n4. 25日动量得分排序\n5. 选Top-2资产等权持有\n6. 未通过过滤的资产权重清零\n7. 每日调仓",
        "S16": "1. 加载7个资产价格：4只交易ETF（纳指/创业板/上证180/沪深300）+ 债券(511260,金丝雀监测) + 黄金(518880,备用) + 货币(511880,现金管理)\n2. 三层金丝雀预警：\n   a) 金丝雀1-债券趋势：债券价格是否低于150日均线→债市走弱预警\n   b) 金丝雀2-波动率异常：短期波动率/长期波动率>1.5且超半数ETF触发→市场恐慌预警\n   c) 金丝雀3-动量宽度：正动量ETF占比<40%→广度恶化预警\n3. 根据预警数量确定风险预算：\n   - 0个预警→风险预算100%（进攻）\n   - 1个预警→风险预算70%（警戒）\n   - 2个预警→风险预算40%（防御）\n   - 3个预警→风险预算0%（避险全仓货币）\n4. 动量打分选股（25日log-price OLS回归 → 年化收益×R² 排名）\n5. 选Top-2×风险预算分配仓位（如风险预算100%,Top-2各50%）\n6. 剩余仓位→货币（511880）\n7. 月末调仓（降低交易成本）",
        "S17": "1. 加载7个资产价格：4只交易ETF（纳指/创业板/上证180/沪深300）+ 债券(511260,金丝雀监测) + 黄金(518880,备用) + 货币(511880,现金管理)\n2. 三层金丝雀预警：\n   a) 金丝雀1-债券趋势：债券价格是否低于150日均线→债市走弱预警\n   b) 金丝雀2-波动率异常：短期波动率/长期波动率>1.5且超半数ETF触发→市场恐慌预警\n   c) 金丝雀3-动量宽度：正动量ETF占比<40%→广度恶化预警\n3. 根据预警数量确定风险预算：\n   - 0个预警→风险预算100%（进攻）\n   - 1个预警→风险预算70%（警戒）\n   - 2个预警→风险预算40%（防御）\n   - 3个预警→风险预算0%（避险全仓货币）\n4. 动量打分选股（25日log-price OLS回归 → 年化收益×R² 排名）\n5. 选Top-2×风险预算分配仓位（如风险预算100%,Top-2各50%）\n6. 剩余仓位→货币（511880）\n7. 每日调仓（反应更快但交易成本更高）",
        "S18": "1. 加载7个资产价格：纳指/创业板/上证180/黄金/沪深300/半导体 + 现金(511880)\n2. RSRS过滤：计算每只ETF的RSRS Beta(log(high) vs log(low) OLS斜率)，用60日滚动z-score\n3. 排除z-score < -2.0的ETF（市场结构弱化）\n4. 反转动量打分：\n   a) 25日动量得分 = 年化收益 × R²\n   b) 200日动量得分 = 年化收益 × R²\n   c) 综合得分 = 25日动量 - (200日动量 / 6)\n5. 得分差过滤：最高最低分差 < 0.02则不调仓\n6. 选Top-1得分最高的ETF满仓持有\n7. 无合格标的→全仓现金(511880)\n8. 每日调仓",
        "S19": "1. 加载5个低相关ETF价格：黄金(518880)/纳指(513100)/创业板(159915)/国债(511260)/沪深300(510300)\n2. 25日log-price OLS回归 → 年化收益 × R² 打分\n3. 选Top-1得分最高的ETF满仓持有\n4. 周度调仓（每周最后交易日评估）\n5. 无显式止损——低相关ETF池本身就是天然风控",
    }
    try:
        with get_conn() as conn:
            for sid, desc in _PROCESS_DESCS.items():
                conn.execute(
                    "UPDATE strategy_kb SET process_desc=? WHERE strategy_id=?",
                    (desc, sid)
                )
    except Exception:
        pass


def seed_all():
    """Seed the database with initial strategy metrics + KB from existing sources.

    Metrics and KB seeding are idempotent (INSERT OR REPLACE) — always runs
    on every startup to pick up new strategies without requiring DB reset.
    """
    init_db()

    # ── Seed strategy_metrics (idempotent upsert, always runs) ──
    # IMPORTANT: Only seed strategies that don't already have real backtest
    # data (annual_return IS NOT NULL). This prevents overwriting user-run
    # single-strategy backtest results (e.g. S16, S17) on restart.
    for s in STRATEGY_DEFS:
        existing = metrics_get_one(s["id"])
        if existing and existing.get("annual_return") is not None:
            # Strategy already has real backtest data — preserve it.
            # Only update name/category/assets/description in case they changed.
            metrics_upsert(
                strategy_id=s["id"], name=s["name"], category=s["category"],
                category_cn=s["category_cn"],
                annual_return=existing["annual_return"],
                sharpe=existing.get("sharpe"),
                max_drawdown=existing.get("max_drawdown"),
                calmar=existing.get("calmar"),
                win_rate=existing.get("win_rate"),
                turnover=existing.get("turnover"),
                excess_return=existing.get("excess_return"),
                assets=[f"{c}" for c in s["assets"]],
                description=s["desc"],
                backtest_window=existing.get("backtest_window") or s["window"],
            )
        else:
            bm = BENCHMARKS.get(s["id"], {})
            metrics_upsert(
                strategy_id=s["id"], name=s["name"], category=s["category"],
                category_cn=s["category_cn"],
                annual_return=bm.get("ann"), sharpe=bm.get("sharpe"),
                max_drawdown=bm.get("dd"), calmar=bm.get("calmar"),
                win_rate=bm.get("wr"), turnover=bm.get("to"),
                excess_return=bm.get("ex"),
                assets=[f"{c}" for c in s["assets"]],
                description=s["desc"], backtest_window=s["window"],
            )

    # ── Seed strategy_kb (idempotent upsert, always runs) ──
    try:
        from strategy_kb import KB
        for sid, kb in KB.items():
            kb_upsert(
                strategy_id=sid,
                name=kb.get("name", ""),
                class_name=kb.get("class_name", ""),
                category=kb.get("category", ""),
                intro=kb.get("intro", ""),
                stock_selection=kb.get("stock_selection", ""),
                market_timing=kb.get("market_timing", ""),
                factors=kb.get("factors", ""),
                rebalance=kb.get("rebalance", ""),
                strengths=kb.get("strengths", ""),
                weaknesses=kb.get("weaknesses", ""),
                backtest_params=kb.get("backtest", {}),
                source_url=kb.get("source_url", ""),
            )
        print("[sync] Strategy KB synced from strategy_kb.py")
    except (ImportError, SyntaxError) as e:
        print(f"[sync] WARNING: strategy_kb.py not importable ({type(e).__name__}: {e}), KB not synced")

    if not is_seeded():
        mark_seeded()
        print("[sync] First seed complete — 17 strategies.")
    else:
        print("[sync] Strategy definitions re-synced (idempotent).")

    # Always update source URLs & process descriptions (idempotent, runs every startup)
    # Must run AFTER seeding so the rows exist to be updated
    _update_source_urls()
    _update_process_descs()


# ═══════════════════════════════════════════════════════════════
# K-line Sync (incremental)
# ═══════════════════════════════════════════════════════════════

def sync_kline(code: str, start: str = None, end: str = None,
               progress_callback=None) -> int:
    """Sync K-line for one ETF code. Only fetches new data after last cached date.

    Returns: number of new rows inserted.
    """
    from backtest.data import get_kline

    if start is None:
        last = kline_latest_date(code)
        if last:
            start = (date.fromisoformat(last) + timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            start = "2012-01-01"

    if end is None:
        end = date.today().strftime("%Y-%m-%d")

    if start >= end:
        return 0  # Already up to date

    if progress_callback:
        progress_callback(f"{code}: fetching {start} ~ {end}")

    try:
        df = get_kline(code, start=start, end=end, refresh=True)
    except Exception as e:
        print(f"[sync] K-line fetch failed for {code}: {e}")
        return 0

    if df is None or len(df) == 0:
        print(f"[sync] K-line fetch returned empty for {code} ({start}~{end}), "
              f"API may not have recent data available")
        return 0

    # Build batch rows
    rows = []
    for idx, row in df.iterrows():
        rows.append((
            code,
            idx.strftime("%Y-%m-%d") if hasattr(idx, 'strftime') else str(idx)[:10],
            float(row.get("open", 0) or 0),
            float(row.get("high", 0) or 0),
            float(row.get("low", 0) or 0),
            float(row.get("close", 0) or 0),
            float(row.get("volume", 0) or 0),
        ))

    kline_upsert_batch(rows)
    return len(rows)


def sync_all_klines(progress_callback=None) -> dict:
    """Sync K-lines for all ETF codes. Returns {code: new_rows}."""
    results = {}
    for i, code in enumerate(ALL_ETF_CODES):
        if progress_callback:
            progress_callback(f"[{i+1}/{len(ALL_ETF_CODES)}] {code}")
        try:
            n = sync_kline(code)
            results[code] = n
            if n > 0:
                print(f"[sync] {code}: +{n} rows")
        except Exception as e:
            results[code] = -1
            print(f"[sync] {code}: ERROR {e}")
    return results


# ═══════════════════════════════════════════════════════════════
# Daily Signals Sync
# ═══════════════════════════════════════════════════════════════

_signals_syncing = False
_signals_sync_lock = threading.Lock()


def sync_daily_signals(progress_callback=None) -> dict:
    """Generate today's signals for all strategies and store in DB.

    Phase 1: Collect all unique ETF codes, sync K-line once per code.
    Phase 2: Generate signals for each strategy from DB-cached prices.
    Returns {strategy_id: asset_count}.
    """
    global _signals_syncing
    with _signals_sync_lock:
        if _signals_syncing:
            return {"error": "Signal sync already in progress"}
        _signals_syncing = True

    try:
        from daily_signal import STRAT_MAP, get_etf_name
        from dashboard.db import kline_get_dataframe
        import pandas as pd

        # ── Phase 1: Sync K-line for all unique codes (once per code) ──
        unique_codes = set()
        for _sid, (_sname, strat) in STRAT_MAP.items():
            unique_codes.update(strat.assets)

        if progress_callback:
            progress_callback(f"Syncing K-line for {len(unique_codes)} unique ETFs...")
        for code in sorted(unique_codes):
            try:
                n = sync_kline(code)
                if n > 0:
                    print(f"[sync] {code}: +{n} K-line rows")
            except Exception:
                pass  # Non-fatal; proceed with whatever is in DB

        # ── Phase 2: Generate signals from DB-cached prices ──
        results = {}
        for sid in sorted(STRAT_MAP.keys()):
            if progress_callback:
                progress_callback(f"Signal: {sid}")

            try:
                sname, strat = STRAT_MAP[sid]

                # Load prices from SQLite
                lookback = max(500, getattr(strat, "lookback", 25) + 100)
                end_d = date.today().strftime("%Y-%m-%d")
                start_d = (date.today() - timedelta(days=lookback + 10)).strftime("%Y-%m-%d")

                series = {}
                for code in strat.assets:
                    df = None
                    try:
                        df = kline_get_dataframe(code, start_d, end_d)
                    except Exception:
                        pass

                    if df is not None and len(df) >= 2:
                        series[code] = df["close"]
                    else:
                        # Fall back to API (rare — Phase 1 should have synced everything)
                        from backtest.data import get_kline
                        try:
                            kdf = get_kline(code, start=start_d, end=end_d, refresh=False)
                            if kdf is not None and len(kdf) >= 2:
                                series[code] = kdf["close"]
                        except Exception:
                            pass

                if not series:
                    results[sid] = 0
                    continue

                prices = pd.DataFrame(series).dropna()
                if len(prices) < 2:
                    results[sid] = 0
                    continue

                # Use live=True for strategies that support it (skips monthly/weekly resample)
                try:
                    weights = strat.generate(prices, live=True)
                except TypeError:
                    weights = strat.generate(prices)
                today_w = weights.iloc[-1]
                prev_w = weights.iloc[-2] if len(weights) > 1 else today_w * 0
                # signal_date = 最新收盘价日期的明天（信号执行日）
                data_date = weights.index[-1].date()
                signal_date = (data_date + timedelta(days=1)).strftime("%Y-%m-%d")

                # Preload names
                for etf in strat.assets:
                    try:
                        get_etf_name(etf)
                    except Exception:
                        pass

                # Batch insert: delete old + insert new in one transaction
                # BUG-FIX(2026-09-07)：云模式走云 signals_upsert/signals_delete_by_strategy
                # （本地无 daily_signals 表，直写会 500 / 绕过云，违背云权威原则）。
                from dashboard.db import USE_CLOUD, signals_delete_by_strategy
                signals_delete_by_strategy(sid)
                for etf in strat.assets:
                    tw = float(today_w.get(etf, 0.0))
                    pw = float(prev_w.get(etf, 0.0))
                    diff = tw - pw
                    if diff > 0.001:
                        action = "BUY"
                    elif diff < -0.001:
                        action = "SELL"
                    else:
                        action = "HOLD"
                    signals_upsert(sid, signal_date, etf, get_etf_name(etf),
                                   tw, pw, action)
                if USE_CLOUD:
                    cnt_rows = _cd_select("daily_signals",
                                          columns="id",
                                          filters=[("strategy_id", "eq", sid),
                                                   ("signal_date", "eq", signal_date)])
                    count = len(cnt_rows)
                else:
                    with get_conn() as conn:
                        count = conn.execute(
                            "SELECT COUNT(*) FROM daily_signals WHERE strategy_id=? AND signal_date=?",
                            (sid, signal_date)
                        ).fetchone()[0]

                results[sid] = count
            except Exception as e:
                print(f"[sync] Signal generation failed for {sid}: {e}")
                results[sid] = -1

        # Cleanup old signal data
        signals_delete_old(30)
        return results
    finally:
        with _signals_sync_lock:
            _signals_syncing = False


# ═══════════════════════════════════════════════════════════════
# Backtest NAV Sync
# ═══════════════════════════════════════════════════════════════

def sync_backtest_nav(progress_callback=None) -> dict:
    """Run full backtest for all strategies and cache NAV data in DB.

    Returns {strategy_name: nav_points_count}.
    """
    import importlib
    import pandas as pd
    import numpy as np
    from backtest.data import get_kline
    from backtest.engine import backtest as run_bt

    START = "2012-05-28"
    END = date.today().strftime("%Y-%m-%d")
    results = {}

    for idx, s in enumerate(STRATEGY_DEFS):
        name = f"{s['id']}_{s['name']}"
        if progress_callback:
            progress_callback(f"Backtest [{idx+1}/{len(STRATEGY_DEFS)}]: {name}")

        try:
            mod = importlib.import_module(s["mod"])
            StratClass = getattr(mod, s["cls"])
            strat = StratClass(**s["kwargs"])

            # Load prices for this strategy's assets
            series = {}
            for code in strat.assets:
                df = get_kline(code, start=START, end=END, refresh=False)
                if df is None or len(df) == 0:
                    continue
                series[code] = df["close"]
            prices = pd.DataFrame(series).dropna()

            w = strat.generate(prices)
            res = run_bt(prices, w)

            # Weekly sampling (every ~5 trading days)
            weekly_nav = res.nav.iloc[::5]
            weekly_dd = res.nav / res.nav.cummax() - 1
            weekly_dd = weekly_dd.iloc[::5]

            # Build batch for upsert
            rows = []
            for i in range(len(weekly_nav)):
                d = str(weekly_nav.index[i].date())
                nv = float(weekly_nav.iloc[i])
                dd = float(weekly_dd.iloc[i]) if i < len(weekly_dd) else 0.0
                rows.append((name, d, nv, dd))

            # Atomically DELETE old + INSERT new (single transaction, no data loss gap)
            with get_conn() as conn:
                conn.execute("DELETE FROM backtest_nav WHERE strategy_name=?", (name,))
                conn.executemany("""
                    INSERT OR REPLACE INTO backtest_nav (strategy_name, date, nav, drawdown)
                    VALUES (?, ?, ?, ?)
                """, rows)

            results[name] = len(rows)
            print(f"[sync] {name}: {len(rows)} NAV points")
        except Exception as e:
            print(f"[sync] Backtest failed for {s['id']}: {e}")
            traceback.print_exc()
            results[name] = -1

    return results
