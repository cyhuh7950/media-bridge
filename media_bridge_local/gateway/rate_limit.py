"""Bounded credential-and-route token bucket for Data Plane endpoints."""

from __future__ import annotations

import math
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

_SELECTOR = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_ROUTE = re.compile(r"^/[a-z0-9/_-]{1,127}$")


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float
    last_seen_at: float


class CredentialRouteRateLimiter:
    """Fail closed at capacity instead of evicting active security state."""

    def __init__(
        self,
        *,
        capacity: int,
        refill_per_second: float,
        max_keys: int,
        idle_ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            capacity < 1
            or not math.isfinite(refill_per_second)
            or refill_per_second <= 0
            or max_keys < 1
            or not math.isfinite(idle_ttl_seconds)
            or idle_ttl_seconds <= 0
        ):
            raise ValueError("rate limiter settings must be positive and finite")
        self._capacity = float(capacity)
        self._refill_per_second = refill_per_second
        self._max_keys = max_keys
        self._idle_ttl_seconds = idle_ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: OrderedDict[tuple[str, str], _Bucket] = OrderedDict()

    @property
    def key_count(self) -> int:
        with self._lock:
            return len(self._buckets)

    def allow(self, selector: str, route: str, *, cost: float = 1.0) -> bool:
        if (
            not _SELECTOR.fullmatch(selector)
            or not _ROUTE.fullmatch(route)
            or not math.isfinite(cost)
            or cost <= 0
            or cost > self._capacity
        ):
            return False
        now = self._clock()
        if not math.isfinite(now):
            return False
        key = (selector, route)
        with self._lock:
            self._purge_idle(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self._max_keys:
                    return False
                bucket = _Bucket(
                    tokens=self._capacity,
                    updated_at=now,
                    last_seen_at=now,
                )
                self._buckets[key] = bucket
            else:
                elapsed = max(0.0, now - bucket.updated_at)
                bucket.tokens = min(
                    self._capacity,
                    bucket.tokens + elapsed * self._refill_per_second,
                )
                bucket.updated_at = now
                bucket.last_seen_at = now
                self._buckets.move_to_end(key)
            if bucket.tokens < cost:
                return False
            bucket.tokens -= cost
            return True

    def _purge_idle(self, now: float) -> None:
        cutoff = now - self._idle_ttl_seconds
        expired = [key for key, bucket in self._buckets.items() if bucket.last_seen_at <= cutoff]
        for key in expired:
            self._buckets.pop(key, None)
