# -*- coding: utf-8 -*-
"""aidap_workspace.py — 火山 AIDAP PostgreSQL 引擎 workspace 自动化（OpenAPI）。

不依赖 volcengine SDK：纯 requests + HMAC-SHA256 签名（火山标准签名机制）。

自动完成：
  1. 创建 PostgreSQL 引擎 workspace（0.25~2 CU）
  2. 配置「算力空闲时自动挂起」SuspendTimeoutSeconds=300
  3. 查询数据库账号连接串（DescribeDBAccountConnection）
  4. 列出已有 workspaces（DescribeWorkspaces，只读）

凭据来源（优先级）：
  A. --ak/--sk/--session-token 显式参数
  B. 环境变量 VOLC_ACCESS_KEY / VOLC_SECRET_KEY / VOLC_SESSION_TOKEN
  C. 自动读取 ~/.volcengine/login/cache/*.json（火山 SSO 登录态），
     过期时用 refresh_token 自动刷新（endpoint: signin.volcengine.com/authorize/oauth/token）

用法：
    # 用登录缓存凭据（推荐，无需提供 AK/SK）
    python scripts/aidap_workspace.py list
    python scripts/aidap_workspace.py create --name astock-db-pg [--min-cu 0.25] [--max-cu 2]
    python scripts/aidap_workspace.py suspend --workspace <ID> [--timeout 300]
    python scripts/aidap_workspace.py conn --workspace <ID> [--account <name>] [--db <name>]

    # 显式 AK/SK
    python scripts/aidap_workspace.py --ak <AK> --sk <SK> create --name astock-db-pg
"""
import argparse
import glob
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

REGION = "cn-beijing"
HOST = f"aidap.{REGION}.volcengineapi.com"
SCHEME = "https"
# AIDAP OpenAPI 版本（来自 volcengine-go-sdk service/aidap/service_aidap.go:
# APIVersion: "2025-10-01"）
VERSION = "2025-10-01"
SIGNIN_BASE = "https://signin.volcengine.com"


def _sha256_hex(s: bytes) -> str:
    return hashlib.sha256(s).hexdigest()


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _sign_request(ak: str, sk: str, method: str, url_path: str,
                  query: dict, body: bytes, x_date: str) -> str:
    """火山引擎 OpenAPI 签名（HMAC-SHA256）。返回 Authorization header 值。"""
    # 1. CanonicalQueryString：参数按 ASCII 排序，RFC3986 编码
    canonical_qs = "&".join(
        f"{quote(k, safe='-_.~')}={quote(str(v), safe='-_.~')}"
        for k, v in sorted(query.items())
    )
    # 2. CanonicalHeaders：host + x-date + x-content-sha256
    payload_hash = _sha256_hex(body)
    headers = {
        "host": HOST,
        "x-date": x_date,
        "x-content-sha256": payload_hash,
    }
    canonical_headers = "".join(
        f"{k}:{str(v).strip()}\n" for k, v in sorted(headers.items())
    )
    signed_headers = ";".join(sorted(headers.keys()))
    # 3. CanonicalRequest
    canonical_request = "\n".join([
        method, url_path, canonical_qs, canonical_headers, signed_headers, payload_hash,
    ])
    # 4. 签名串
    date = x_date[:8]
    scope = f"{date}/{REGION}/aidap/request"
    string_to_sign = "\n".join([
        "HMAC-SHA256", x_date, scope, _sha256_hex(canonical_request.encode()),
    ])
    # 5. 派生密钥链
    k_date = _hmac_sha256(sk.encode(), date)
    k_region = _hmac_sha256(k_date, REGION)
    k_service = _hmac_sha256(k_region, "aidap")
    k_signing = _hmac_sha256(k_service, "request")
    signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
    return (
        f"HMAC-SHA256 Credential={ak}/{scope}, SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )


def call(ak: str, sk: str, action: str, params: dict,
         session_token: str | None = None) -> dict:
    """调用 AIDAP OpenAPI。params 为接口业务参数（并入 query + body）。

    session_token 为 STS 临时凭据时必传（火山 SSO 登录场景），
    签名时作为 X-Security-Token 请求头。
    """
    x_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    query = {"Action": action, "Version": VERSION}
    body = json.dumps(params, ensure_ascii=False).encode("utf-8")
    url_path = "/"
    auth = _sign_request(ak, sk, "POST", url_path, query, body, x_date)
    headers = {
        "Content-Type": "application/json",
        "X-Date": x_date,
        "X-Content-Sha256": _sha256_hex(body),
        "Authorization": auth,
        "Host": HOST,
    }
    if session_token:
        headers["X-Security-Token"] = session_token
    url = f"{SCHEME}://{HOST}{url_path}"
    if query:
        url += "?" + "&".join(f"{k}={quote(str(v), safe='-_.~')}" for k, v in query.items())
    resp = requests.post(url, headers=headers, data=body, timeout=60)
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text[:500]}
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}: {json.dumps(payload, ensure_ascii=False)[:600]}")
    return payload


