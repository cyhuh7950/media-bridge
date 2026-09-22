from __future__ import annotations

import json
from typing import Any

import pytest

from media_bridge.backends import AnalysisResult, BackendStatus
from media_bridge.receipts import GateReceiptSigner, ReceiptBinding
from media_bridge_gateway.contracts import DownstreamError, SealedGatewayRequest
from media_bridge_gateway.downstream import ProviderResponsesDownstream
from media_bridge_gateway.normalizer import digest_gateway_payload


class CaptureBackend:
    def __init__(self) -> None:
        self.context = ""

    async def analyze(self, *, context: str, user_request: str) -> AnalysisResult:
        self.context = context
        return AnalysisResult(BackendStatus.SUCCESS, analysis="test answer")


def _request(
    signer: GateReceiptSigner,
    target_id: str,
    *,
    client_effort: str | None = None,
) -> SealedGatewayRequest:
    payload = {"model": target_id, "input": "sanitized OCR text"}
    if client_effort is not None:
        payload["reasoning_effort"] = client_effort
    nonce = "0123456789abcdef"
    output_digest = digest_gateway_payload({"payload": payload, "request_nonce": nonce})
    binding = ReceiptBinding(
        target_id=target_id,
        capability="non_vision",
        input_digest="input-digest",
        output_digest=output_digest,
        action="converted",
    )
    return SealedGatewayRequest(
        target_id=target_id,
        capability="non_vision",
        action="converted",
        payload=payload,
        input_digest=binding.input_digest,
        output_digest=output_digest,
        receipt=signer.sign(binding),
        request_nonce=nonce,
        snapshot_version=1,
    )


def _snapshot(*, duplicate: bool = False) -> dict[str, Any]:
    models = [
        {"id": "solar-alias", "provider_id": "provider-solar", "aliases": ["public-solar"]}
    ]
    providers = [
        {
            "id": "provider-solar",
            "kind": "llm",
            "enabled": True,
            "catalog_id": "upstage-solar",
            "protocol": "openai-chat-completions",
            "endpoint": "https://api.upstage.ai/v1/chat/completions",
            "model_id": "solar-pro4",
            "reasoning_effort": "high",
        }
    ]
    if duplicate:
        models.append(
            {"id": "solar-alias", "provider_id": "provider-other", "aliases": []}
        )
        providers.append({**providers[0], "id": "provider-other"})
    return {"registry": {"models": models}, "providers": providers}


@pytest.mark.asyncio
async def test_downstream_resolves_model_provider_from_snapshot_and_only_passes_text() -> None:
    signer = GateReceiptSigner(secret=b"r" * 32)
    backend = CaptureBackend()
    seen_provider_ids: list[str] = []

    def build(provider: dict[str, Any]) -> CaptureBackend:
        seen_provider_ids.append(provider["id"])
        return backend

    downstream = ProviderResponsesDownstream(
        snapshot=_snapshot(),
        backend_factory=build,
        receipt_signer=signer,
    )
    response = await downstream.invoke(
        _request(signer, "solar-alias", client_effort="low")
    )

    assert response.status_code == 200
    assert json.loads(response.body)["model"] == "solar-alias"
    assert seen_provider_ids == ["provider-solar"]
    assert backend.context == "sanitized OCR text"


@pytest.mark.asyncio
async def test_downstream_rejects_ambiguous_model_provider_before_backend_creation() -> None:
    signer = GateReceiptSigner(secret=b"r" * 32)
    created: list[bool] = []

    def build(_provider: dict[str, Any]) -> CaptureBackend:
        created.append(True)
        return CaptureBackend()

    downstream = ProviderResponsesDownstream(
        snapshot=_snapshot(duplicate=True),
        backend_factory=build,
        receipt_signer=signer,
    )
    with pytest.raises(DownstreamError, match="unique") as error:
        await downstream.invoke(_request(signer, "solar-alias"))

    assert error.value.code == "model_provider_unavailable"
    assert not created


@pytest.mark.asyncio
async def test_downstream_rejects_missing_provider_mapping_before_backend_creation() -> None:
    signer = GateReceiptSigner(secret=b"r" * 32)
    created: list[bool] = []
    snapshot = _snapshot()
    snapshot["providers"] = []

    def build(_provider: dict[str, Any]) -> CaptureBackend:
        created.append(True)
        return CaptureBackend()

    downstream = ProviderResponsesDownstream(
        snapshot=snapshot,
        backend_factory=build,
        receipt_signer=signer,
    )
    with pytest.raises(DownstreamError) as error:
        await downstream.invoke(_request(signer, "solar-alias"))

    assert error.value.code == "model_provider_unavailable"
    assert not created


@pytest.mark.asyncio
async def test_downstream_maps_unsupported_provider_contract_to_safe_error() -> None:
    signer = GateReceiptSigner(secret=b"r" * 32)

    def build(_provider: dict[str, Any]) -> CaptureBackend:
        raise ValueError("sensitive adapter construction details")

    downstream = ProviderResponsesDownstream(
        snapshot=_snapshot(),
        backend_factory=build,
        receipt_signer=signer,
    )
    with pytest.raises(DownstreamError) as error:
        await downstream.invoke(_request(signer, "solar-alias"))

    assert error.value.code == "model_provider_unavailable"
    assert "sensitive" not in error.value.safe_message
