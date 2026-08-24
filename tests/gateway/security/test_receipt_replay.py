from __future__ import annotations

import httpx
import pytest

from media_bridge.receipts import GateReceiptSigner, ReceiptBinding
from media_bridge_gateway.contracts import DownstreamGuardError, SealedGatewayRequest
from media_bridge_gateway.downstream import GuardedResponsesDownstream
from media_bridge_gateway.normalizer import digest_gateway_payload


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
    binding = ReceiptBinding(
        target_id="text-model",
        capability="non_vision",
        input_digest="a" * 64,
        output_digest=digest_gateway_payload(payload),
        action="passthrough",
    )
    sealed = SealedGatewayRequest(
        target_id=binding.target_id,
        capability=binding.capability,
        action=binding.action,
        payload=payload,
        input_digest=binding.input_digest,
        output_digest=binding.output_digest,
        receipt=signer.sign(binding),
        snapshot_version=1,
    )
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
