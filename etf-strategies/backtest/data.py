"""数据层：东财前复权日K + parquet 本地缓存。"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
from pathlib import Path
from backtest.em_client import eastmoney_kline

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"


def get_kline(code, start="2012-05-28", end="2026-07-01", refresh=False):
    """取前复权日K。命中缓存则读 parquet，否则走东财并写缓存。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{code}.parquet"
    if cache_file.exists() and not refresh:
        df = pd.read_parquet(cache_file)
        return df.loc[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
    rows = eastmoney_kline(code, start=start.replace("-", ""),
                           end=end.replace("-", ""))
    if not rows:
        raise RuntimeError(
            f"东财返回空数据 code={code}（可能被风控，请换网络或稍后重试）")
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    for c in ["open", "close", "high", "low", "vol", "amount", "amp"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.loc[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
    df.to_parquet(cache_file)
    return df


def load_prices(codes, start, end, refresh=False):
    """取多标的收盘价，按公共首末日对齐（dropna 任何含 NaN 的行）。"""
    series = {}
    for c in codes:
        df = get_kline(c, start=start, end=end, refresh=refresh)
        series[c] = df["close"]
    prices = pd.DataFrame(series).dropna()
    return prices
