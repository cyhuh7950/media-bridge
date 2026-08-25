from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from media_bridge_adapters.app import build_adapter_app
from media_bridge_adapters.contracts import PreUpstreamRequest
from media_bridge_adapters.http_client import GatewayPrepareClient, GatewayPrepareError
from media_bridge_adapters.service import PreUpstreamService


class FailingGateway:
    async def prepare(self, _payload: dict[str, object]):
        raise GatewayPrepareError("gateway_unavailable")


def text_request() -> dict[str, object]:
    return PreUpstreamRequest(
        contract_version="media-bridge-pre-upstream/v1",
        request_id="req_security",
        wire_format="openai-responses",
        provider="openai",
        target_model="text-model",
        body={"model": "text-model", "input": "hello"},
    ).model_dump(mode="json")


@pytest.mark.asyncio
async def test_gateway_failure_returns_bounded_block_without_body_or_exception() -> None:
    service = PreUpstreamService(gateway=FailingGateway(), decision_secret=b"d" * 32)

    result = await service.prepare(PreUpstreamRequest.model_validate(text_request()))

    assert result.status == "blocked"
    assert result.body is None
    assert result.error is not None
    assert result.error.code == "gateway_unavailable"


@pytest.mark.asyncio
async def test_adapter_http_requires_digest_verified_bearer() -> None:
    raw_credential = "mba_test-only-credential"
    app = build_adapter_app(
        PreUpstreamService(gateway=FailingGateway(), decision_secret=b"d" * 32),
        credential_digest=hashlib.sha256(raw_credential.encode()).hexdigest(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.post("/adapter/v1/pre-upstream", json=text_request())
        wrong = await client.post(
            "/adapter/v1/pre-upstream",
            headers={"authorization": "Bearer mba_wrong"},
            json=text_request(),
        )
        duplicate = await client.post(
            "/adapter/v1/pre-upstream",
            headers=[
                ("authorization", f"Bearer {raw_credential}"),
                ("authorization", "Bearer mba_wrong"),
                ("content-type", "application/json"),
            ],
            content=json.dumps(text_request()).encode(),
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert duplicate.status_code == 401
    assert raw_credential not in missing.text + wrong.text + duplicate.text


@pytest.mark.asyncio
async def test_gateway_client_rejects_redirect_without_following_it() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(307, headers={"location": "https://attacker.invalid/capture"})

    client = GatewayPrepareClient(
        base_url="https://bridge.example",
        credential="mbc_test-only-credential",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(GatewayPrepareError, match="gateway_redirect_rejected"):
        await client.prepare({"content": [{"type": "text", "text": "hello"}]})

    assert calls == ["https://bridge.example/v1/prepare"]
