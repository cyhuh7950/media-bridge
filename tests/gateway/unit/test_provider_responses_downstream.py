from __future__ import annotations

import json
from typing import Any

import pytest

from media_bridge.backends import AnalysisResult, BackendStatus
from media_bridge.receipts import GateReceiptSigner, ReceiptBinding
from media_bridge_gateway.contracts import DownstreamError, SealedGatewayRequest
from media_bridge_gateway.downstream import ProviderResponsesDownstream
from media_bridge_gateway.normalizer import digest_gateway_payload


def _s18_sealed(signer: GateReceiptSigner, payload: dict[str, Any]) -> SealedGatewayRequest:
    nonce = "s18-generation-options-0001"
    digest = digest_gateway_payload({"payload": payload, "request_nonce": nonce})
    binding = ReceiptBinding(
        target_id="solar-alias",
        capability="non_vision",
        input_digest="input-digest",
        output_digest=digest,
        action="converted",
    )
    return SealedGatewayRequest(
        target_id=binding.target_id,
        capability=binding.capability,
        action=binding.action,
        payload=payload,
        input_digest=binding.input_digest,
        output_digest=digest,
        receipt=signer.sign(binding),
        request_nonce=nonce,
        snapshot_version=1,
    )


_S18_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "cited_chunk_ids": {"type": "array", "items": {"type": "string"}},
        "insufficient": {"type": "boolean"},
    },
    "required": ["answer", "cited_chunk_ids", "insufficient"],
    "additionalProperties": False,
}
_S18_FORMAT = {
    "type": "json_schema",
    "name": "grounded_answer",
    "strict": True,
    "schema": _S18_SCHEMA,
}


