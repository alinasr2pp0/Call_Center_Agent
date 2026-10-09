"""Password hashing (PBKDF2-SHA256, stdlib), JWT helpers and a tiny login rate limiter."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import jwt  # PyJWT

from app.config import settings

_ITERATIONS = 310_000
_SCHEME = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return "$".join([
        _SCHEME, str(_ITERATIONS),
        base64.b64encode(salt).decode("ascii"), base64.b64encode(digest).decode("ascii"),
    ])


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_b64, digest_b64 = stored.split("$")
        if scheme != _SCHEME:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# A fixed, valid hash used to burn the same CPU time when the username does not exist
# (prevents username enumeration through response timing).
_DUMMY_HASH = hash_password(secrets.token_urlsafe(12))


def burn_password_check(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def create_access_token(subject: str, kind: str, extra: Optional[dict] = None,
                        expires_minutes: Optional[int] = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "kind": kind,  # "staff" | "customer"
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.PyJWTError:
        return None


def sign_value(value: str) -> str:
    """HMAC signature used to protect public webhook URLs from forgery."""
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def verify_signature(value: str, signature: str) -> bool:
    return hmac.compare_digest(sign_value(value), signature or "")


class LoginRateLimiter:
    """Counts failed logins per key inside a sliding window."""

    def __init__(self, max_attempts: int, window_seconds: int):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._lock = threading.Lock()
        self._failures: Dict[str, List[float]] = {}

    def _prune(self, key: str, now: float) -> List[float]:
        recent = [t for t in self._failures.get(key, []) if now - t < self.window]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._prune(key, time.monotonic())) >= self.max_attempts

    def fail(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._prune(key, now)
            self._failures.setdefault(key, []).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


login_limiter = LoginRateLimiter(settings.LOGIN_MAX_ATTEMPTS, settings.LOGIN_WINDOW_SECONDS)
