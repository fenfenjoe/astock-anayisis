#!/usr/bin/env python3
"""joinquant_backtest.py — 聚宽平台回测（路径 B2）：研究环境回测 API。

聚宽官方研究环境 API（https://www.joinquant.com/help/api/help?name=api）：
- `POST /algorithm/index/build?ajax=1` — 从策略ID创建回测（实测端点，form 格式）
- `GET /algorithm/backtest/detail?backtestId=` — 查询回测结果（实测返回完整指标）

**前置条件：需要有效的聚宽登录态（Cookie token+uid）。**
社区列表/详情 API（listV2/detailV2）匿名可用，但研究环境回测 API **必须登录**：
- create_backtest 在"研究中"执行，需要登录态
- get_backtest 读取回测结果，需要登录态

Cookie 提供方式（与 fetch_joinquant_forum.py 一致）：
- 主路径：agent.db platform_cookies 表（Dashboard「角色页 → 认识小满 → 爱逛的地方」
  → 聚宽 → 去登录 → 登录后刷新）
- 备路径：`--cookie "token=xxx; uid=yyy"` 直接传（调试用）
- 或 `--from-browser` 从浏览器档案读（需先 open_login_window 登录过）

用法：
    # 从帖子 backtestId 拉回测摘要（无需登录，帖子内嵌指标）
    python joinquant_backtest.py summary <backtestId>

    # 创建回测（从策略ID，需登录）
    python joinquant_backtest.py create <algorithm_id> --start 2020-01-01 --end 2026-09-30

    # 查询回测状态/结果（需登录）
    python joinquant_backtest.py status <backtest_id>
    python joinquant_backtest.py poll <backtest_id> --timeout 600

    # 删除回测释放并行配额（聚宽并行回测上限 2 个，需登录）
    python joinquant_backtest.py del <backtest_id>
"""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "https://www.joinquant.com"
LOGIN_CHECK_URL = BASE_URL + "/user/index/isLogin"
BACKTEST_SUMMARY_URL = BASE_URL + "/algorithm/backtest/summary"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/plain, */*",
}

SCRIPT_DIR = Path(__file__).resolve().parent
ETF_STRATEGIES_DIR = SCRIPT_DIR.parent.parent  # etf-strategies/
AGENT_DB = ETF_STRATEGIES_DIR / "agent" / "data" / "agent.db"


# ── Cookie 获取 ──

def read_cookie_from_db():
    """读 agent.db / 云库 platform_cookies 中 joinquant 的 Cookie；无/异常 → None。

    云库优先（AGENT_DB_BACKEND=cloud 时 agent 常驻进程读写云库 platform_cookies）；
    本地 SQLite 兜底（脚本独立运行 / 未配置云时）。
    """
    # 1) 云库优先：加载 .env 后 agent.db 的 platform_cookie_get 自动走云库
    try:
        sys.path.insert(0, str(ETF_STRATEGIES_DIR))
        try:
            from load_env import load_env_file

            load_env_file()
        except ImportError:
            pass
        import agent.db as adb

        c = adb.platform_cookie_get("joinquant")
        if c:
            return c
    except Exception:
        pass
    # 2) 本地 SQLite 兜底
    if not AGENT_DB.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{AGENT_DB}?mode=ro", uri=True, timeout=5)
        try:
            row = conn.execute(
                "SELECT cookie FROM platform_cookies WHERE platform_id=?",
                ("joinquant",),
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return None


def read_cookie_from_browser():
    """从浏览器档案读聚宽 cookie（需先 open_login_window 登录过）。"""
    try:
        sys.path.insert(0, str(ETF_STRATEGIES_DIR))
        from agent.core import browser_cookies

        return browser_cookies.read_platform_cookie("joinquant")
    except Exception:
        return None


def resolve_cookie(explicit=None, from_browser=False):
    """解析 Cookie：显式 > agent.db > 浏览器档案。"""
    if explicit:
        return explicit
    c = read_cookie_from_db()
    if c:
        return c
    if from_browser:
        return read_cookie_from_browser()
    return None


# ── 登录态 ──

def is_logged_in(cookie):
    """聚宽登录态校验：/user/index/isLogin → data.isLogin==1。"""
    import requests

    try:
        headers = dict(HEADERS)
        if cookie:
            headers["Cookie"] = cookie
        r = requests.get(LOGIN_CHECK_URL, headers=headers, timeout=10)
        if r.status_code != 200:
            return False
        return r.json().get("data", {}).get("isLogin") == 1
    except Exception:
        return False


# ── 回测摘要（帖子内嵌指标，匿名可用） ──

def fetch_backtest_summary(backtest_id, post_id=None, cookie=None):
    """拉取回测摘要页面并解析隐藏字段。

    聚宽 /algorithm/backtest/summary 返回 SPA HTML 外壳，指标由 JS 渲染；
    但页面含隐藏 input 字段（真实 backtestId / backtest-status 等）。
    本函数解析 HTML 提取有用信息（匿名可用，无需登录）。

    返回 dict：
      - request_backtest_id: 请求的 backtestId
      - resolved_backtest_id: 页面隐藏字段里的真实回测ID（可能不同）
      - page_size: 页面字节数
    失败 → None。
    """
    import re

    import requests

    params = {"backtestId": backtest_id, "iframe": 1}
    if post_id:
        params["postId"] = post_id
    headers = dict(HEADERS)
    if cookie:
        headers["Cookie"] = cookie
    try:
        r = requests.get(BACKTEST_SUMMARY_URL, headers=headers, params=params, timeout=20)
        if r.status_code != 200:
            return None
        html = r.text
        # 隐藏 input 里的 backtestId（可能多个，取第一个）
        ids = re.findall(
            r'<input[^>]*id="backtestId"[^>]*value="([^"]+)"', html
        )
        return {
            "request_backtest_id": backtest_id,
            "resolved_backtest_id": ids[0] if ids else None,
            "page_size": len(html),
        }
    except Exception:
        return None


# ── 研究环境回测 API（需登录） ──
#
# 实测确认（2026-10-10，登录态下抓包）：
#   - 创建回测：POST /algorithm/index/build?ajax=1（form-urlencoded）
#       algorithm[algorithmId] / algorithm[userId] / algorithm[name] / algorithm[code]
#       backtest[startTime] / backtest[endTime] / backtest[baseCapital] / backtest[frequency]
#       backtest[pyVersion] / encrType(plain|base64)
#     返回 {"data":{"backtestId":"...","tradeDays":[...]}}
#     无需显式 token（有效登录 cookie 即可）
#     ⚠️ 必须带 Referer=/algorithm/index/edit（否则聚宽静默返回空 data）
#   - 查询回测：GET /algorithm/backtest/detail?backtestId=...
#     返回完整指标（overallReturn/maxDrawdown/yearReturn/alpha/beta/sharpe...）

CREATE_BACKTEST_URL = BASE_URL + "/algorithm/index/build?ajax=1"
GET_BACKTEST_URL = BASE_URL + "/algorithm/backtest/detail"

# 回测创建时需要 algorithm 的 userId（算法归属者）。缺省从策略页/用户信息获取。
def _get_user_id(cookie):
    """拉取当前登录用户的 userId（聚宽账号 ID）。

    实测（2026-10-10）：build 请求的 algorithm[userId] 必须填**登录用户**的
    userId，可从 /user/index/isLogin 的 data.userId 拿到（build 时缺省 userId
    会导致返回空 data 创建失败）。失败返回 None。
    """
    import requests

    try:
        headers = dict(HEADERS)
        headers["Cookie"] = cookie
        r = requests.get(LOGIN_CHECK_URL, headers=headers, timeout=10)
        if r.status_code == 200:
            d = r.json().get("data") or {}
            return d.get("userId") or None
    except Exception:
        pass
    return None


def create_backtest(algorithm_id, start_date, end_date, cookie,
                    frequency="day", initial_cash="100000", name=None,
                    algorithm_code=None, encr_type="plain", user_id=None,
                    py_version="3", retries=6, retry_wait=15):
    """从策略ID创建回测（研究环境 API，需登录）。

    algorithm_id: 策略ID（策略编辑页 URL /algorithm/index/edit?algorithmId=xxx 中的 xxx）
    algorithm_code: 策略源码（缺省只建空壳回测；传源码则用平台编译运行真实策略）
    encr_type: "plain"（明文）或 "base64"（聚宽前端默认 base64）

    ⚠️ 聚宽并行回测上限 2 个：并发超限时返回 {"data":[],"status":"0"} 或
       {"data":null,"status":"2","code":"20000","msg":"当前并行编译或回测数量最多2个"}。
       本函数自动等待重试（retries×retry_wait 秒）。

    返回 dict：{algorithmId, backtestId, backtestId_, tradeDays, ...}
    """
    import requests
    import time

    # 缺省 user_id 时尝试拉取（实际聚宽以 cookie 身份为准，userId 可留空）
    if not user_id:
        user_id = _get_user_id(cookie) or ""

    payload = {
        "algorithm[algorithmId]": algorithm_id,
        "algorithm[userId]": user_id,
        "algorithm[accessControl]": "0",
        "backtest[type]": "1",
        "algorithm[name]": name or "策略回测",
        "backtest[startTime]": start_date + " 00:00:00",
        "backtest[endTime]": end_date + " 23:59:59",
        "backtest[baseCapital]": str(initial_cash),
        "backtest[frequency]": frequency,
        "backtest[pyVersion]": py_version,
        "encrType": encr_type,
        "algorithm[code]": algorithm_code or "# 测试策略\npass",
        "ajax": "1",
    }
    headers = dict(HEADERS)
    headers["Cookie"] = cookie
    headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    # 实测（2026-10-10）：build 必须带 Referer=/algorithm/index/edit，
    # 否则聚宽静默返回空 data（{"data":[],"status":"0"}）创建失败。
    headers["Referer"] = BASE_URL + "/algorithm/index/edit"

    last_err = None
    for attempt in range(retries):
        try:
            r = requests.post(CREATE_BACKTEST_URL, headers=headers, data=payload, timeout=30)
            r.raise_for_status()
            data = r.json()
            bt = data.get("data") or {}
            if isinstance(bt, dict) and bt.get("backtestId"):
                return bt
            # 明确错误（非并发）→ 立即抛出
            msg = str(data.get("msg") or "")
            if data.get("status") == "2" and "并行" not in msg and "最多" not in msg:
                raise RuntimeError(f"创建回测失败: {msg or data}")
            # 空 data / 并发限制 → 等待重试（聚宽并行回测上限 2 个）
            last_err = msg or f"创建回测未返回 backtestId: {data}"
            if attempt < retries - 1:
                time.sleep(retry_wait)
                continue
        except requests.RequestException as e:
            last_err = str(e)
            if attempt < retries - 1:
                time.sleep(retry_wait)
                continue
    raise RuntimeError(f"创建回测失败: {last_err}")


def get_backtest_status(backtest_id, cookie):
    """查询回测状态（需登录）。返回 {status, ...}。"""
    import requests

    headers = dict(HEADERS)
    headers["Cookie"] = cookie
    r = requests.get(
        GET_BACKTEST_URL,
        headers=headers,
        params={"backtestId": backtest_id},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def delete_backtest(backtest_id, cookie):
    """删除回测（释放聚宽并行配额）。实测端点 POST /algorithm/backtest/del。"""
    import requests

    headers = dict(HEADERS)
    headers["Cookie"] = cookie
    headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    r = requests.post(
        BASE_URL + "/algorithm/backtest/del",
        headers=headers,
        data={"backtestId": backtest_id, "ajax": "1"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def poll_backtest(backtest_id, cookie, interval=10, timeout=600):
    """轮询回测直到 done/failed/canceled。返回最终状态 dict。"""
    import requests

    headers = dict(HEADERS)
    headers["Cookie"] = cookie
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = get_backtest_status(backtest_id, cookie)
        status = (data.get("data") or {}).get("status") or data.get("status")
        if status in ("done", "failed", "canceled", "deleted"):
            return data
        time.sleep(interval)
    raise TimeoutError(f"回测 {backtest_id} 超时（{timeout}s 未完成）")


# ── CLI ──

def main() -> int:
    ap = argparse.ArgumentParser(description="聚宽平台回测（研究环境 API，需登录态）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_summary = sub.add_parser("summary", help="拉取帖子内嵌回测摘要（匿名可用）")
    p_summary.add_argument("backtest_id")
    p_summary.add_argument("--post-id", default=None)

    p_create = sub.add_parser("create", help="从策略ID创建回测（需登录）")
    p_create.add_argument("algorithm_id")
    p_create.add_argument("--start", required=True)
    p_create.add_argument("--end", required=True)
    p_create.add_argument("--frequency", default="day")
    p_create.add_argument("--cash", default="100000")
    p_create.add_argument("--name", default=None)
    p_create.add_argument("--code", default=None, help="策略源码文件路径（缺省只建空壳回测）")

    p_status = sub.add_parser("status", help="查询回测状态（需登录）")
    p_status.add_argument("backtest_id")

    p_poll = sub.add_parser("poll", help="轮询回测直到完成（需登录）")
    p_poll.add_argument("backtest_id")
    p_poll.add_argument("--interval", type=int, default=10)
    p_poll.add_argument("--timeout", type=int, default=600)

    p_del = sub.add_parser("del", help="删除回测释放并行配额（需登录）")
    p_del.add_argument("backtest_id")

    p_verify = sub.add_parser("verify", help="验证登录态 + 回测API端点可用性")
    p_verify.add_argument("backtest_id", nargs="?", default=None)

    ap.add_argument("--cookie", default=None, help="显式 Cookie（调试用）")
    ap.add_argument("--from-browser", action="store_true", help="从浏览器档案读 Cookie")
    args = ap.parse_args()

    # summary 命令匿名可用，无需 Cookie 解析
    if args.cmd == "summary":
        data = fetch_backtest_summary(args.backtest_id, post_id=args.post_id)
        if data is None:
            print("拉取回测摘要失败（backtestId 可能无效）", file=sys.stderr)
            return 1
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    # 其余命令需登录
    cookie = resolve_cookie(explicit=getattr(args, "cookie", None), from_browser=getattr(args, "from_browser", False))
    if not is_logged_in(cookie):
        print(
            "聚宽未登录：研究环境回测 API 需要有效 Cookie（token+uid）。\n"
            "请在 Dashboard「角色页 → 认识小满 → 爱逛的地方」对聚宽点「去登录」，"
            "登录后刷新；或 --cookie \\\"token=xxx; uid=yyy\\\" 直接传入。",
            file=sys.stderr,
        )
        return 3

    if args.cmd == "verify":
        print("登录态: OK")
        if args.backtest_id:
            data = fetch_backtest_summary(args.backtest_id, cookie=cookie)
            print("回测摘要接口:", "OK" if data is not None else "FAIL")
            if data:
                print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
        return 0

    if args.cmd == "create":
        try:
            code = None
            if args.code:
                code = Path(args.code).read_text(encoding="utf-8")
            out = create_backtest(
                args.algorithm_id, args.start, args.end, cookie,
                frequency=args.frequency, initial_cash=args.cash, name=args.name,
                algorithm_code=code,
            )
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0
        except Exception as e:
            print(f"创建回测失败: {e}", file=sys.stderr)
            return 1

    if args.cmd == "status":
        try:
            out = get_backtest_status(args.backtest_id, cookie)
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0
        except Exception as e:
            print(f"查询失败: {e}", file=sys.stderr)
            return 1

    if args.cmd == "poll":
        try:
            out = poll_backtest(args.backtest_id, cookie, interval=args.interval, timeout=args.timeout)
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0
        except Exception as e:
            print(f"轮询失败: {e}", file=sys.stderr)
            return 1

    if args.cmd == "del":
        try:
            out = delete_backtest(args.backtest_id, cookie)
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0
        except Exception as e:
            print(f"删除失败: {e}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