@pytest.mark.asyncio
@pytest.mark.parametrize("ingress", ["chat", "responses"])
@pytest.mark.parametrize(
    "catalog,protocol",
    [
        ("upstage-solar", "openai-chat-completions"),
        ("openai", "openai-chat-completions"),
        ("openai", "openai-responses"),
    ],
)
@pytest.mark.parametrize(
    "output",
    [
        '{"answer":"근거 답변","cited_chunk_ids":["chunk-1"],"insufficient":false}',
        '{"answer":"근거에 정보가 없습니다.","cited_chunk_ids":[],"insufficient":true}',
        "not JSON; do not repair this answer",
    ],
)
async def test_s18_signed_generation_options_reach_actual_provider_request(
    ingress: str,
    catalog: str,
    protocol: str,
    output: str,
) -> None:
    import httpx

    from media_bridge.llm_backends import build_llm_backend
    from media_bridge.openai_chat import chat_request_to_responses

    payload = {
        "model": "solar-alias",
        "input": "sanitized evidence",
        "instructions": "Return only JSON. Preserve 한국어 instructions.",
        "max_output_tokens": 512,
        "text": {"format": _S18_FORMAT},
    }
    if ingress == "chat":
        payload = chat_request_to_responses(
            {
                "model": "solar-alias",
                "messages": [
                    {"role": "system", "content": payload["instructions"]},
                    {"role": "user", "content": "sanitized evidence"},
                ],
                "max_tokens": 512,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "grounded_answer",
                        "strict": True,
                        "schema": _S18_SCHEMA,
                    },
                },
            }
        )
    seen: list[httpx.Request] = []
    loads: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = (
            {"output_text": output}
            if protocol == "openai-responses"
            else {"choices": [{"message": {"content": output}}]}
        )
        return httpx.Response(200, json=body)

    snapshot = _snapshot()
    provider = snapshot["providers"][0]
    provider.update(
        catalog_id=catalog,
        protocol=protocol,
        endpoint="https://provider.example/v1",
        model_id="solar-pro4" if catalog == "upstage-solar" else "gpt-5.1",
    )

    def credential() -> str:
        loads.append("loaded")
        return "synthetic-provider-secret"

    signer = GateReceiptSigner(secret=b"r" * 32)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        downstream = ProviderResponsesDownstream(
            snapshot=snapshot,
            receipt_signer=signer,
            backend_factory=lambda configuration: build_llm_backend(
                configuration, credential_loader=credential, client=client
            ),
        )
        response = await downstream.invoke(_s18_sealed(signer, payload))
    assert len(seen) == 1
    assert loads == ["loaded"]
    outgoing = json.loads(seen[0].content)
    assert outgoing["model"] == provider["model_id"]
    if protocol == "openai-responses":
        assert outgoing["instructions"] == "Return only JSON. Preserve 한국어 instructions."
        assert outgoing["max_output_tokens"] == 512
        assert outgoing["text"] == {"format": _S18_FORMAT}
        assert outgoing["input"] == "sanitized evidence"
        assert "max_tokens" not in outgoing
    else:
        assert outgoing["messages"][0] == {
            "role": "system",
            "content": "Return only JSON. Preserve 한국어 instructions.",
        }
        assert outgoing["messages"][-1] == {"role": "user", "content": "sanitized evidence"}
        cap_key = "max_completion_tokens" if catalog == "openai" else "max_tokens"
        other_key = "max_tokens" if catalog == "openai" else "max_completion_tokens"
        assert outgoing[cap_key] == 512
        assert other_key not in outgoing
        assert outgoing["response_format"] == {
            "type": "json_schema",
            "json_schema": {"name": "grounded_answer", "strict": True, "schema": _S18_SCHEMA},
        }
        assert "max_output_tokens" not in outgoing
    assert json.loads(response.body)["output"][0]["content"][0]["text"] == output


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra",
    [
        {"max_output_tokens": True},
        {"max_output_tokens": 512.0},
        {"max_output_tokens": 0},
        {"max_output_tokens": -1},
        {"max_tokens": 512, "max_output_tokens": 1024},
        {"instructions": ["invalid"]},
        {"text": {"format": {"type": "unknown"}}},
        {"text": {"format": {**_S18_FORMAT, "strict": 1}}},
        {"text": {"format": {**_S18_FORMAT, "schema": []}}},
        {"temperature": 0.5},
        {"tools": [{"type": "function"}]},
        {"text": {"format": {"type": []}}},
        {"text": {"format": {"type": {}}}},
    ],
)
async def test_s18_invalid_generation_options_stop_before_backend_creation(
    extra: dict[str, Any],
) -> None:
    from media_bridge_gateway.contracts import DownstreamError

    signer = GateReceiptSigner(secret=b"r" * 32)
    builds: list[object] = []

    def build(provider: dict[str, Any]) -> CaptureBackend:
        builds.append(provider)
        return CaptureBackend()

    downstream = ProviderResponsesDownstream(
        snapshot=_snapshot(), backend_factory=build, receipt_signer=signer
    )
    with pytest.raises(DownstreamError) as error:
        await downstream.invoke(
            _s18_sealed(signer, {"model": "solar-alias", "input": "safe", **extra})
        )
    assert error.value.http_status == 400
    assert builds == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "catalog,protocol,model",
    [
        ("gemini", "gemini-generate-content", "gemini-2.5-flash"),
        ("anthropic", "anthropic-messages", "claude-sonnet-4"),
    ],
)
async def test_s18_unverified_provider_options_never_load_credentials_or_call_http(
    catalog: str,
    protocol: str,
    model: str,
) -> None:
    import httpx

    from media_bridge.llm_backends import build_llm_backend
    from media_bridge_gateway.contracts import DownstreamError

    signer = GateReceiptSigner(secret=b"r" * 32)
    snapshot = _snapshot()
    snapshot["providers"][0].update(
        catalog_id=catalog,
        protocol=protocol,
        model_id=model,
        endpoint="https://provider.example/v1beta/models"
        if catalog == "gemini"
        else "https://provider.example/v1",
        reasoning_effort="provider_default",
    )
    calls: list[str] = []

    def credential() -> str:
        calls.append("credential")
        return "synthetic-secret"

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append("http")
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        downstream = ProviderResponsesDownstream(
            snapshot=snapshot,
            receipt_signer=signer,
            backend_factory=lambda provider: build_llm_backend(
                provider, credential_loader=credential, client=client
            ),
        )
        with pytest.raises(DownstreamError):
            await downstream.invoke(
                _s18_sealed(
                    signer,
                    {
                        "model": "solar-alias",
                        "input": "safe",
                        "instructions": "JSON only",
                        "max_output_tokens": 512,
                        "text": {"format": _S18_FORMAT},
                    },
                )
            )
    assert calls == []


