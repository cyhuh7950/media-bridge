"""Deterministic, fail-closed selection for managed Provider candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RoutingStrategy = Literal["priority", "fallback", "health", "cost"]


class ProviderSelectionError(RuntimeError):
    """Raised when no eligible Provider can satisfy a route."""


@dataclass(frozen=True, slots=True)
class ProviderRouteCandidate:
    provider_id: str
    enabled: bool
    capabilities: frozenset[str]
    priority: int = 0
    healthy: bool = True
    estimated_cost: float = 0.0


def select_provider(
    candidates: list[ProviderRouteCandidate],
    *,
    required_capability: str,
    strategy: RoutingStrategy = "priority",
) -> ProviderRouteCandidate:
    """Select one enabled, capable, healthy candidate without fallback ambiguity."""

    eligible = [
        candidate
        for candidate in candidates
        if candidate.enabled
        and candidate.healthy
        and required_capability in candidate.capabilities
    ]
    if not eligible:
        raise ProviderSelectionError("provider_route_unavailable")
    if strategy == "cost":
        return min(
            eligible,
            key=lambda item: (item.estimated_cost, item.priority, item.provider_id),
        )
    if strategy == "health":
        return min(eligible, key=lambda item: (not item.healthy, item.priority, item.provider_id))
    return min(eligible, key=lambda item: (item.priority, item.provider_id))
