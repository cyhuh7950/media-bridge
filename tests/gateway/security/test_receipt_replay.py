from __future__ import annotations

import httpx
import pytest

from media_bridge.receipts import GateReceiptSigner, ReceiptBinding
from media_bridge_gateway.contracts import DownstreamGuardError, SealedGatewayRequest
from media_bridge_gateway.downstream import GuardedResponsesDownstream
from media_bridge_gateway.normalizer import digest_gateway_payload


def _sealed(
    *,
    signer: GateReceiptSigner,
    payload: dict[str, str],
    nonce: str,
) -> SealedGatewayRequest:
    binding = ReceiptBinding(
        target_id="text-model",
        capability="non_vision",
        input_digest="a" * 64,
        output_digest=digest_gateway_payload(
            {"payload": payload, "request_nonce": nonce}
        ),
        action="passthrough",
    )
    return SealedGatewayRequest(
        target_id=binding.target_id,
        capability=binding.capability,
        action=binding.action,
        payload=payload,
        input_digest=binding.input_digest,
        output_digest=binding.output_digest,
        receipt=signer.sign(binding),
        request_nonce=nonce,
        snapshot_version=1,
    )


@pytest.mark.asyncio
async def test_sealed_receipt_can_open_at_most_one_downstream_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_DOWNSTREAM_KEY", "downstream-secret")
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"id": "resp_once", "output": []})

    signer = GateReceiptSigner(secret=b"r" * 32, clock=lambda: 100.0)
    payload = {"model": "text-model", "input": "safe"}
    sealed = _sealed(signer=signer, payload=payload, nonce="nonce-replay-0001")
    downstream = GuardedResponsesDownstream(
        endpoint="http://127.0.0.1:20128/v1/responses",
        receipt_signer=signer,
        api_key_env="TEST_DOWNSTREAM_KEY",
        api_key_file_env=None,
        transport=httpx.MockTransport(handler),
        replay_clock=lambda: 100.0,
    )

    first = await downstream.invoke(sealed)
    with pytest.raises(DownstreamGuardError, match="replay"):
        await downstream.invoke(sealed)

    assert first.response_id == "resp_once"
    assert calls == 1
    await downstream.close()


@pytest.mark.asyncio
async def test_identical_requests_in_same_second_use_distinct_signed_nonces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_DOWNSTREAM_KEY", "downstream-secret")
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"id": f"resp_{calls}", "output": []})

    signer = GateReceiptSigner(secret=b"r" * 32, clock=lambda: 100.0)
    payload = {"model": "text-model", "input": "safe"}
    first = _sealed(signer=signer, payload=payload, nonce="nonce-request-0001")
    second = _sealed(signer=signer, payload=payload, nonce="nonce-request-0002")
    downstream = GuardedResponsesDownstream(
        endpoint="http://127.0.0.1:20128/v1/responses",
        receipt_signer=signer,
        api_key_env="TEST_DOWNSTREAM_KEY",
        api_key_file_env=None,
        transport=httpx.MockTransport(handler),
        replay_clock=lambda: 100.0,
    )

    first_response = await downstream.invoke(first)
    second_response = await downstream.invoke(second)

    assert first.receipt != second.receipt
    assert first_response.response_id == "resp_1"
    assert second_response.response_id == "resp_2"
    assert calls == 2
    await downstream.close()
