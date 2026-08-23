"""Password, opaque-token, CSRF, and login throttling primitives."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from argon2 import PasswordHasher as Argon2PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


class PasswordHasher:
    """Argon2id password hashing with a fresh salt per call."""

    def __init__(self) -> None:
        self._hasher = Argon2PasswordHasher()

    def hash(self, password: str) -> str:
        if len(password) < 12 or len(password) > 1_024:
            raise ValueError("password length is outside the allowed range")
        return self._hasher.hash(password)

    def verify(self, encoded: str, password: str) -> bool:
        try:
            return self._hasher.verify(encoded, password)
        except (InvalidHashError, VerificationError):
            return False


@dataclass(frozen=True, slots=True)
class OpaqueToken:
    raw: str
    selector: str
    digest: str


class SecurityContext:
    """Domain-separated HMAC digests for high-entropy transient values."""

    def __init__(self, *, pepper: bytes) -> None:
        if len(pepper) < 32:
            raise ValueError("security pepper must contain at least 32 bytes")
        self._pepper = pepper
        self.passwords = PasswordHasher()

    def digest(self, value: str, *, purpose: str) -> str:
        payload = f"{purpose}\0{value}".encode()
        return hmac.new(self._pepper, payload, hashlib.sha256).hexdigest()

    def issue_token(self, *, prefix: str, purpose: str) -> OpaqueToken:
        selector = secrets.token_urlsafe(12)
        secret = secrets.token_urlsafe(32)
        raw = f"{prefix}_{selector}.{secret}"
        return OpaqueToken(
            raw=raw,
            selector=selector,
            digest=self.digest(raw, purpose=purpose),
        )

    def selector(self, raw: str, *, prefix: str) -> str | None:
        marker = f"{prefix}_"
        if not raw.startswith(marker) or "." not in raw:
            return None
        selector, secret = raw[len(marker) :].split(".", 1)
        if not selector or not secret or len(selector) > 32 or len(secret) > 64:
            return None
        return selector

    def matches(self, raw: str, expected_digest: str, *, purpose: str) -> bool:
        candidate = self.digest(raw, purpose=purpose)
        return hmac.compare_digest(candidate, expected_digest)


class LoginRateLimiter:
    """Small bounded in-memory limiter for login failures."""

    def __init__(self, *, limit: int, window: timedelta, max_keys: int = 10_000) -> None:
        if limit < 1 or window <= timedelta(0) or max_keys < 1:
            raise ValueError("login limiter settings must be positive")
        self._limit = limit
        self._window = window
        self._max_keys = max_keys
        self._attempts: OrderedDict[str, deque[datetime]] = OrderedDict()

    def _active(self, key: str, *, now: datetime) -> deque[datetime]:
        attempts = self._attempts.get(key)
        if attempts is None:
            if len(self._attempts) >= self._max_keys:
                self._attempts.popitem(last=False)
            attempts = deque()
            self._attempts[key] = attempts
        cutoff = now - self._window
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        self._attempts.move_to_end(key)
        return attempts

    def allow(self, key: str, *, now: datetime) -> bool:
        return len(self._active(key, now=now)) < self._limit

    def record_failure(self, key: str, *, now: datetime) -> None:
        self._active(key, now=now).append(now)

    def clear(self, key: str) -> None:
        self._attempts.pop(key, None)