def load_sts_from_login_cache():
    """从 ~/.volcengine/login/cache/*.json 读取火山 SSO 登录态并刷新 STS。

    返回 (access_key_id, secret_access_key, session_token)。
    缓存里的 STS 有效期仅 900s，几乎必然已过期 → 总是用 refresh_token 刷新；
    刷新失败才回退到缓存里的旧 STS。
    """
    files = sorted(glob.glob(str(Path.home() / ".volcengine" / "login" / "cache" / "*.json")))
    if not files:
        return None
    try:
        tok = json.loads(Path(files[-1]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    refresh = tok.get("refresh_token")
    client_id = tok.get("client_id")
    if refresh and client_id:
        try:
            r = requests.post(f"{SIGNIN_BASE}/authorize/oauth/token", data={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": client_id,
            }, timeout=30, headers={"Content-Type": "application/x-www-form-urlencoded"})
            if r.status_code == 200:
                inner = json.loads(r.json()["access_token"])
                return inner["access_key_id"], inner["secret_access_key"], inner["session_token"]
            print(f"[aidap] STS 刷新失败: HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"[aidap] STS 刷新异常: {e}")
    # 回退：缓存里的旧 STS
    at = tok.get("access_token") or {}
    ak, sk, st = at.get("access_key_id"), at.get("secret_access_key"), at.get("session_token")
    if ak and sk and st:
        print("[aidap] 回退使用缓存 STS（可能已过期）")
        return ak, sk, st
    return None


def cmd_list(ak, sk, st, args):
    """列出账号下所有 AIDAP workspaces（只读）。"""
    r = call(ak, sk, "DescribeWorkspaces", {"PageSize": 100}, session_token=st)
    result = r.get("Result") or {}
    workspaces = result.get("Workspaces") or []
    print(f"[aidap] 账号下共 {result.get('Total', len(workspaces))} 个 workspace:\n")
    for w in workspaces:
        print(f"  {w.get('WorkspaceId')}  {w.get('WorkspaceName')}")
        print(f"    引擎: {w.get('EngineType')} {w.get('EngineVersion')}"
              f" | 状态: {w.get('Status')} | 地域: {w.get('RegionId')}")
        cs = w.get("ComputeSettings") or {}
        bs = w.get("BaasComputeSettings") or {}
        print(f"    算力: {cs.get('AutoScalingLimitMinCU')}~{cs.get('AutoScalingLimitMaxCU')} CU"
              f" | 挂起阈值: {bs.get('SuspendTimeoutSeconds', '未设置')}s")
        print()
    return r


def cmd_create(ak, sk, st, args):
    params = {
        "WorkspaceName": args.name,
        "EngineType": "PostgreSQL",
        "EngineVersion": "PostgreSQL_17",
        "ComputeSettings": {
            "AutoScalingLimitMinCU": args.min_cu,
            "AutoScalingLimitMaxCU": args.max_cu,
        },
        "BranchSettings": {"BranchName": "main"},
    }
    print(f"[aidap] 创建 PostgreSQL workspace: {args.name} "
          f"(算力 {args.min_cu}~{args.max_cu} CU)")
    r = call(ak, sk, "CreateWorkspace", params, session_token=st)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    wid = (r.get("Result") or {}).get("WorkspaceId") or (r.get("WorkspaceId") or "")
    if wid:
        print(f"\n[aidap] 创建成功！WorkspaceId = {wid}")
        print("[aidap] 下一步：配置自动挂起 + 查连接串")
    return wid


def cmd_suspend(ak, sk, st, args):
    params = {
        "WorkspaceId": args.workspace,
        # ModifyComputeSettingsInput：AutoScalingLimitMinCU/MaxCU 为必填
        "AutoScalingLimitMinCU": args.min_cu,
        "AutoScalingLimitMaxCU": args.max_cu,
        "SuspendTimeoutSeconds": args.timeout,
    }
    print(f"[aidap] 配置自动挂起: workspace={args.workspace} "
          f"SuspendTimeoutSeconds={args.timeout} "
          f"(算力 {args.min_cu}~{args.max_cu} CU)")
    r = call(ak, sk, "ModifyComputeSettings", params, session_token=st)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return r


def cmd_conn(ak, sk, st, args):
    params = {"WorkspaceId": args.workspace}
    if args.account:
        params["AccountName"] = args.account
    if args.db:
        params["DatabaseName"] = args.db
    r = call(ak, sk, "DescribeDBAccountConnection", params, session_token=st)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    # 提取连接串（常见字段：ConnectionString / ConnectionInfo）
    result = r.get("Result") or r
    for key in ("ConnectionString", "ConnectionInfo", "ConnectionUrl", "Dsn"):
        if isinstance(result, dict) and result.get(key):
            print(f"\n[aidap] 连接串({key}): {result[key]}")
    return r


def cmd_delete(ak, sk, st, args):
    """删除 workspace（不可逆；有删除保护时先关闭保护再删）。"""
    params = {"WorkspaceId": args.workspace}
    print(f"[aidap] 删除 workspace: {args.workspace}")
    try:
        r = call(ak, sk, "DeleteWorkspace", params, session_token=st)
    except Exception as e:
        if args.force and "DeletionProtection" in str(e):
            print("[aidap] 检测到删除保护，先关闭保护...")
            call(ak, sk, "ModifyWorkspaceDeletionProtectionPolicy",
                 {"WorkspaceId": args.workspace, "DeletionProtection": "Disabled"},
                 session_token=st)
            print("[aidap] 删除保护已关闭，重试删除...")
            r = call(ak, sk, "DeleteWorkspace", params, session_token=st)
        else:
            raise
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return r


def _resolve_creds(args):
    """按优先级解析凭据：显式参数 > 环境变量 > 登录缓存。"""
    ak, sk, st = args.ak, args.sk, getattr(args, "session_token", None)
    if ak and sk:
        return ak, sk, st or os.environ.get("VOLC_SESSION_TOKEN", "")
    from_cache = load_sts_from_login_cache()
    if from_cache:
        print("[aidap] 使用 ~/.volcengine 登录缓存凭据（自动刷新 STS）")
        return from_cache
    return None


def main():
    ap = argparse.ArgumentParser(description="火山 AIDAP PostgreSQL workspace 自动化")
    ap.add_argument("--ak", default=os.environ.get("VOLC_ACCESS_KEY", ""))
    ap.add_argument("--sk", default=os.environ.get("VOLC_SECRET_KEY", ""))
    ap.add_argument("--session-token", default=os.environ.get("VOLC_SESSION_TOKEN", ""),
                    help="STS session token（SSO 登录态自动获取时无需提供）")
    ap.add_argument("--region", default=REGION)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="列出 workspaces（只读）")

    p_create = sub.add_parser("create", help="创建 PostgreSQL workspace")
    p_create.add_argument("--name", required=True, help="workspace 名称（如 astock-db-pg）")
    p_create.add_argument("--min-cu", type=float, default=0.25)
    p_create.add_argument("--max-cu", type=float, default=2)

    p_suspend = sub.add_parser("suspend", help="配置算力空闲自动挂起")
    p_suspend.add_argument("--workspace", required=True)
    p_suspend.add_argument("--timeout", type=int, default=300, help="挂起阈值秒数（300~604800）")
    p_suspend.add_argument("--min-cu", type=float, default=0.25)
    p_suspend.add_argument("--max-cu", type=float, default=2)

    p_conn = sub.add_parser("conn", help="查询数据库账号连接串")
    p_conn.add_argument("--workspace", required=True)
    p_conn.add_argument("--account", default=None)
    p_conn.add_argument("--db", default=None)

    p_delete = sub.add_parser("delete", help="删除 workspace（不可逆，需先关删除保护）")
    p_delete.add_argument("--workspace", required=True)
    p_delete.add_argument("--force", action="store_true",
                          help="遇删除保护时自动关闭保护再删")

    args = ap.parse_args()
    creds = _resolve_creds(args)
    if not creds:
        print("ERROR: 无可用凭据（--ak/--sk、VOLC_ACCESS_KEY/VOLC_SECRET_KEY，"
              "或 ~/.volcengine 登录缓存）")
        sys.exit(1)
    ak, sk, st = creds
    globals()[f"cmd_{args.cmd}"](ak, sk, st, args)


if __name__ == "__main__":
    main()
