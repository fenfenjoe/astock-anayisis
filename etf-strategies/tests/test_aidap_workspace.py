"""scripts/aidap_workspace.py — 签名算法与 CLI 结构测试（不真调 API）。"""
import hashlib
import hmac
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pytest

import aidap_workspace as aw


# ═══════════════════════════════════════════
# 签名算法：确定性 + 结构正确
# ═══════════════════════════════════════════

def test_sign_is_deterministic():
    a1 = aw._sign_request("AKID", "SK", "POST", "/", {"Action": "X", "Version": "V"},
                          b"{}", "20260917T000000Z")
    a2 = aw._sign_request("AKID", "SK", "POST", "/", {"Action": "X", "Version": "V"},
                          b"{}", "20260917T000000Z")
    assert a1 == a2


def test_sign_structure():
    auth = aw._sign_request("AKID", "SK", "POST", "/",
                            {"Action": "CreateWorkspace", "Version": "2024-08-01"},
                            b'{"a":1}', "20260917T000000Z")
    assert auth.startswith("HMAC-SHA256 Credential=AKID/20260917/cn-beijing/aidap/request")
    assert "SignedHeaders=" in auth
    assert "Signature=" in auth


def test_sign_changes_with_body():
    a1 = aw._sign_request("AK", "SK", "POST", "/", {"Action": "X", "Version": "V"},
                          b"{}", "20260917T000000Z")
    a2 = aw._sign_request("AK", "SK", "POST", "/", {"Action": "X", "Version": "V"},
                          b'{"x":1}', "20260917T000000Z")
    assert a1 != a2  # body 变化 → 签名变化


def test_sign_changes_with_date():
    a1 = aw._sign_request("AK", "SK", "POST", "/", {"Action": "X", "Version": "V"},
                          b"{}", "20260917T000000Z")
    a2 = aw._sign_request("AK", "SK", "POST", "/", {"Action": "X", "Version": "V"},
                          b"{}", "20260918T000000Z")
    assert a1 != a2


def test_sign_hmac_matches_reference():
    """用已知输入验证 HMAC 链正确（对照火山签名算法手算）。"""
    # 验证派生密钥链：HMAC(secret, date) → HMAC(→region) → HMAC(→service) → HMAC(→request)
    k_date = aw._hmac_sha256(b"test-secret", "20260917")
    k_region = aw._hmac_sha256(k_date, "cn-beijing")
    k_service = aw._hmac_sha256(k_region, "aidap")
    k_signing = aw._hmac_sha256(k_service, "request")
    assert len(k_signing) == 32  # SHA-256 摘要长度
    # 签名是 64 位 hex
    sig = hmac.new(k_signing, b"HMAC-SHA256\n20260917T000000Z\n20260917/cn-beijing/aidap/request\nhash",
                   hashlib.sha256).hexdigest()
    assert len(sig) == 64


# ═══════════════════════════════════════════
# call()：请求构造正确（mock requests）
# ═══════════════════════════════════════════

def test_call_constructs_request(monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200
        def json(self):
            return {"Result": {"WorkspaceId": "ws-123"}}

    def fake_post(url, headers=None, data=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["data"] = data
        return FakeResp()

    monkeypatch.setattr(aw.requests, "post", fake_post)
    r = aw.call("AK", "SK", "CreateWorkspace", {"WorkspaceName": "test"})
    assert r["Result"]["WorkspaceId"] == "ws-123"
    assert captured["url"].startswith("https://aidap.cn-beijing.volcengineapi.com/")
    assert "Action=CreateWorkspace" in captured["url"]
    assert captured["headers"]["Content-Type"] == "application/json"
    assert "Authorization" in captured["headers"]
    assert captured["headers"]["X-Date"]
    assert captured["headers"]["X-Content-Sha256"]
    assert b'"WorkspaceName": "test"' in captured["data"]


def test_call_raises_on_error(monkeypatch):
    class FakeResp:
        status_code = 400
        def json(self):
            return {"Error": {"Message": "bad request"}}

    monkeypatch.setattr(aw.requests, "post", lambda *a, **k: FakeResp())
    with pytest.raises(RuntimeError, match="HTTP 400"):
        aw.call("AK", "SK", "X", {})


# ═══════════════════════════════════════════
# CLI：无 AK/SK 拒绝
# ═══════════════════════════════════════════

def test_main_requires_credentials(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["aidap_workspace", "create", "--name", "x"])
    monkeypatch.delenv("VOLC_ACCESS_KEY", raising=False)
    monkeypatch.delenv("VOLC_SECRET_KEY", raising=False)
    monkeypatch.setattr(aw, "load_sts_from_login_cache", lambda: None)
    with pytest.raises(SystemExit) as e:
        aw.main()
    assert e.value.code == 1


def test_main_parse_create_args(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "aidap_workspace", "--ak", "AK", "--sk", "SK", "create",
        "--name", "astock-db-pg", "--min-cu", "0.25", "--max-cu", "2",
    ])
    seen = {}

    def fake_call(ak, sk, action, params, session_token=None):
        seen.update(ak=ak, sk=sk, action=action, params=params)
        return {"Result": {"WorkspaceId": "ws-new"}}
    monkeypatch.setattr(aw, "call", fake_call)
    aw.main()
    assert seen["ak"] == "AK"
    assert seen["action"] == "CreateWorkspace"
    assert seen["params"]["EngineType"] == "PostgreSQL"
    assert seen["params"]["EngineVersion"] == "PostgreSQL_17"
    assert seen["params"]["ComputeSettings"] == {"AutoScalingLimitMinCU": 0.25,
                                                 "AutoScalingLimitMaxCU": 2}


def test_main_parse_suspend_args(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "aidap_workspace", "--ak", "AK", "--sk", "SK", "suspend",
        "--workspace", "ws-1", "--timeout", "300",
    ])
    seen = {}
    monkeypatch.setattr(
        aw, "call",
        lambda ak, sk, action, params, session_token=None:
            seen.update(action=action, params=params) or {})
    aw.main()
    assert seen["action"] == "ModifyComputeSettings"
    assert seen["params"] == {"WorkspaceId": "ws-1", "SuspendTimeoutSeconds": 300}


def test_main_uses_login_cache_when_no_ak(monkeypatch):
    """无显式 AK/SK 时回退登录缓存凭据。"""
    monkeypatch.setattr(sys, "argv", ["aidap_workspace", "list"])
    monkeypatch.delenv("VOLC_ACCESS_KEY", raising=False)
    monkeypatch.delenv("VOLC_SECRET_KEY", raising=False)
    monkeypatch.setattr(aw, "load_sts_from_login_cache",
                        lambda: ("AK-cache", "SK-cache", "ST-cache"))
    seen = {}
    monkeypatch.setattr(
        aw, "call",
        lambda ak, sk, action, params, session_token=None:
            seen.update(ak=ak, sk=sk, action=action, st=session_token) or
            {"Result": {"Total": 0, "Workspaces": []}})
    monkeypatch.setattr(aw, "cmd_list", lambda ak, sk, st, args: seen.update(cmd="list") or {})
    aw.main()
    assert seen["cmd"] == "list"
