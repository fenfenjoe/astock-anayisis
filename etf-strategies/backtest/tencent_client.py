"""腾讯财经客户端 — 免费实时行情（不封IP，海外可直连）。

数据来源：
- 实时报价：qt.gtimg.cn（GBK，`~` 分隔 88 字段，批量）
- 日K（前复权）：ifzq.gtimg.cn/appstock/app/fqkline/get（qfqday）
- 分钟K：ifzq.gtimg.cn/appstock/app/kline/mkline（m1/m5/m15/m30/m60）

REQ-004：作为 get_kline() 多源容错的「腾讯主源/备源」。
实现复用 a-stock-data skill 的 tencent_quote() 与实测端点格式。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import json
import urllib.request
from datetime import date
import pandas as pd

# 沪市指数代码（以"0"开头但不是深市股票，需要明确映射到 sh 前缀）
_SH_INDEX_CODES = {
    "000001", "000002", "000003", "000008", "000009", "000010",
    "000016", "000300", "000688", "000852", "000905", "000922",
}

_MINUTE_FREQS = {"m1", "m5", "m15", "m30", "m60"}

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_REFERER = "https://gu.qq.com/"


def _http_get_json(url: str, timeout: int = 10):
    """GET JSON（腾讯 ifzq 接口）。"""
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Referer": _REFERER})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _http_get_bytes(url: str, timeout: int = 10) -> bytes:
    """GET 原始字节（qt.gtimg.cn GBK 报价）。"""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _to_prefixed(codes: list[str]) -> list[str]:
    """6位代码 → sh/sz/bj 前缀（供 qt.gtimg.cn / ifzq 使用）。"""
    prefixed = []
    for c in codes:
        c = c.lower()
        if c.startswith(("sh", "sz", "bj")):
            prefixed.append(c)
        elif c in _SH_INDEX_CODES:
            prefixed.append(f"sh{c}")
        elif c.startswith(("5", "6", "9")):
            prefixed.append(f"sh{c}")
        elif c.startswith(("4", "8")):
            prefixed.append(f"bj{c}")
        else:
            prefixed.append(f"sz{c}")
    return prefixed


def tencent_quote(codes: list[str]) -> dict[str, dict]:
    """批量实时报价。codes: 6位代码（支持指数 sh000001/沪深300 等）。

    返回: {code: {name, price, last_close, open, high, low, change_amt,
                  change_pct, amount_wan, turnover_pct, pe_ttm, amplitude_pct,
                  mcap_yi, float_mcap_yi, pb, limit_up, limit_down, vol_ratio,
                  pe_static}}
    """
    url = "https://qt.gtimg.cn/q=" + ",".join(_to_prefixed(codes))
    data = _http_get_bytes(url).decode("gbk", errors="replace")
    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]
        result[code] = {
            "name":         vals[1],
            "price":        float(vals[3]) if vals[3] else 0.0,
            "last_close":   float(vals[4]) if vals[4] else 0.0,
            "open":         float(vals[5]) if vals[5] else 0.0,
            "change_amt":   float(vals[31]) if vals[31] else 0.0,
            "change_pct":   float(vals[32]) if vals[32] else 0.0,
            "high":         float(vals[33]) if vals[33] else 0.0,
            "low":          float(vals[34]) if vals[34] else 0.0,
            "amount_wan":   float(vals[37]) if vals[37] else 0.0,
            "turnover_pct": float(vals[38]) if vals[38] else 0.0,
            "pe_ttm":       float(vals[39]) if vals[39] else 0.0,
            "amplitude_pct":float(vals[43]) if vals[43] else 0.0,
            "mcap_yi":      float(vals[44]) if vals[44] else 0.0,
            "float_mcap_yi":float(vals[45]) if vals[45] else 0.0,
            "pb":           float(vals[46]) if vals[46] else 0.0,
            "limit_up":     float(vals[47]) if vals[47] else 0.0,
            "limit_down":   float(vals[48]) if vals[48] else 0.0,
            "vol_ratio":    float(vals[49]) if vals[49] else 0.0,
            "pe_static":    float(vals[52]) if vals[52] else 0.0,
        }
    return result


def tencent_daily_kline(code: str, start: str = None, end: str = None,
                        count: int = 320) -> pd.DataFrame:
    """腾讯前复权日K（qfqday）。code: 6位。

    start/end: 'YYYY-MM-DD'；缺省 end=今天。count: 最多返回 bar 数。
    返回: DataFrame(date 索引升序, open/close/high/low/vol)。
    """
    if end is None:
        end = date.today().strftime("%Y-%m-%d")
    prefixed = _to_prefixed([code])[0]
    url = ("https://ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={prefixed},day,{start or ''},{end},{count},qfq")
    d = _http_get_json(url)
    rows = ((d.get("data") or {}).get(prefixed) or {}).get("qfqday") or []
    df = _bars_to_df(rows)
    if len(df) == 0:
        return df
    if start:
        df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]
    return df


def tencent_mkline(code: str, freq: str = "m5", count: int = 320) -> pd.DataFrame:
    """腾讯分钟K线。freq: m1/m5/m15/m30/m60；count: 最多 bar 数（上限~800）。

    返回: DataFrame(datetime 索引, open/close/high/low/vol)。
    """
    if freq not in _MINUTE_FREQS:
        raise ValueError(f"非法分钟频率 freq={freq!r}，可用: {sorted(_MINUTE_FREQS)}")
    prefixed = _to_prefixed([code])[0]
    url = ("https://ifzq.gtimg.cn/appstock/app/kline/mkline"
           f"?param={prefixed},{freq},,{count}")
    d = _http_get_json(url)
    rows = ((d.get("data") or {}).get(prefixed) or {}).get(freq) or []
    return _bars_to_df(rows)


def _bars_to_df(rows: list) -> pd.DataFrame:
    """腾讯 K线行 → DataFrame。

    日K行:  [date, open, close, high, low, volume]
    分钟行: [datetime, open, close, high, low, volume, {}, amount]
    注意字段序 open/close/high/low（与东财 open/close/high/low 不同！）。
    """
    records = []
    for line in rows:
        if not line or len(line) < 6:
            continue
        ts = line[0]
        try:
            records.append({
                "date": ts,
                "open": float(line[1]),
                "close": float(line[2]),
                "high": float(line[3]),
                "low": float(line[4]),
                "vol": float(line[5]) if line[5] else 0.0,
            })
        except (ValueError, TypeError):
            continue
    if not records:
        df = pd.DataFrame(columns=["open", "close", "high", "low", "vol"])
        df.index.name = "date"
        return df
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df.index.name = "date"
    return df


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="腾讯财经客户端自检")
    ap.add_argument("--code", default="510300")
    ap.add_argument("--cmd", choices=["quote", "daily", "minute"], default="quote")
    ap.add_argument("--freq", default="m5")
    args = ap.parse_args()
    if args.cmd == "quote":
        print(tencent_quote([args.code]))
    elif args.cmd == "daily":
        print(tencent_daily_kline(args.code))
    else:
        print(tencent_mkline(args.code, freq=args.freq).tail(5))
