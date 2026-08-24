"""Bodyless operational events for the product Gateway."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol

_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9./:_-]{0,127}$")
LatencyBucket = Literal["lt_100ms", "lt_500ms", "lt_1s", "lt_5s", "gte_5s"]
SizeBucket = Literal["lt_2kb", "lt_64kb", "lt_1mb", "gte_1mb"]


@dataclass(frozen=True, slots=True)
class GatewayEvent:
    request_id: str
    event_type: str
    model_id: str | None
    policy_version: int | None
    status_code: str
    latency_bucket: LatencyBucket
    size_bucket: SizeBucket

    def __post_init__(self) -> None:
        if not self.request_id or len(self.request_id) > 64:
            raise ValueError("Gateway event request identifier is invalid")
        if _SAFE_CODE.fullmatch(self.event_type) is None:
            raise ValueError("Gateway event type is invalid")
        if self.model_id is not None and _MODEL_ID.fullmatch(self.model_id) is None:
            raise ValueError("Gateway event model identifier is invalid")
        if self.policy_version is not None and self.policy_version < 0:
            raise ValueError("Gateway event policy version is invalid")
        if _SAFE_CODE.fullmatch(self.status_code) is None:
            raise ValueError("Gateway event status code is invalid")


class GatewayEventSink(Protocol):
    def emit(self, event: GatewayEvent) -> None: ...


class NullGatewayEventSink:
    def emit(self, event: GatewayEvent) -> None:
        del event


def latency_bucket(elapsed_seconds: float) -> LatencyBucket:
    if elapsed_seconds < 0.1:
        return "lt_100ms"
    if elapsed_seconds < 0.5:
        return "lt_500ms"
    if elapsed_seconds < 1:
        return "lt_1s"
    if elapsed_seconds < 5:
        return "lt_5s"
    return "gte_5s"


def size_bucket(size_bytes: int) -> SizeBucket:
    if size_bytes < 2 * 1024:
        return "lt_2kb"
    if size_bytes < 64 * 1024:
        return "lt_64kb"
    if size_bytes < 1024 * 1024:
        return "lt_1mb"
    return "gte_1mb"


def emit_safely(sink: GatewayEventSink, event: GatewayEvent) -> bool:
    """Keep observability failure from corrupting an already-issued model result."""

    try:
        sink.emit(event)
    except Exception:
        return False
    return True


__all__ = [
    "GatewayEvent",
    "GatewayEventSink",
    "NullGatewayEventSink",
    "emit_safely",
    "latency_bucket",
    "size_bucket",
]
