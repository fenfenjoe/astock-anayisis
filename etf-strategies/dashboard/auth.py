"""Dashboard 认证模块 — JWT + bcrypt + 登录限流.

本模块提供:
- 密码哈希/验证 (bcrypt)
- JWT 创建/解码 (PyJWT, HS256, 8h 过期)
- FastAPI Dependency: get_current_user (从 Bearer header 提取 token)
- 内存登录限流 (5次/5分钟 → 60s 封禁)
"""
import os
import secrets
import threading
import time
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import HTTPException, Request


# ── Password helpers ──

def hash_password(password: str) -> str:
    """Return bcrypt hash of *password*."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify *plain* against *hashed* bcrypt string."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ── Secret key (persisted to file so hot-reload doesn't invalidate tokens) ──
_KEY_FILE = Path(__file__).resolve().parent / "data" / ".secret_key"
_SECRET_KEY = os.environ.get("DASHBOARD_SECRET_KEY", "")
_SECRET_KEY_AUTO = False
if not _SECRET_KEY:
    if _KEY_FILE.exists():
        _SECRET_KEY = _KEY_FILE.read_text().strip()
    else:
        _SECRET_KEY = secrets.token_hex(32)
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEY_FILE.write_text(_SECRET_KEY)
        _SECRET_KEY_AUTO = True


def get_secret_key_warning() -> str | None:
    """Return a warning message if the secret key was auto-generated, else None."""
    if _SECRET_KEY_AUTO:
        return (
            "WARNING: DASHBOARD_SECRET_KEY not set — using auto-generated key.\n"
            "         Key persisted to data/.secret_key for consistency across restarts.\n"
            "         Set the env var for explicit control."
        )
    return None


# ── JWT helpers ──

ACCESS_TOKEN_EXPIRE_HOURS = 8


def create_token(user: dict) -> str:
    """Create a JWT access token for *user*.

    *user* must have keys: username, role, display_name.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user["username"],
        "role": user.get("role", "viewer"),
        "display": user.get("display_name", user["username"]),
        "iat": now,
        "exp": now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, _SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> dict:
    """Decode and verify a JWT token. Returns the payload dict.

    Raises HTTPException(401) on any failure (expired / invalid / tampered).
    """
    try:
        payload = jwt.decode(token, _SECRET_KEY, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token 已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token 无效，请重新登录")


# ── FastAPI Dependency ──

def get_current_user(request: Request) -> dict:
    """FastAPI dependency — extract & verify Bearer token from Authorization header.

    Returns user info dict: {username, role, display_name}.
    Raises HTTPException(401) if missing or invalid.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少认证 Token，请登录")

    token = auth_header[len("Bearer "):].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Token 为空，请登录")

    payload = decode_token(token)
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Token 格式无效")
    return {
        "username": username,
        "role": payload.get("role", "viewer"),
        "display_name": payload.get("display", username),
    }


# ── Login Rate Limiter (in-memory, thread-safe) ──

_RATE_LIMIT_WINDOW = 300   # 5 minutes
_RATE_LIMIT_MAX_FAILS = 5  # max failures in window
_RATE_LIMIT_BLOCK = 60     # block duration after exceeding (seconds)

# {ip: [fail_timestamps, ...]}
_rate_store: dict[str, list[float]] = defaultdict(list)
_block_store: dict[str, float] = {}  # {ip: blocked_until_timestamp}
_rate_lock = threading.Lock()


def _cleanup_rate_store(now: float) -> None:
    """Remove stale entries (IPs blocked more than 2x window ago)."""
    stale_cutoff = now - 2 * _RATE_LIMIT_WINDOW
    for ip in list(_block_store.keys()):
        if _block_store[ip] < stale_cutoff:
            _block_store.pop(ip, None)
            _rate_store.pop(ip, None)


def check_rate_limit(ip: str) -> None:
    """Check login rate limit for *ip*. Raises HTTPException(429) if blocked."""
    now = time.time()

    with _rate_lock:
        _cleanup_rate_store(now)

        # Check if currently blocked
        blocked_until = _block_store.get(ip)
        if blocked_until and now < blocked_until:
            remaining = int(blocked_until - now)
            raise HTTPException(
                status_code=429,
                detail=f"登录尝试过于频繁，请 {remaining} 秒后重试",
            )

        # Purge old entries
        cutoff = now - _RATE_LIMIT_WINDOW
        _rate_store[ip] = [t for t in _rate_store[ip] if t > cutoff]

        if len(_rate_store[ip]) >= _RATE_LIMIT_MAX_FAILS:
            _block_store[ip] = now + _RATE_LIMIT_BLOCK
            _rate_store.pop(ip, None)
            raise HTTPException(
                status_code=429,
                detail=f"登录失败次数过多，请 {_RATE_LIMIT_BLOCK} 秒后重试",
            )


def record_login_failure(ip: str) -> None:
    """Record a failed login attempt for *ip*."""
    with _rate_lock:
        _rate_store[ip].append(time.time())


def clear_rate_limit(ip: str) -> None:
    """Clear rate-limit state for *ip* after a successful login."""
    with _rate_lock:
        _rate_store.pop(ip, None)
        _block_store.pop(ip, None)
