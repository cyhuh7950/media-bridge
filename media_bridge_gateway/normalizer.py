"""Gateway normalization compatibility boundary for OpenAI Responses v1."""

from __future__ import annotations

import hashlib
import json

from media_bridge.openai_responses import (
    NormalizedResponsesRequest,
    ResponsesNormalizationError,
    normalize_responses_request,
)


def digest_gateway_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "NormalizedResponsesRequest",
    "ResponsesNormalizationError",
    "digest_gateway_payload",
    "normalize_responses_request",
]
