"""东财统一限流客户端 — 复用 a-stock-data SKILL.md 的 em_get helper。
所有东财请求走 em_get()：串行限流 + 会话复用 + 退避重试，防封 IP。"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import time, random, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
try:
    _adapter = HTTPAdapter(max_retries=Retry(
        total=3, connect=3, backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"]))
    EM_SESSION.mount("https://", _adapter)
    EM_SESSION.mount("http://", _adapter)
except Exception:
    pass

EM_MIN_INTERVAL = 1.0
_em_last_call = [0.0]


def em_get(url, params=None, headers=None, timeout=15, **kwargs):
    """东财统一请求入口：自动节流 + 复用 session + 默认 UA。"""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()


def eastmoney_kline(code, start="20120101", end="20261231"):
    """东财前复权日K。code: 6位ETF代码。返回 list[dict]:
    date/open/close/high/low/vol/amount/amp。"""
    secid = f"1.{code}" if code.startswith(("5", "6")) else f"0.{code}"
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid, "klt": "101", "fqt": "1",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "beg": start, "end": end,
    }
    r = em_get(url, params=params,
               headers={"Referer": "https://quote.eastmoney.com/"}, timeout=15)
    d = r.json()
    klines = (d.get("data") or {}).get("klines") or []
    rows = []
    for line in klines:
        p = line.split(",")
        if len(p) >= 7:
            rows.append({
                "date": p[0], "open": float(p[1]), "close": float(p[2]),
                "high": float(p[3]), "low": float(p[4]),
                "vol": float(p[5]), "amount": float(p[6]),
                "amp": float(p[7]) if len(p) > 7 and p[7] else 0.0,
            })
    return rows
