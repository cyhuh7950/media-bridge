"""OmniRoute name over the generic sealed Responses downstream."""

from __future__ import annotations

from typing import Any

from media_bridge_gateway.contracts import (
    DownstreamError,
    DownstreamGuardError,
    GatewayResponse,
    SealedGatewayRequest,
)
from media_bridge_gateway.downstream import GuardedResponsesDownstream
from media_bridge_gateway.normalizer import digest_gateway_payload

OmniRouteAdapterError = DownstreamError
OmniRouteGuardError = DownstreamGuardError
OmniRouteResponse = GatewayResponse
SealedResponsesRequest = SealedGatewayRequest


def digest_responses_payload(payload: object) -> str:
    return digest_gateway_payload(payload)


class GuardedOmniRouteAdapter(GuardedResponsesDownstream):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("api_key_env", "MEDIA_BRIDGE_OMNIROUTE_API_KEY")
        kwargs.setdefault("api_key_file_env", "MEDIA_BRIDGE_OMNIROUTE_API_KEY_FILE")
        kwargs.setdefault("error_prefix", "omniroute")
        super().__init__(**kwargs)


__all__ = [
    "GuardedOmniRouteAdapter",
    "OmniRouteAdapterError",
    "OmniRouteGuardError",
    "OmniRouteResponse",
    "SealedResponsesRequest",
    "digest_responses_payload",
]
