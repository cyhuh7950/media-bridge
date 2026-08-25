from __future__ import annotations

from typing import Any

import pytest

from media_bridge.contracts import PrepareForModelResult
from media_bridge_adapters.contracts import PreUpstreamRequest
from media_bridge_adapters.service import PreUpstreamService
from tests.gateway.helpers import image_uri


class RecordingGateway:
    def __init__(self, result: PrepareForModelResult) -> None:
        self.result = result
        self.payloads: list[dict[str, Any]] = []

    async def prepare(self, payload: dict[str, Any]) -> PrepareForModelResult:
        self.payloads.append(payload)
        return self.result


def request_with_image(target: str = "text-model") -> PreUpstreamRequest:
    return PreUpstreamRequest(
        contract_version="media-bridge-pre-upstream/v1",
        request_id="req_parent",
        wire_format="openai-responses",
        provider="openai",
        target_model=target,
        body={
            "model": "selector-before-route",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "safe history"}],
                },
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "explain"},
                        {"type": "input_image", "image_url": image_uri()},
                    ],
                },
            ],
            "previous_response_id": "resp_parent",
            "stream": True,
        },
    )


@pytest.mark.asyncio
async def test_non_vision_conversion_rebuilds_text_only_current_input() -> None:
    gateway = RecordingGateway(
        PrepareForModelResult(
            action="converted",
            target_model="text-model",
            contains_media=True,
            contains_image=True,
            contains_pdf=False,
            target_supports_vision=False,
            sanitized_text="explain\n\n[OCR]\nERROR 104",
            original_image_removed=True,
            error=None,
        )
    )
    service = PreUpstreamService(gateway=gateway, decision_secret=b"d" * 32)

    result = await service.prepare(request_with_image())

    assert result.status == "prepared"
    assert result.capability == "non_vision"
    assert result.original_media_removed is True
    assert result.body == {
        "model": "text-model",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "safe history"}],
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "explain\n\n[OCR]\nERROR 104"}],
            },
        ],
        "stream": True,
    }
    assert "data:image" not in str(result.body)
    assert result.input_digest and result.output_digest and result.decision_token
    assert gateway.payloads[0]["target"] == {"registry_id": "text-model"}


@pytest.mark.asyncio
async def test_verified_vision_passthrough_preserves_original_body() -> None:
    gateway = RecordingGateway(
        PrepareForModelResult(
            action="passthrough",
            target_model="vision-model",
            contains_media=True,
            contains_image=True,
            contains_pdf=False,
            target_supports_vision=True,
            sanitized_text=None,
            original_image_removed=False,
            error=None,
        )
    )
    service = PreUpstreamService(gateway=gateway, decision_secret=b"d" * 32)
    request = request_with_image("vision-model")

    result = await service.prepare(request)

    assert result.status == "unchanged"
    assert result.capability == "vision"
    assert result.body == {
        "model": "vision-model",
        "input": request.body["input"],
        "stream": True,
    }
    assert "previous_response_id" not in result.body


@pytest.mark.asyncio
async def test_target_mismatch_blocks_without_returning_a_body() -> None:
    gateway = RecordingGateway(
        PrepareForModelResult(
            action="passthrough",
            target_model="different-model",
            contains_media=True,
            contains_image=True,
            contains_pdf=False,
            target_supports_vision=True,
            sanitized_text=None,
            original_image_removed=False,
            error=None,
        )
    )
    service = PreUpstreamService(gateway=gateway, decision_secret=b"d" * 32)

    result = await service.prepare(request_with_image())

    assert result.status == "blocked"
    assert result.body is None
    assert result.error is not None
    assert result.error.code == "target_mismatch"
    assert result.error.message == "Prepared target did not match the resolved target."
