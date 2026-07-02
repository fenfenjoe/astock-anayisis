"""每日信号：给出指定策略当天的具体操作（买入/卖出/持有）。

用法:
  python daily_signal.py              # 列出所有可用策略
  python daily_signal.py S4           # 查看 S4 今天的信号
  python daily_signal.py S8           # 查看 S8 今天的信号
  python daily_signal.py --all        # 查看所有策略的今日信号
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import argparse
import json
from datetime import date, timedelta
from pathlib import Path
import pandas as pd
import numpy as np

from backtest.data import get_kline
from backtest.em_client import em_get
from backtest.strategies.buy_hold import BuyHold
from backtest.strategies.dual_momentum import DualMomentum
from backtest.strategies.ma_trend import MATrend
from backtest.strategies.momentum_rotation import MomentumRotation
from backtest.strategies.equal_weight import EqualWeight
from backtest.strategies.portfolio_6040 import Portfolio6040
from backtest.strategies.target_vol import TargetVol
from backtest.strategies.three_factor_momentum import ThreeFactorMomentum
from backtest.strategies.industry_momentum import IndustryMomentum
from backtest.strategies.low_vol import LowVol
from backtest.strategies.bollinger import Bollinger
from backtest.strategies.sentiment_momentum import SentimentMomentum
from backtest.strategies.multi_factor import MultiFactor

# ── 策略注册表 ──
STRAT_MAP = {
    "S1": ("买入持有",           BuyHold("510300")),
    "S2": ("双动量",              DualMomentum(lookback=250)),
    "S3": ("均线趋势",            MATrend(short=20, long=60)),
    "S4": ("多资产动量轮动",       MomentumRotation(lookback=25, top_n=1)),
    "S5": ("等权组合",            EqualWeight()),
    "S6": ("60-40股债平衡",       Portfolio6040()),
    "S7": ("目标波动率",          TargetVol(target_vol=0.15, window=20)),
    "S8": ("三因子动量轮动",       ThreeFactorMomentum(lookback=25, top_n=1, threshold=1.5)),
    "S9": ("行业动量轮动",         IndustryMomentum(lookback=60, top_n=3)),
    "S10": ("低波动因子",          LowVol(window=60, top_n=3)),
    "S11": ("布林带均值回归",       Bollinger(etf="510300", cash="511880", ma_period=20, sigma=2.0)),
    "S12": ("量价情绪多因子",       SentimentMomentum(lookback=20, top_n=1)),
    "S13": ("多因子综合打分",       MultiFactor(lookback=60, top_n=3)),
}

# ── ETF 名称映射（静态 + API 缓存） ──
ETF_NAMES = {
    # 宽基
    "510300": "沪深300ETF",
    "510500": "中证500ETF",
    "510180": "上证180ETF",
    "159915": "创业板ETF",
    "588000": "科创50ETF",
    # 债券/货币
    "511260": "国债ETF",
    "511880": "银华日利(货币)",
    "511010": "国债ETF(511010)",
    # 商品/海外
    "518880": "黄金ETF",
    "513100": "纳指100ETF",
    "159949": "创50ETF",
    # 行业
    "512010": "医药ETF",
    "512880": "证券ETF",
    "512800": "银行ETF",
    "512660": "军工ETF",
    "512480": "半导体ETF",
    "512690": "酒ETF",
    "512400": "有色ETF",
    "512720": "计算机ETF",
    "515790": "光伏ETF",
    "515030": "新能源车ETF",
    "512100": "中证1000ETF",
}

# 本地缓存文件，持久化 API 查到的名称
NAME_CACHE_FILE = Path(__file__).resolve().parent / "cache" / "etf_names.json"


def _load_name_cache():
    """加载本地持久化的名称缓存。"""
    if NAME_CACHE_FILE.exists():
        try:
            return json.loads(NAME_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_name_cache(cache):
    """保存名称缓存到本地。"""
    NAME_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    NAME_CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2),
                               encoding="utf-8")


def _fetch_name_from_api(code):
    """通过东财 push2 API 获取ETF名称（secid格式：1.5xxxxx / 0.1xxxxx）。"""
    secid = f"1.{code}" if code.startswith(("5", "6")) else f"0.{code}"
    try:
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "secid": secid,
            "fields": "f57,f58",
        }
        r = em_get(url, params=params,
                   headers={"Referer": "https://quote.eastmoney.com/"}, timeout=10)
        data = r.json().get("data", {})
        name = data.get("f58", "")
        if name:
            return name
    except Exception:
        pass
    return ""


def get_etf_name(code):
    """查ETF名称：静态表 → 本地缓存 → API查询 → 返回代码本身。"""
    # 1) 静态映射
    if code in ETF_NAMES:
        return ETF_NAMES[code]

    # 2) 本地持久化缓存
    cache = _load_name_cache()
    if code in cache:
        ETF_NAMES[code] = cache[code]  # 回填到内存
        return cache[code]

    # 3) API 查询
    name = _fetch_name_from_api(code)
    if name:
        ETF_NAMES[code] = name
        cache[code] = name
        _save_name_cache(cache)
        return name

    # 4) 兜底
    return code


def load_prices(assets, lookback_days=300):
    """拉取最近 N 个自然日的价格数据（自动对齐交易日）。"""
    end = date.today().strftime("%Y-%m-%d")
    start = (date.today() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    series = {}
    for code in assets:
        try:
            df = get_kline(code, start=start, end=end, refresh=False)
            series[code] = df["close"]
        except Exception as e:
            print(f"  ⚠️ 获取 {code} 数据失败: {e}")
    if not series:
        raise RuntimeError("无法获取任何资产数据，请检查网络")
    prices = pd.DataFrame(series).dropna()
    if len(prices) < 2:
        raise RuntimeError(f"数据不足（仅 {len(prices)} 个交易日），无法生成信号")
    return prices


def generate_signal(strat_id, strat_name, strat):
    """生成策略今日信号并打印。"""
    # 预加载所有ETF名称
    for etf in strat.assets:
        get_etf_name(etf)

    print(f"\n{'='*70}")
    print(f"  {strat_id} {strat_name}")
    print(f"  资产池: {', '.join(f'{c}({get_etf_name(c)})' for c in strat.assets)}")
    print(f"{'='*70}")

    # 拉数据：需要足够长的回看窗口（max 300天覆盖所有策略的 lookback）
    lookback = max(300, getattr(strat, 'lookback', 25) + 50)
    prices = load_prices(strat.assets, lookback_days=lookback)
    print(f"  数据窗口: {prices.index[0].date()} ~ {prices.index[-1].date()} "
          f"({len(prices)} 个交易日)")

    # 生成目标权重
    weights = strat.generate(prices)

    # 最新一期的目标权重 = 最后一行
    today_weights = weights.iloc[-1]
    # 上一期 = 倒数第二行
    prev_weights = weights.iloc[-2] if len(weights) > 1 else pd.Series(0.0, index=today_weights.index)

    # 判断买卖方向
    print(f"\n  📅 信号日期: {weights.index[-1].date()}")
    print(f"  {'代码':<8s} {'名称':<14s} {'目标权重':>8s} {'上期权重':>8s} {'变动':>8s}  操作")
    print(f"  {'-'*62}")

    actions = []
    for etf in strat.assets:
        tw = today_weights.get(etf, 0.0)
        pw = prev_weights.get(etf, 0.0)
        diff = tw - pw
        name = get_etf_name(etf)

        if diff > 0.001:
            action = "🟢 买入"
            actions.append((etf, name, "BUY", diff))
        elif diff < -0.001:
            action = "🔴 卖出"
            actions.append((etf, name, "SELL", -diff))
        else:
            action = "⚪ 持有"

        print(f"  {etf:<8s} {name:<14s} {tw:>7.1%}   {pw:>7.1%}   {diff:>+7.1%}   {action}")

    # 一句话总结
    if not actions:
        print(f"\n  ✅ 今日无需操作，维持现有持仓。")
    else:
        print(f"\n  📋 今日需操作:")
        for etf, name, act, pct in actions:
            print(f"     {act} {etf} {name}: 仓位变动 {pct:.1%}")

    # 当前持仓概览
    print(f"\n  💼 建议持仓:")
    held = [(etf, get_etf_name(etf), w) for etf, w in today_weights.items() if w > 0.001]
    if held:
        for etf, name, w in sorted(held, key=lambda x: -x[2]):
            print(f"     {etf} {name}: {w:.1%}")
    else:
        print(f"     (空仓/货币)")


def main():
    parser = argparse.ArgumentParser(description="ETF策略每日信号")
    parser.add_argument("strategy", nargs="?", default=None,
                        help="策略编号 (S1-S11) 或 '--all'")
    parser.add_argument("--all", action="store_true", default=False,
                        help="显示所有策略信号")
    args = parser.parse_args()

    if args.strategy is None and not args.all:
        print("可用策略:")
        print("-" * 50)
        for sid, (sname, _) in STRAT_MAP.items():
            print(f"  {sid}: {sname}")
        print("\n用法: python daily_signal.py S4       # 查看 S4 今日信号")
        print("      python daily_signal.py --all     # 查看所有策略信号")
        return

    if args.all or args.strategy == "--all":
        for sid, (sname, strat) in STRAT_MAP.items():
            try:
                generate_signal(sid, sname, strat)
            except Exception as e:
                print(f"\n  ❌ {sid} 信号生成失败: {e}")
    else:
        sid = args.strategy.upper()
        if sid not in STRAT_MAP:
            print(f"❌ 未知策略: {args.strategy}")
            print(f"   可用: {', '.join(STRAT_MAP.keys())}")
            return
        sname, strat = STRAT_MAP[sid]
        try:
            generate_signal(sid, sname, strat)
        except Exception as e:
            print(f"\n❌ 信号生成失败: {e}")
            print("  请检查网络连接（需访问东财 push2his API）")


if __name__ == "__main__":
    main()