@pytest.mark.asyncio
async def test_s18_legacy_backend_rejects_options_without_silent_fallback() -> None:
    from media_bridge_gateway.contracts import DownstreamError

    backend = CaptureBackend()
    signer = GateReceiptSigner(secret=b"r" * 32)
    downstream = ProviderResponsesDownstream(
        backend=backend, model="solar-alias", receipt_signer=signer
    )
    with pytest.raises(DownstreamError) as error:
        await downstream.invoke(
            _s18_sealed(signer, {"model": "solar-alias", "input": "safe", "max_output_tokens": 512})
        )
    assert error.value.http_status == 400
    assert backend.context == ""


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
    stream: bool | None = None,
) -> SealedGatewayRequest:
    payload = {"model": target_id, "input": "sanitized OCR text"}
    if client_effort is not None:
        payload["reasoning_effort"] = client_effort
    if stream is not None:
        payload["stream"] = stream
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
    models = [{"id": "solar-alias", "provider_id": "provider-solar", "aliases": ["public-solar"]}]
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
        models.append({"id": "solar-alias", "provider_id": "provider-other", "aliases": []})
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
        _request(signer, "solar-alias", client_effort="low", stream=False)
    )

    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert response.stream is None
    assert json.loads(response.body)["model"] == "solar-alias"
    assert seen_provider_ids == ["provider-solar"]
    assert backend.context == "sanitized OCR text"


@pytest.mark.asyncio
async def test_provider_downstream_streams_responses_events_when_requested() -> None:
    signer = GateReceiptSigner(secret=b"r" * 32)
    downstream = ProviderResponsesDownstream(
        backend=CaptureBackend(), model="solar-alias", receipt_signer=signer
    )

    response = await downstream.invoke(_request(signer, "solar-alias", stream=True))

    assert response.content_type == "text/event-stream"
    assert response.stream is not None
    wire = b"".join([chunk async for chunk in response.stream]).decode("utf-8")
    events = []
    for frame in wire.strip().split("\n\n"):
        lines = frame.splitlines()
        assert lines[0].startswith("event: response.")
        assert lines[1].startswith("data: ")
        events.append(json.loads(lines[1][6:]))
    assert [event["type"] for event in events] == [
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.completed",
    ]
    assert [event["sequence_number"] for event in events] == list(range(len(events)))
    assert events[4]["delta"] == "test answer"
    completed = events[-1]["response"]
    assert completed["status"] == "completed"
    assert completed["output"][0]["content"][0]["text"] == "test answer"


@pytest.mark.asyncio
async def test_downstream_uses_default_routing_when_model_has_no_route_binding() -> None:
    signer = GateReceiptSigner(secret=b"r" * 32)
    backend = CaptureBackend()
    seen_provider_ids: list[str] = []

    def build(provider: dict[str, Any]) -> CaptureBackend:
        seen_provider_ids.append(provider["id"])
        return backend

    snapshot = _snapshot()
    snapshot["providers"].append(
        {
            "id": "provider-route-default",
            "kind": "llm",
            "enabled": True,
            "catalog_id": "openai",
            "protocol": "openai-chat-completions",
            "endpoint": "https://api.openai.com/v1/chat/completions",
            "model_id": "gpt-5",
        }
    )
    snapshot["routing_profiles"] = [
        {
            "id": "route-default",
            "llm_provider_ids": ["provider-route-default"],
            "strategy": "priority",
            "enabled": True,
        }
    ]

    downstream = ProviderResponsesDownstream(
        snapshot=snapshot,
        backend_factory=build,
        receipt_signer=signer,
    )
    await downstream.invoke(_request(signer, "solar-alias"))

    assert seen_provider_ids == ["provider-route-default"]


@pytest.mark.asyncio
async def test_provider_default_snapshot_effort_keeps_provider_setting() -> None:
    signer = GateReceiptSigner(secret=b"r" * 32)
    backend = CaptureBackend()
    seen_providers: list[dict[str, Any]] = []

    def build(provider: dict[str, Any]) -> CaptureBackend:
        seen_providers.append(provider)
        return backend

    snapshot = _snapshot()
    snapshot["defaults"] = {"reasoning_effort": "provider_default"}
    downstream = ProviderResponsesDownstream(
        snapshot=snapshot,
        backend_factory=build,
        receipt_signer=signer,
    )

    await downstream.invoke(_request(signer, "solar-alias"))

    assert seen_providers[0]["reasoning_effort"] == "high"


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
