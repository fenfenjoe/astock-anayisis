"""Tests for dashboard/auth.py — JWT auth, login flow, protected routes."""
import sys
import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

# ── Install lightweight mocks before importing the app ──
# daily_signal is mocked by conftest.py — do NOT create a separate mock here
# as it breaks the shared mock state used by test_dashboard_app.py.

_mock_html_report = MagicMock()
sys.modules["html_report"] = _mock_html_report

# Patch DB user functions — tests control them directly
_FAKE_USER = {
    "id": 1,
    "username": "admin",
    "password_hash": None,  # set in each test
    "display_name": "管理员",
    "role": "admin",
    "is_active": 1,
    "created_at": "2024-01-01",
    "last_login": None,
}

_mock_user_get = MagicMock(return_value=_FAKE_USER)
_mock_user_create = MagicMock()
_mock_user_update_login = MagicMock()
_mock_user_change_pw = MagicMock()
_mock_user_count = MagicMock(return_value=1)

# We need to patch the imports INSIDE auth.py / app.py after they're loaded.
# The cleanest way: patch on the app module directly.

from dashboard.auth import hash_password, verify_password, create_token, decode_token


# ═══════════════════════════════════════════════════════════════
# Unit Tests: Password Hashing
# ═══════════════════════════════════════════════════════════════

class TestPasswordHashing:
    def test_hash_produces_bcrypt_string(self):
        h = hash_password("test123456")
        assert h.startswith("$2b$")

    def test_verify_correct_password(self):
        h = hash_password("correct-horse")
        assert verify_password("correct-horse", h) is True

    def test_verify_incorrect_password(self):
        h = hash_password("correct-horse")
        assert verify_password("wrong-horse", h) is False

    def test_different_hashes_for_same_password(self):
        """bcrypt generates unique salt each time."""
        h1 = hash_password("same-pw")
        h2 = hash_password("same-pw")
        assert h1 != h2
        assert verify_password("same-pw", h1) is True
        assert verify_password("same-pw", h2) is True

    def test_reject_empty_password(self):
        h = hash_password("abc123")
        assert verify_password("", h) is False


# ═══════════════════════════════════════════════════════════════
# Unit Tests: JWT Token
# ═══════════════════════════════════════════════════════════════

class TestJWTToken:
    def test_create_and_decode(self):
        user = {"username": "admin", "role": "admin", "display_name": "管理员"}
        token = create_token(user)
        payload = decode_token(token)
        assert payload["sub"] == "admin"
        assert payload["role"] == "admin"
        assert payload["display"] == "管理员"

    def test_token_has_expiry(self):
        user = {"username": "test", "role": "viewer", "display_name": "测试"}
        token = create_token(user)
        payload = decode_token(token)
        assert "exp" in payload
        assert "iat" in payload
        # Should expire in the future
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        assert payload["exp"] > now


