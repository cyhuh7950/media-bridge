from __future__ import annotations

import json

import httpx
import pytest

from media_bridge.omniroute_adapter import (
    GuardedOmniRouteAdapter,
    OmniRouteAdapterError,
    OmniRouteGuardError,
    SealedResponsesRequest,
    digest_responses_payload,
)
from media_bridge.receipts import GateReceiptSigner, ReceiptBinding


def _sealed(
    signer: GateReceiptSigner,
    payload: dict[str, object],
    *,
    capability: str = "non_vision",
    action: str = "passthrough",
) -> SealedResponsesRequest:
    binding = ReceiptBinding(
        target_id="text-model",
        capability=capability,
        input_digest="a" * 64,
        output_digest=digest_responses_payload(payload),
        action=action,
    )
    return SealedResponsesRequest(
        target_id=binding.target_id,
        capability=binding.capability,
        action=binding.action,
        payload=payload,
        input_digest=binding.input_digest,
        output_digest=binding.output_digest,
        receipt=signer.sign(binding),
    )


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://10.0.0.5:20128/v1/responses",
        "http://user:pass@127.0.0.1:20128/v1/responses",
        "https://omniroute.example/v1/responses?secret=x",
        "https://omniroute.example/v1/responses#fragment",
        "https://omniroute.example/v1/chat/completions",
        "ftp://omniroute.example/v1/responses",
    ],
)
def test_adapter_rejects_unsafe_endpoint(endpoint: str) -> None:
    signer = GateReceiptSigner(secret=b"s" * 32)

    with pytest.raises(ValueError, match="endpoint"):
        GuardedOmniRouteAdapter(endpoint=endpoint, receipt_signer=signer)


@pytest.mark.asyncio
async def test_adapter_rejects_digest_tampering_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_OMNI_KEY", "secret")
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"id": "resp_never"})

    signer = GateReceiptSigner(secret=b"s" * 32)
    payload: dict[str, object] = {"model": "text-model", "input": "safe"}
    sealed = _sealed(signer, payload)
    payload["input"] = "tampered"
    adapter = GuardedOmniRouteAdapter(
        endpoint="http://localhost:20128/v1/responses",
        receipt_signer=signer,
        api_key_env="TEST_OMNI_KEY",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(OmniRouteGuardError, match="digest"):
        await adapter.invoke(sealed)
    assert calls == 0
    await adapter.close()


@pytest.mark.asyncio
async def test_adapter_rejects_signed_nonvision_media_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_OMNI_KEY", "secret")
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"id": "resp_never"})

    signer = GateReceiptSigner(secret=b"s" * 32)
    payload: dict[str, object] = {
        "model": "text-model",
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_image", "image_url": "data:image/png;base64,AAAA"}],
            }
        ],
    }
    adapter = GuardedOmniRouteAdapter(
        endpoint="http://127.0.0.1:20128/v1/responses",
        receipt_signer=signer,
        api_key_env="TEST_OMNI_KEY",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(OmniRouteGuardError, match="media"):
        await adapter.invoke(_sealed(signer, payload))
    assert calls == 0
    await adapter.close()


@pytest.mark.asyncio
async def test_adapter_missing_secret_and_oversized_response_fail_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_MISSING_KEY", raising=False)
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"id": "resp_large", "padding": "x" * 100})

    signer = GateReceiptSigner(secret=b"s" * 32)
    sealed = _sealed(signer, {"model": "text-model", "input": "safe"})
    missing = GuardedOmniRouteAdapter(
        endpoint="http://127.0.0.1:20128/v1/responses",
        receipt_signer=signer,
        api_key_env="TEST_MISSING_KEY",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(OmniRouteAdapterError) as missing_error:
        await missing.invoke(sealed)
    assert missing_error.value.code == "omniroute_configuration"
    assert calls == 0
    await missing.close()

    monkeypatch.setenv("TEST_OMNI_KEY", "secret")
    oversized = GuardedOmniRouteAdapter(
        endpoint="http://127.0.0.1:20128/v1/responses",
        receipt_signer=signer,
        api_key_env="TEST_OMNI_KEY",
        transport=httpx.MockTransport(handler),
        max_response_bytes=32,
    )
    with pytest.raises(OmniRouteAdapterError) as oversized_error:
        await oversized.invoke(sealed)
    assert oversized_error.value.code == "omniroute_response_oversized"
    assert "padding" not in oversized_error.value.safe_message
    assert calls == 1
    await oversized.close()


@pytest.mark.asyncio
async def test_adapter_accepts_bounded_sse_and_extracts_response_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_OMNI_KEY", "secret")

    async def handler(_request: httpx.Request) -> httpx.Response:
        body = (
            'event: response.created\n'
            'data: {"type":"response.created","response":{"id":"resp_sse"}}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    signer = GateReceiptSigner(secret=b"s" * 32)
    adapter = GuardedOmniRouteAdapter(
        endpoint="https://omniroute.example/v1/responses",
        receipt_signer=signer,
        api_key_env="TEST_OMNI_KEY",
        transport=httpx.MockTransport(handler),
    )

    response = await adapter.invoke(
        _sealed(signer, {"model": "text-model", "input": "safe", "stream": True})
    )

    assert response.response_id == "resp_sse"
    assert response.content_type == "text/event-stream"
    assert json.loads(response.body.split(b"data: ")[1].splitlines()[0])["response"]["id"] == "resp_sse"
    await adapter.close()
