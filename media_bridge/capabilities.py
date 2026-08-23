"""Exact model capability registry with explicit stale handling."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class CapabilityState(StrEnum):
    VISION = "vision"
    NON_VISION = "non_vision"
    UNKNOWN = "unknown"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class ModelCapability:
    model_id: str
    input_modalities: set[str]
    expires_at: datetime

    def supports_all(self, modalities: frozenset[str]) -> bool:
        return modalities.issubset(self.input_modalities)

    def is_stale(self, now: datetime | None = None) -> bool:
        checked_at = now or datetime.now(UTC)
        return self.expires_at <= checked_at


@dataclass(frozen=True, slots=True)
class CapabilityResolution:
    state: CapabilityState
    capability: ModelCapability | None


class CapabilityRegistry:
    """Resolve only operator-registered exact model identifiers."""

    def __init__(self, capabilities: list[ModelCapability], version: str) -> None:
        self._capabilities = {item.model_id: item for item in capabilities}
        self.version = version

    def resolve(self, model_id: str, now: datetime | None = None) -> CapabilityResolution:
        capability = self._capabilities.get(model_id)
        if capability is None:
            return CapabilityResolution(CapabilityState.UNKNOWN, None)
        if capability.is_stale(now):
            return CapabilityResolution(CapabilityState.STALE, capability)
        if capability.input_modalities.intersection({"image", "pdf"}):
            return CapabilityResolution(CapabilityState.VISION, capability)
        return CapabilityResolution(CapabilityState.NON_VISION, capability)
