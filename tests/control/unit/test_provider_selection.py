import pytest

from media_bridge_gateway.provider_selection import (
    ProviderRouteCandidate,
    ProviderSelectionError,
    select_provider,
)


def test_selection_skips_disabled_unhealthy_and_incapable_candidates() -> None:
    selected = select_provider(
        [
            ProviderRouteCandidate("disabled", False, frozenset({"text"})),
            ProviderRouteCandidate("unhealthy", True, frozenset({"text"}), healthy=False),
            ProviderRouteCandidate("vision-only", True, frozenset({"image"})),
            ProviderRouteCandidate("ready", True, frozenset({"text"}), priority=2),
        ],
        required_capability="text",
    )
    assert selected.provider_id == "ready"


def test_cost_strategy_selects_lowest_cost_then_priority() -> None:
    selected = select_provider(
        [
            ProviderRouteCandidate("expensive", True, frozenset({"text"}), estimated_cost=2),
            ProviderRouteCandidate("cheap", True, frozenset({"text"}), estimated_cost=1),
        ],
        required_capability="text",
        strategy="cost",
    )
    assert selected.provider_id == "cheap"


def test_selection_fails_closed_when_no_candidate_is_eligible() -> None:
    with pytest.raises(ProviderSelectionError, match="provider_route_unavailable"):
        select_provider([], required_capability="text")
