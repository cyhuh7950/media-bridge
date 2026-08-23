from __future__ import annotations

from datetime import UTC, datetime, timedelta

from media_bridge_control.security import LoginRateLimiter, PasswordHasher


def test_password_hash_uses_argon2_and_unique_salts() -> None:
    passwords = PasswordHasher()

    first = passwords.hash("correct horse battery staple")
    second = passwords.hash("correct horse battery staple")

    assert first.startswith("$argon2id$")
    assert second.startswith("$argon2id$")
    assert first != second
    assert "correct horse battery staple" not in first
    assert passwords.verify(first, "correct horse battery staple") is True
    assert passwords.verify(first, "wrong password") is False


def test_login_rate_limiter_is_bounded_and_expires_attempts() -> None:
    limiter = LoginRateLimiter(limit=3, window=timedelta(minutes=1), max_keys=10)
    now = datetime(2026, 8, 24, tzinfo=UTC)

    assert limiter.allow("127.0.0.1:admin", now=now) is True
    limiter.record_failure("127.0.0.1:admin", now=now)
    limiter.record_failure("127.0.0.1:admin", now=now)
    limiter.record_failure("127.0.0.1:admin", now=now)
    assert limiter.allow("127.0.0.1:admin", now=now) is False
    assert limiter.allow("127.0.0.1:other", now=now) is True
    assert limiter.allow("127.0.0.1:admin", now=now + timedelta(seconds=61)) is True
