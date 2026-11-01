"""Demo-grade authentication and role enforcement.

* Passwords are hashed with PBKDF2-HMAC-SHA256 (Python standard library).
* Login returns a short-lived HMAC-signed bearer token: base64(payload).signature.
* Every protected endpoint resolves the user from the token on the SERVER and checks
  the role there. The frontend's tabs are convenience only, never authorisation.

This is intentionally simple and readable. A production system would use a vetted
identity provider, refresh tokens, revocation and rate limiting (see docs/limitations.md).
"""
import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User

_PBKDF2_ROUNDS = 200_000
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2${_PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds))
    return hmac.compare_digest(digest.hex(), digest_hex)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token(user: User) -> str:
    payload = {"uid": user.id, "role": user.role, "exp": int(time.time()) + get_settings().token_ttl_minutes * 60}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(get_settings().app_secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(sig)}"


def read_token(token: str) -> dict | None:
    try:
        body, sig = token.split(".")
    except ValueError:
        return None
    expected = hmac.new(get_settings().app_secret.encode(), body.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64(expected), sig):
        return None
    payload = json.loads(_unb64(body))
    if payload.get("exp", 0) < time.time():
        return None
    return payload


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required.")
    payload = read_token(creds.credentials)
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or invalid. Please sign in again.")
    user = db.get(User, payload["uid"])
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account no longer exists.")
    return user


def require_role(*roles: str):
    """Dependency factory: `Depends(require_role("admin"))`."""

    def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"This action needs one of these roles: {', '.join(roles)}.")
        return user

    return checker
