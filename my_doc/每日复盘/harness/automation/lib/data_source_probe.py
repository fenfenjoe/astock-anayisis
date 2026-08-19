"""
数据源连通性探测 — 所有自动化 Prompt 的 Step 2.5 引用此脚本。

功能：
  1. 探测所有数据源是否可达（push2 / push2his / 腾讯 / 同花顺 / push2ex / mootdx / datacenter）
  2. 输出 JSON 状态文件供 Prompt 读取
  3. 根据状态给出数据采集路径建议

用法：
  python data_source_probe.py --output probe_status.json
  返回 JSON: { "push2": "ok"|"fail", "push2his": "ok"|"fail", ...,
                "paths": {...}, "timestamp": "..." }
"""

import json
import sys
import time
import argparse
import urllib.request
import socket
from datetime import datetime
from pathlib import Path


def _probe_push2() -> str:
    """东财 push2 连通性探测 — 最常失败的数据源。

    用实际业务端点 clist（行业涨跌排名）而非轻量 ulist 判定：
    东财对 push2 是**端点级风控**——轻量请求（ulist 单标的 1 字段）放行，
    批量分页请求（clist 全行业）被拦。测 ulist 会误报 ok（实测 2026-08-19：
    ulist 可达而 clist 被 RemoteDisconnected 拒绝）。探测参数贴近
    industry_comparison() 业务调用（fs=m:90+t:2, pz=100），确保探测结果
    真实反映行业排名端点可用性。
    """
    try:
        url = (
            "https://push2.eastmoney.com/api/qt/clist/get"
            "?pn=1&pz=100&po=1&np=1&fltt=2&invt=2&fs=m:90+t:2"
            "&fields=f12,f14,f3"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=8)
        data = json.loads(resp.read().decode("utf-8"))
        diff = (data.get("data") or {}).get("diff") or []
        return "ok" if diff else "fail"
    except Exception:
        return "fail"


def _probe_push2his() -> str:
    """东财 push2his（个股/板块资金流）— 独立子域名，与 push2 分开风控。

    push2his.eastmoney.com 与 push2.eastmoney.com 是不同子域名，风控独立：
    push2 可用不代表 push2his 可用（反之亦然），因此单独探测，供
    fund_flow 路径判定使用。
    """
    try:
        url = (
            "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
            "?secid=1.600519&fields1=f1,f2,f3,f7&fields2=f51,f52"
            "&lmt=5"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=8)
        data = json.loads(resp.read().decode("utf-8"))
        klines = (data.get("data") or {}).get("klines") or []
        return "ok" if klines else "fail"
    except Exception:
        return "fail"


def _probe_tencent() -> str:
    """腾讯财经 — 几乎从不失败"""
    try:
        url = "https://qt.gtimg.cn/q=sh000001"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=5)
        text = resp.read().decode("gbk")
        return "ok" if text and '"' in text else "fail"
    except Exception:
        return "fail"


