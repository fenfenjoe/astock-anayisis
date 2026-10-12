"""数据层：多源容错日K — 东财主源 + 腾讯兜底 + parquet 备份（REQ-004）。

原单源东财 push2his 对部分 IP 间歇风控（HTTP 000/空/RemoteDisconnected），
现升级为：东财(em_get限流) → 腾讯(ifzq fqkline) → 本地 parquet → 报错。
切换不静默（WARN 日志），复用 MultiSourceQuote 健康探测/自动切换。
"""
import sys
import logging
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from datetime import date
import pandas as pd
from pathlib import Path
from backtest.em_client import eastmoney_kline
from backtest import tencent_client

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"


def get_kline(code, start="2012-05-28", end=None, refresh=False):
    """取前复权日K（多源容错）。

    refresh=True:  东财 API → 失败切腾讯 → 再失败读缓存；写 parquet 备份。
    refresh=False: 优先读本地 parquet 缓存；缓存覆盖请求范围时零 API 调用。
                   缓存不足或不存在时才走 API（同样多源容错）。
    返回值始终过滤到 [start, end] 范围。
    end 缺省时动态取当前日期。
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{code}.parquet"

    if end is None:
        end = date.today().strftime("%Y-%m-%d")

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)

    # ── refresh=False + 缓存已覆盖请求范围 → 直接读缓存，零 API 调用 ──
    if not refresh and cache_file.exists():
        try:
            existing = pd.read_parquet(cache_file)
            if len(existing) >= 2:
                existing.index.name = "date"
                cache_start = existing.index.min()
                cache_end = existing.index.max()
                if cache_start <= start_ts and cache_end >= end_ts:
                    return existing.loc[(existing.index >= start_ts)
                                        & (existing.index <= end_ts)]
        except Exception:
            pass  # 缓存读取失败 → 继续走 API

    # ── 走 API（东财 → 腾讯 多源容错）──
    df = _fetch_multisource(code, start, end)
    if df is None:
        # 全部源失败 → 回退读缓存
        if cache_file.exists():
            cached = pd.read_parquet(cache_file)
            cached.index.name = "date"
            return cached.loc[(cached.index >= start_ts) & (cached.index <= end_ts)]
        raise RuntimeError(
            f"所有行情源均不可用且无本地缓存 code={code}（东财/腾讯均失败）")

    # ── 写 parquet 备份 — 与已有缓存合并，防止增量拉取覆盖全量历史 ──
    try:
        if cache_file.exists():
            existing = pd.read_parquet(cache_file)
            # Merge: new data wins on duplicate dates, old data preserved
            df = pd.concat([existing, df])
            df = df[~df.index.duplicated(keep="last")].sort_index()
        # pd.concat 后 index.name 可能被旧缓存(None)冲掉，统一恢复
        df.index.name = "date"
        df.to_parquet(cache_file)
    except Exception:
        pass

    # ── 过滤到请求范围后返回（合并后 df 可能包含全量历史，必须重新裁剪）──
    return df.loc[(df.index >= start_ts) & (df.index <= end_ts)]


def _fetch_multisource(code, start, end):
    """东财 → 腾讯 → None（全失败）。成功返回 DataFrame（未过滤范围）。"""
    # ── 1. 东财主源 ──
    try:
        rows = eastmoney_kline(code, start=start.replace("-", ""),
                               end=end.replace("-", ""))
        if rows:
            df = _rows_to_df(rows)
            logger.debug("[data] %s 东财主源 OK", code)
            return df
        logger.warning("[data] %s 东财返回空数据 → 切腾讯", code)
    except Exception as api_err:
        logger.warning("[data] %s 东财失败(%s) → 切腾讯", code, api_err)

    # ── 2. 腾讯备源 ──
    try:
        df = tencent_client.tencent_daily_kline(code, start=start, end=end)
        if len(df) > 0:
            logger.warning("[data] %s 已切换腾讯日K（东财不可用）", code)
            # 腾讯字段与东财对齐：确保列名统一（补 amount/amp 空列）
            df = df.copy()
            df.index.name = "date"
            for c in ["open", "close", "high", "low", "vol"]:
                if c not in df.columns:
                    df[c] = 0.0
            for c in ["amount", "amp"]:
                if c not in df.columns:
                    df[c] = float("nan")
            return df
        logger.warning("[data] %s 腾讯日K为空", code)
    except Exception as tencent_err:
        logger.warning("[data] %s 腾讯失败(%s)", code, tencent_err)

    return None


def _rows_to_df(rows):
    """东财 rows(list[dict]) → DataFrame（与旧 get_kline 解析一致）。"""
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    for c in ["open", "close", "high", "low", "vol", "amount", "amp"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df.index.name = "date"
    return df


def load_prices(codes, start, end, refresh=False):
    """取多标的收盘价，按公共首末日对齐（dropna 任何含 NaN 的行）。"""
    series = {}
    for c in codes:
        df = get_kline(c, start=start, end=end, refresh=refresh)
        series[c] = df["close"]
    prices = pd.DataFrame(series).dropna()
    return prices
