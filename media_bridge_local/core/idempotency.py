"""Bounded, digest-bound idempotency for v2 transformations."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


class IdempotencyConflictError(ValueError):
    """The same key was reused for a different canonical request."""


IdempotencyConflict = IdempotencyConflictError


@dataclass(frozen=True, slots=True)
class _Entry:
    fingerprint: str
    value: object
    expires_at: float


class IdempotencyStore:
    """Serialize same-key work and cache metadata-only transformation results."""

    def __init__(self, *, ttl_seconds: int = 300, max_entries: int = 1024) -> None:
        if ttl_seconds < 1 or ttl_seconds > 86_400:
            raise ValueError("idempotency ttl is outside the allowed range")
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._entries: dict[str, _Entry] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()

    def run(self, key: str, fingerprint: str, operation: Callable[[], T]) -> T:
        if not key or not fingerprint:
            raise ValueError("idempotency key and fingerprint are required")
        with self._lock:
            self._purge_locked()
            entry = self._entries.get(key)
            if entry is not None and entry.fingerprint != fingerprint:
                raise IdempotencyConflict("idempotency fingerprint mismatch")
            key_lock = self._locks.setdefault(key, threading.Lock())
        with key_lock:
            with self._lock:
                self._purge_locked()
                entry = self._entries.get(key)
                if entry is not None:
                    if entry.fingerprint != fingerprint:
                        raise IdempotencyConflict("idempotency fingerprint mismatch")
                    return entry.value  # type: ignore[return-value]
            value = operation()
            with self._lock:
                self._entries[key] = _Entry(
                    fingerprint,
                    value,
                    time.monotonic() + self._ttl_seconds,
                )
                self._trim_locked()
            return value

    def _purge_locked(self) -> None:
        now = time.monotonic()
        for key in list(self._entries):
            if self._entries[key].expires_at <= now:
                del self._entries[key]

    def _trim_locked(self) -> None:
        while len(self._entries) > self._max_entries:
            oldest = min(self._entries, key=lambda key: self._entries[key].expires_at)
            del self._entries[oldest]