def _probe_ths() -> str:
    """同花顺热点/热榜 — 零鉴权"""
    try:
        import requests
        r = requests.get(
            "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock",
            params={"stock_type": "a", "type": "hour", "list_type": "normal"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        return "ok" if r.status_code == 200 and r.json().get("data") else "fail"
    except Exception:
        return "fail"


def _probe_push2ex() -> str:
    """东财 push2ex（涨停板池）— 与 push2 同域名族"""
    try:
        import requests
        r = requests.get(
            "https://push2ex.eastmoney.com/getTopicZTPool",
            params={"ut": "7eea3edcaed734bea9cbfc24409ed989", "dpt": "wz.ztzt",
                    "Pageindex": 0, "pagesize": 1},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        return "ok" if r.status_code == 200 else "fail"
    except Exception:
        return "fail"


def _probe_mootdx() -> str:
    """mootdx TCP 7709 — 海外网络通常超时"""
    try:
        ip, port = "119.97.185.59", 7709
        sock = socket.create_connection((ip, port), timeout=3)
        sock.close()
        return "ok"
    except Exception:
        return "fail"


def _probe_datacenter() -> str:
    """东财 datacenter-web（龙虎榜/解禁等）— 与 push2 不同子域名"""
    try:
        import requests
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPTA_WEB_RZRQ_GGMX",
            "columns": "ALL", "filter": '(SCODE="600519")',
            "pageNumber": "1", "pageSize": "1",
            "sortColumns": "DATE", "sortTypes": "-1",
            "source": "WEB", "client": "WEB",
        }
        r = requests.get(url, params=params,
                         headers={"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"},
                         timeout=6)
        return "ok" if r.status_code == 200 and r.json().get("result", {}).get("data") else "fail"
    except Exception:
        return "fail"


def get_data_paths(status: dict) -> dict:
    """
    根据探测结果给出数据采集路径建议。
    返回 { data_type: { primary: str, fallback: str, note: str }, ... }
    """
    push2_ok = status.get("push2") == "ok"
    push2his_ok = status.get("push2his") == "ok"
    tencent_ok = status.get("tencent") == "ok"
    ths_ok = status.get("ths") == "ok"
    push2ex_ok = status.get("push2ex") == "ok"
    mootdx_ok = status.get("mootdx") == "ok"
    dc_ok = status.get("datacenter") == "ok"

    paths = {}

    # 1. 行业板块排名
    if push2_ok:
        paths["industry_ranking"] = {
            "primary": "东财 push2 industry_comparison",
            "fallback": "腾讯财经批量行情自算",
            "note": "",
        }
    else:
        paths["industry_ranking"] = {
            "primary": "腾讯财经批量行情自算（push2 不可达）",
            "fallback": "同花顺热点题材频次推断",
            "note": "⚠️ push2 不可达，板块排名基于腾讯批量行情 + 同花顺热点题材频次综合判断",
        }

    # 2. 北向资金
    if push2_ok:
        paths["northbound"] = {
            "primary": "东财 push2 北向数据",
            "fallback": "同花顺 hsgtApi + 本地 CSV 缓存",
            "note": "",
        }
    else:
        paths["northbound"] = {
            "primary": "同花顺 hsgtApi（实时）",
            "fallback": "本地 CSV 缓存（历史数据）",
            "note": "⚠️ push2 不可达，北向资金数据源自同花顺 hsgtApi 或本地缓存",
        }

    # 3. 个股资金流（push2his 独立子域名，独立风控）
    if push2his_ok:
        paths["fund_flow"] = {
            "primary": "东财 push2his 个股资金流（日级120日）",
            "fallback": "mootdx 量价估算 + 腾讯换手率",
            "note": "",
        }
    else:
        paths["fund_flow"] = {
            "primary": "mootdx 量价估算 + 腾讯换手率",
            "fallback": "标记'数据缺失'",
            "note": "⚠️ push2his 不可达，资金流数据基于 mootdx 量价 + 腾讯换手率估算，精度有限",
        }

    # 4. 融资融券
    if dc_ok:
        paths["margin"] = {
            "primary": "东财 datacenter 融资融券",
            "fallback": "标记'数据缺失'",
            "note": "",
        }
    else:
        paths["margin"] = {
            "primary": "标记'数据缺失'",
            "fallback": "上周同期数据参考",
            "note": "⚠️ 东财 datacenter 不可达，融资融券数据缺失",
        }

    # 5. 涨停板池
    if push2ex_ok:
        paths["limit_up"] = {
            "primary": "东财 push2ex 涨停/炸板/跌停池",
            "fallback": "同花顺涨停揭秘",
            "note": "",
        }
    elif ths_ok:
        paths["limit_up"] = {
            "primary": "同花顺涨停揭秘（push2ex 不可达）",
            "fallback": "标记'数据缺失'",
            "note": "⚠️ push2ex 不可达，涨停数据源自同花顺涨停揭秘",
        }
    else:
        paths["limit_up"] = {
            "primary": "标记'数据缺失'",
            "fallback": "",
            "note": "⚠️ push2ex 与同花顺均不可达，涨停板数据缺失",
        }

    # 6. 同花顺热点（题材归因）— 独立数据源
    paths["hot_themes"] = {
        "primary": "同花顺热点 reason tags" if ths_ok else "标记'数据缺失'",
        "fallback": "东财人气榜概念命中" if ths_ok else "",
        "note": "" if ths_ok else "⚠️ 同花顺热点不可达，题材归因数据缺失",
    }

    # 7. 海外市场
    paths["overseas"] = {
        "primary": "腾讯财经（海外指数）" if tencent_ok else "WebSearch 综合搜索",
        "fallback": "WebSearch 综合搜索",
        "note": "" if tencent_ok else "⚠️ 腾讯财经海外指数不可达，使用 WebSearch 替代",
    }

    # 8. K线数据
    paths["kline"] = {
        "primary": "mootdx TCP" if mootdx_ok else "腾讯财经日K + pandas 本地算技术指标",
        "fallback": "腾讯财经日K（百度股市通兜底）",
        "note": "" if mootdx_ok else "⚠️ mootdx TCP 不可达（海外网络限制），K线数据源自腾讯财经日K",
    }

    return paths


def main():
    # Windows 控制台默认 GBK，note 中的 ⚠️(U+26A0) 会触发 UnicodeEncodeError
    # （实测 2026-08-19：push2 fail 时 note 含 ⚠️，print 崩溃）。强制 UTF-8 输出。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="数据源连通性探测")
    parser.add_argument("--output", default="",
                        help="输出 JSON 文件路径（默认 stdout）")
    parser.add_argument("--pretty", action="store_true",
                        help="格式化 JSON 输出")
    args = parser.parse_args()

    # 执行探测
    status = {
        "push2": _probe_push2(),
        "push2his": _probe_push2his(),
        "tencent": _probe_tencent(),
        "ths": _probe_ths(),
        "push2ex": _probe_push2ex(),
        "mootdx": _probe_mootdx(),
        "datacenter": _probe_datacenter(),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 生成数据路径建议
    paths = get_data_paths(status)

    # 计算整体状态摘要
    ok_count = sum(1 for k, v in status.items() if k != "timestamp" and v == "ok")
    total = len([k for k in status if k != "timestamp"])
    overall = "all_ok" if ok_count == total else "partial" if ok_count > 0 else "all_fail"

    result = {
        "status": status,
        "overall": overall,
        "ok_count": ok_count,
        "total_sources": total,
        "paths": paths,
        "note": "数据源探测结果 — 用于 Prompt 判断数据采集路径",
    }

    output = json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"探测结果已写入 {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
