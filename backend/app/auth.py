"""JWT authentication for SaaS mode."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

_bearer = HTTPBearer(auto_error=False)

# Local-mode sentinel user (Mac app, no auth)
LOCAL_USER_ID = 1


def _hash_password(password: str) -> str:
    salt = settings.auth_password_salt.encode()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return digest.hex()


def verify_password(password: str, password_hash: str) -> bool:
    return hmac.compare_digest(_hash_password(password), password_hash)


def hash_password(password: str) -> str:
    return _hash_password(password)


def _jwt_secret() -> bytes:
    secret = settings.jwt_secret or settings.auth_password_salt
    return secret.encode()


def create_access_token(user_id: int, email: str, *, days: int | None = None) -> str:
    import base64
    import json

    ttl = days if days is not None else settings.jwt_expire_days
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": int((datetime.now(timezone.utc) + timedelta(days=ttl)).timestamp()),
        "iat": int(datetime.now(timezone.utc).timestamp()),
    }
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signing_input = f"{header}.{body}".encode()
    sig = hmac.new(_jwt_secret(), signing_input, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{header}.{body}.{sig_b64}"


def decode_access_token(token: str) -> dict[str, Any]:
    import base64
    import json

    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="Invalid token")
    header_b64, body_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{body_b64}".encode()
    expected = hmac.new(_jwt_secret(), signing_input, hashlib.sha256).digest()
    pad = "=" * (-len(sig_b64) % 4)
    try:
        actual = base64.urlsafe_b64decode(sig_b64 + pad)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    if not hmac.compare_digest(expected, actual):
        raise HTTPException(status_code=401, detail="Invalid token")
    pad = "=" * (-len(body_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(body_b64 + pad))
    if payload.get("exp", 0) < int(datetime.now(timezone.utc).timestamp()):
        raise HTTPException(status_code=401, detail="Token expired")
    return payload


def generate_magic_token() -> str:
    return secrets.token_urlsafe(32)


async def get_current_user_id(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> int:
    if not settings.saas_mode:
        return LOCAL_USER_ID
    if creds and creds.credentials:
        payload = decode_access_token(creds.credentials)
        return int(payload["sub"])
    # Optional: allow session cookie for web app
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        payload = decode_access_token(token)
        return int(payload["sub"])
    raise HTTPException(status_code=401, detail="Authentication required")


async def get_optional_user_id(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> int | None:
    if not settings.saas_mode:
        return LOCAL_USER_ID
    try:
        return await get_current_user_id(request, creds)
    except HTTPException:
        return None
