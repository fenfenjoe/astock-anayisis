"""数据层：东财前复权日K — 始终走 API 保证数据最新，同时写 parquet 备份。"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
from pathlib import Path
from backtest.em_client import eastmoney_kline

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"


def get_kline(code, start="2012-05-28", end="2026-07-01", refresh=False):
    """取前复权日K。

    refresh=True:  始终走东财 API 保证最新，写 parquet 备份。
    refresh=False: 优先读本地 parquet 缓存；缓存覆盖请求范围时零 API 调用。
                   缓存不足或不存在时才走 API。

    拉取成功后会写 parquet 更新本地备份。
    返回值始终过滤到 [start, end] 范围。
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{code}.parquet"

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)

    # ── refresh=False + 缓存已覆盖请求范围 → 直接读缓存，零 API 调用 ──
    if not refresh and cache_file.exists():
        try:
            existing = pd.read_parquet(cache_file)
            if len(existing) >= 2:
                cache_start = existing.index.min()
                cache_end = existing.index.max()
                if cache_start <= start_ts and cache_end >= end_ts:
                    return existing.loc[(existing.index >= start_ts)
                                        & (existing.index <= end_ts)]
        except Exception:
            pass  # 缓存读取失败 → 继续走 API

    # ── 走 API ──
    try:
        rows = eastmoney_kline(code, start=start.replace("-", ""),
                               end=end.replace("-", ""))
    except Exception as api_err:
        # API 失败 → 回退读缓存
        if cache_file.exists():
            df = pd.read_parquet(cache_file)
            return df.loc[(df.index >= start_ts) & (df.index <= end_ts)]
        raise RuntimeError(
            f"东财API请求失败且无本地缓存 code={code}: {api_err}")

    if not rows:
        # 空数据 → 回退读缓存
        if cache_file.exists():
            df = pd.read_parquet(cache_file)
            return df.loc[(df.index >= start_ts) & (df.index <= end_ts)]
        raise RuntimeError(
            f"东财返回空数据 code={code}（可能被风控，请换网络或稍后重试）")

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    # DAT-001: 无重复索引（东财 API 异常时可能返回重复日期，去重保留最新）
    df = df[~df.index.duplicated(keep="last")]
    for c in ["open", "close", "high", "low", "vol", "amount", "amp"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

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

    # ── 过滤到请求范围后返回（合并后 df 可能包含全量历史，必须重新裁剪）──
    return df.loc[(df.index >= start_ts) & (df.index <= end_ts)]


def load_prices(codes, start, end, refresh=False):
    """取多标的收盘价，按公共首末日对齐（dropna 任何含 NaN 的行）。"""
    series = {}
    for c in codes:
        df = get_kline(c, start=start, end=end, refresh=refresh)
        series[c] = df["close"]
    prices = pd.DataFrame(series).dropna()
    return prices
