from __future__ import annotations

import hashlib
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from media_bridge_adapters.app import build_adapter_app
from media_bridge_adapters.contracts import PreUpstreamRequest, PreUpstreamResult
from media_bridge_adapters.http_client import GatewayPrepareClient, GatewayPrepareError
from media_bridge_adapters.service import PreUpstreamService


class StaticGateway:
    def __init__(self, result: object) -> None:
        self.result = result

    async def prepare(self, _payload: dict[str, Any]) -> object:
        return self.result


def request(body: dict[str, Any] | None = None) -> PreUpstreamRequest:
    return PreUpstreamRequest(
        contract_version="media-bridge-pre-upstream/v1",
        request_id="req_branch",
        wire_format="openai-responses",
        provider="openai",
        target_model="text-model",
        body=body or {"model": "text-model", "input": "hello"},
    )


def gateway_result(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "action": "passthrough",
        "target_model": "text-model",
        "contains_media": False,
        "contains_image": False,
        "contains_pdf": False,
        "target_supports_vision": False,
        "sanitized_text": None,
        "original_image_removed": True,
        "error": None,
    }
    result.update(overrides)
    return result


@pytest.mark.parametrize(
    "payload",
    [
        {
            "status": "blocked",
            "provider": "openai",
            "target_model": "text-model",
            "capability": None,
            "body": None,
            "original_media_removed": True,
            "input_digest": None,
            "output_digest": None,
            "decision_token": None,
            "error": {"code": "policy_denied", "message": "blocked"},
        },
        {
            "status": "prepared",
            "provider": "openai",
            "target_model": "text-model",
            "capability": "non_vision",
            "body": {"input": "text"},
            "original_media_removed": False,
            "input_digest": "a" * 64,
            "output_digest": "b" * 64,
            "decision_token": "c" * 43,
            "error": None,
        },
    ],
)
def test_result_contract_rejects_false_safety_claims(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PreUpstreamResult.model_validate(payload)


@pytest.mark.asyncio
async def test_plain_text_is_bound_to_resolved_target_and_signed() -> None:
    service = PreUpstreamService(
        gateway=StaticGateway(gateway_result()),
        decision_secret=b"d" * 32,
    )

    result = await service.prepare(request())

    assert result.status == "unchanged"
    assert result.body == {"model": "text-model", "input": "hello"}
    assert result.original_media_removed is True
    assert result.decision_token is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "expected_code"),
    [
        (gateway_result(target_supports_vision=None), "pre_request_blocked"),
        (
            gateway_result(
                action="blocked",
                target_supports_vision=False,
                error={"code": "policy_denied", "message": "denied"},
            ),
            "policy_denied",
        ),
        (gateway_result(action="converted", sanitized_text=None), "sanitization_failed"),
        ({"unexpected": True}, "gateway_invalid_response"),
    ],
)
async def test_gateway_uncertainty_is_fail_closed(
    result: object,
    expected_code: str,
) -> None:
    service = PreUpstreamService(gateway=StaticGateway(result), decision_secret=b"d" * 32)

    decision = await service.prepare(request())

    assert decision.status == "blocked"
    assert decision.body is None
    assert decision.error is not None
    assert decision.error.code == expected_code


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"input": []},
        {"input": [{"role": "assistant", "content": "no user"}]},
        {
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": "data:image/png;base64,%%%",
                        }
                    ],
                }
            ]
        },
        {
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_image", "image_url": "http://example.com/a.png"}],
                }
            ]
        },
        {"input": "hello", "metadata": {"asset_id": "asset_hidden"}},
    ],
)
async def test_unsafe_or_ambiguous_input_is_rejected(body: dict[str, Any]) -> None:
    service = PreUpstreamService(
        gateway=StaticGateway(gateway_result()),
        decision_secret=b"d" * 32,
    )

    decision = await service.prepare(request(body))

    assert decision.status == "blocked"
    assert decision.body is None
    assert decision.error is not None
    assert decision.error.code == "invalid_request"


def test_constructor_and_client_configuration_reject_weak_boundaries() -> None:
    with pytest.raises(ValueError, match="at least 32"):
        PreUpstreamService(gateway=StaticGateway({}), decision_secret=b"short")
    with pytest.raises(ValueError, match="credential"):
        GatewayPrepareClient(base_url="https://bridge.example", credential="bad")
    with pytest.raises(ValueError, match="loopback"):
        GatewayPrepareClient(
            base_url="http://bridge.example",
            credential="mbc_test-only-credential",
        )
    with pytest.raises(ValueError, match="canonical"):
        GatewayPrepareClient(
            base_url="https://bridge.example/",
            credential="mbc_test-only-credential",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "max_bytes", "code"),
    [
        (httpx.Response(500), 512, "gateway_prepare_failed"),
        (
            httpx.Response(200, content=b"x" * 32, headers={"content-type": "application/json"}),
            16,
            "gateway_response_too_large",
        ),
        (httpx.Response(200, json={}), 512, "gateway_invalid_response"),
        (httpx.Response(200, text="not-json"), 512, "gateway_invalid_response"),
    ],
)
async def test_gateway_client_rejects_invalid_responses(
    response: httpx.Response,
    max_bytes: int,
    code: str,
) -> None:
    client = GatewayPrepareClient(
        base_url="http://127.0.0.1:8400",
        credential="mbc_test-only-credential",
        max_response_bytes=max_bytes,
        transport=httpx.MockTransport(lambda _request: response),
    )

    with pytest.raises(GatewayPrepareError, match=code):
        await client.prepare({"content": [{"type": "text", "text": "hello"}]})


@pytest.mark.asyncio
async def test_gateway_client_accepts_strict_prepare_response() -> None:
    response = httpx.Response(
        200,
        json=gateway_result(),
        headers={"content-type": "application/json"},
    )
    client = GatewayPrepareClient(
        base_url="http://localhost:8400",
        credential="mbc_test-only-credential",
        max_response_bytes=1024,
        transport=httpx.MockTransport(lambda _request: response),
    )

    result = await client.prepare({"content": [{"type": "text", "text": "hello"}]})

    assert result.action == "passthrough"


@pytest.mark.asyncio
async def test_http_boundary_rejects_content_type_size_and_invalid_json() -> None:
    credential = "mba_test-only-credential"
    headers = {"authorization": f"Bearer {credential}"}
    app = build_adapter_app(
        PreUpstreamService(
            gateway=StaticGateway(gateway_result()),
            decision_secret=b"d" * 32,
        ),
        credential_digest=hashlib.sha256(credential.encode()).hexdigest(),
        max_request_bytes=16,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        content_type = await client.post(
            "/adapter/v1/pre-upstream",
            content=b"{}",
            headers={**headers, "content-type": "text/plain"},
        )
        too_large = await client.post(
            "/adapter/v1/pre-upstream",
            content=b"{" + b"x" * 32,
            headers={**headers, "content-type": "application/json"},
        )

    assert content_type.status_code == 415
    assert too_large.status_code == 413


def test_http_boundary_rejects_invalid_configuration() -> None:
    service = PreUpstreamService(gateway=StaticGateway({}), decision_secret=b"d" * 32)
    with pytest.raises(ValueError, match="digest"):
        build_adapter_app(service, credential_digest="not-a-digest")
    with pytest.raises(ValueError, match="positive"):
        build_adapter_app(service, credential_digest="a" * 64, max_request_bytes=0)