# ═══════════════════════════════════════════════════════════════
# Integration Tests: Auth Endpoints (via FastAPI TestClient)
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset rate-limiter state between tests to avoid cross-test contamination."""
    import dashboard.auth as auth_mod
    auth_mod._rate_store.clear()
    auth_mod._block_store.clear()
    yield
    auth_mod._rate_store.clear()
    auth_mod._block_store.clear()


@pytest.fixture
def client(monkeypatch):
    """FastAPI TestClient with all DB/user patches applied.

    Mocks at the dashboard.db level because the auth route handler imports
    user functions inside the function body (not at module level).

    IMPORTANT: Clears app.dependency_overrides to ensure the REAL auth
    dependency runs (other test modules may have overridden it).
    """
    from fastapi.testclient import TestClient
    import dashboard.app as app_mod

    # Clear any dependency overrides set by other test modules so the
    # REAL get_current_user dependency is active for auth tests.
    app_mod.app.dependency_overrides.clear()

    # Patch DB functions at the source (dashboard.db) since they're imported
    # inside route handlers at call time
    monkeypatch.setattr("dashboard.db.user_get_by_username", _mock_user_get)
    monkeypatch.setattr("dashboard.db.user_update_last_login", _mock_user_update_login)
    monkeypatch.setattr("dashboard.db.user_change_password", _mock_user_change_pw)

    # Patch app-level imports
    monkeypatch.setattr(app_mod, "user_count", MagicMock(return_value=1))
    monkeypatch.setattr(app_mod, "user_create", MagicMock())
    monkeypatch.setattr(app_mod, "init_db", MagicMock())
    monkeypatch.setattr(app_mod, "is_seeded", MagicMock(return_value=True))
    monkeypatch.setattr(app_mod, "seed_all", MagicMock())
    monkeypatch.setattr(app_mod, "get_secret_key_warning", MagicMock(return_value=None))
    monkeypatch.setattr(app_mod, "metrics_get_all", MagicMock(return_value=[]))
    monkeypatch.setattr(app_mod, "signals_get_latest", MagicMock(return_value=None))
    monkeypatch.setattr(app_mod, "kb_get", MagicMock(return_value=None))
    monkeypatch.setattr(app_mod, "nav_get_all", MagicMock(
        return_value={"dates": [], "series": {}, "drawdowns": {}}))
    monkeypatch.setattr(app_mod, "nav_has_data", MagicMock(return_value=False))

    with TestClient(app_mod.app) as tc:
        yield tc

    # Restore dependency overrides if any test module needs them later
    app_mod.app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    """Return a valid Authorization header for the default admin user."""
    token = create_token({
        "username": "admin",
        "role": "admin",
        "display_name": "管理员",
    })
    return {"Authorization": f"Bearer {token}"}


class TestAuthLogin:
    def test_login_success(self, client):
        """Valid credentials should return access_token."""
        pw = "correct-password"
        _FAKE_USER["password_hash"] = hash_password(pw)
        _mock_user_get.return_value = _FAKE_USER

        resp = client.post("/api/auth/login", json={
            "username": "admin", "password": pw,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["user"]["username"] == "admin"
        # Verify the returned token is valid
        payload = decode_token(data["access_token"])
        assert payload["sub"] == "admin"

    def test_login_wrong_password(self, client):
        """Wrong password should return 401."""
        _FAKE_USER["password_hash"] = hash_password("correct")
        _mock_user_get.return_value = _FAKE_USER

        resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "wrong-password",
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        """Non-existent user should return 401."""
        _mock_user_get.return_value = None

        resp = client.post("/api/auth/login", json={
            "username": "nobody", "password": "anything",
        })
        assert resp.status_code == 401

    def test_login_disabled_user(self, client):
        """Disabled user should return 401."""
        disabled_user = dict(_FAKE_USER)
        disabled_user["is_active"] = 0
        disabled_user["password_hash"] = hash_password("pw")
        _mock_user_get.return_value = disabled_user

        resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "pw",
        })
        assert resp.status_code == 401

    def test_login_empty_fields(self, client):
        """Empty username or password should return 400."""
        resp = client.post("/api/auth/login", json={
            "username": "", "password": "something",
        })
        assert resp.status_code == 400

    def test_login_rate_limit(self, client):
        """After 5 failures, 6th should return 429."""
        _FAKE_USER["password_hash"] = hash_password("correct")
        _mock_user_get.return_value = _FAKE_USER

        # 5 failed attempts
        for _ in range(5):
            resp = client.post("/api/auth/login", json={
                "username": "admin", "password": "wrong",
            })
            assert resp.status_code == 401

        # 6th should be rate-limited
        resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "wrong",
        })
        assert resp.status_code == 429
        assert "秒" in resp.json()["detail"]


class TestAuthLogout:
    def test_logout_returns_ok(self, client, auth_headers):
        resp = client.post("/api/auth/logout", headers=auth_headers)
        assert resp.status_code == 200


class TestAuthMe:
    def test_me_returns_user_info(self, client, auth_headers):
        resp = client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "admin"

    def test_me_without_token_returns_401(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401


class TestAuthChangePassword:
    def test_change_password_success(self, client, auth_headers):
        """Valid old password should allow change."""
        pw = "old-password"
        _FAKE_USER["password_hash"] = hash_password(pw)
        _mock_user_get.return_value = _FAKE_USER
        _mock_user_change_pw.reset_mock()

        resp = client.post("/api/auth/change-password", json={
            "old_password": pw, "new_password": "new-password123",
        }, headers=auth_headers)
        assert resp.status_code == 200

    def test_change_password_wrong_old(self, client, auth_headers):
        """Wrong old password should return 400."""
        _FAKE_USER["password_hash"] = hash_password("correct-old")
        _mock_user_get.return_value = _FAKE_USER

        resp = client.post("/api/auth/change-password", json={
            "old_password": "wrong-old", "new_password": "new-pw",
        }, headers=auth_headers)
        assert resp.status_code == 400

    def test_change_password_short_new(self, client, auth_headers):
        """New password < 6 chars should return 400."""
        resp = client.post("/api/auth/change-password", json={
            "old_password": "anything", "new_password": "12345",
        }, headers=auth_headers)
        assert resp.status_code == 400

    def test_change_password_without_token(self, client):
        resp = client.post("/api/auth/change-password", json={
            "old_password": "a", "new_password": "b",
        })
        assert resp.status_code == 401


class TestProtectedRoutes:
    def test_strategies_without_token_returns_401(self, client):
        resp = client.get("/api/strategies")
        assert resp.status_code == 401

    def test_strategies_with_valid_token(self, client, auth_headers):
        resp = client.get("/api/strategies", headers=auth_headers)
        # Should be 200 (not 401) — metrics are mocked
        assert resp.status_code == 200

    def test_strategies_with_invalid_token(self, client):
        resp = client.get("/api/strategies", headers={
            "Authorization": "Bearer invalid.token.here",
        })
        assert resp.status_code == 401

    def test_strategies_with_expired_token(self, client):
        """Token with past expiry should return 401."""
        import jwt as _jwt
        import os
        import datetime
        secret = os.environ.get("DASHBOARD_SECRET_KEY", "")
        if not secret:
            from dashboard.auth import _SECRET_KEY
            secret = _SECRET_KEY
        expired = _jwt.encode({
            "sub": "admin", "role": "admin", "display": "管理员",
            "iat": datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc),
            "exp": datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc),
        }, secret, algorithm="HS256")
        resp = client.get("/api/strategies", headers={
            "Authorization": f"Bearer {expired}",
        })
        assert resp.status_code == 401
