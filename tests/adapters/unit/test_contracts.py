from __future__ import annotations

import pytest
from pydantic import ValidationError

from media_bridge_adapters.contracts import PreUpstreamRequest, PreUpstreamResult


def test_pre_upstream_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        PreUpstreamRequest.model_validate(
            {
                "contract_version": "media-bridge-pre-upstream/v1",
                "request_id": "req_123",
                "wire_format": "openai-responses",
                "provider": "openai",
                "target_model": "text-model",
                "body": {"model": "text-model", "input": "hello"},
                "unexpected": True,
            }
        )


def test_pre_upstream_result_requires_blocked_body_to_be_absent() -> None:
    with pytest.raises(ValidationError):
        PreUpstreamResult.model_validate(
            {
                "status": "blocked",
                "provider": "openai",
                "target_model": "text-model",
                "capability": None,
                "body": {"input": "must not escape"},
                "original_media_removed": False,
                "input_digest": None,
                "output_digest": None,
                "decision_token": None,
                "error": {"code": "policy_denied", "message": "Request blocked."},
            }
        )
