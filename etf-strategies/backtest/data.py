"""数据层：东财前复权日K — 始终走 API 保证数据最新，同时写 parquet 备份。"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
from pathlib import Path
from backtest.em_client import eastmoney_kline

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"


def get_kline(code, start="2012-05-28", end="2026-07-01", refresh=False):
    """取前复权日K。始终走东财 API 保证数据新鲜度；
    API 失败时回退读本地 parquet 缓存作为兜底。
    拉取成功后会写 parquet 更新本地备份。
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{code}.parquet"

    # ── 始终走 API ──
    try:
        rows = eastmoney_kline(code, start=start.replace("-", ""),
                               end=end.replace("-", ""))
    except Exception as api_err:
        # API 失败 → 回退读缓存
        if cache_file.exists():
            df = pd.read_parquet(cache_file)
            return df.loc[(df.index >= pd.Timestamp(start))
                          & (df.index <= pd.Timestamp(end))]
        raise RuntimeError(
            f"东财API请求失败且无本地缓存 code={code}: {api_err}")

    if not rows:
        # 空数据 → 回退读缓存
        if cache_file.exists():
            df = pd.read_parquet(cache_file)
            return df.loc[(df.index >= pd.Timestamp(start))
                          & (df.index <= pd.Timestamp(end))]
        raise RuntimeError(
            f"东财返回空数据 code={code}（可能被风控，请换网络或稍后重试）")

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    for c in ["open", "close", "high", "low", "vol", "amount", "amp"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.loc[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]

    # 写 parquet 备份 — 与已有缓存合并，防止增量拉取覆盖全量历史
    try:
        if cache_file.exists():
            existing = pd.read_parquet(cache_file)
            # Merge: new data wins on duplicate dates, old data preserved
            df = pd.concat([existing, df])
            df = df[~df.index.duplicated(keep="last")].sort_index()
        df.to_parquet(cache_file)
    except Exception:
        pass

    return df


def load_prices(codes, start, end, refresh=False):
    """取多标的收盘价，按公共首末日对齐（dropna 任何含 NaN 的行）。"""
    series = {}
    for c in codes:
        df = get_kline(c, start=start, end=end, refresh=refresh)
        series[c] = df["close"]
    prices = pd.DataFrame(series).dropna()
    return prices
