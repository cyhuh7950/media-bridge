"""Hop and external-wire guards for v2 gateway interoperability."""

from __future__ import annotations

from typing import Any

from media_bridge.contracts_v2 import HopMetadata, InteropV2Result, provider_call_allowed


class HopGuardError(ValueError):
    """Raised when a request would revisit or exceed a gateway hop budget."""


def advance_hop(hop: HopMetadata, *, gateway_id: str) -> HopMetadata:
    if gateway_id in hop.visited_gateways:
        raise HopGuardError("gateway hop loop detected")
    if len(hop.visited_gateways) >= hop.max_hops:
        raise HopGuardError("gateway hop limit exceeded")
    return HopMetadata(
        hop_id=hop.hop_id,
        visited_gateways=[*hop.visited_gateways, gateway_id],
        max_hops=hop.max_hops,
    )


def build_external_provider_messages(result: InteropV2Result) -> list[dict[str, Any]]:
    """Expose only sanitized messages; internal provenance never reaches a provider."""

    if not provider_call_allowed(result):
        raise HopGuardError("result is not authorized for provider execution")
    messages: list[dict[str, Any]] = []
    for message in result.sanitized_messages:
        if any(key in message for key in ("image", "image_url", "file_data", "asset_id")):
            raise HopGuardError("original media reference remains in provider wire")
        messages.append(
            {
                key: value
                for key, value in message.items()
                if not key.startswith("_media_bridge")
                and key not in {"provenance", "prepared_marker", "transformations"}
            }
        )
    return messages
