from __future__ import annotations

from media_bridge.omniroute_adapter import (
    GuardedOmniRouteAdapter as LegacyGuardedOmniRouteAdapter,
)
from media_bridge.omniroute_adapter import (
    digest_responses_payload as legacy_digest_responses_payload,
)
from media_bridge_adapters.omniroute.downstream import (
    GuardedOmniRouteAdapter,
    digest_responses_payload,
)
from media_bridge_adapters.registry import default_registry
from media_bridge_gateway.app import build_gateway_app


def test_legacy_omniroute_api_is_a_one_release_reexport() -> None:
    assert LegacyGuardedOmniRouteAdapter is GuardedOmniRouteAdapter
    assert legacy_digest_responses_payload is digest_responses_payload


def test_registry_removal_does_not_remove_generic_gateway_or_downstream() -> None:
    registry = default_registry()
    registry.unregister("omniroute")

    assert registry.adapter_ids() == ("opencodex",)
    assert GuardedOmniRouteAdapter is not None
    assert build_gateway_app is not None
