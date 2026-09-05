from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from media_bridge.receipts import GateReceiptSigner, ReceiptBinding
from media_bridge_gateway.contracts import (
    DownstreamError,
    DownstreamGuardError,
    SealedGatewayRequest,
)
from media_bridge_gateway.normalizer import digest_gateway_payload
from media_bridge_personal.solar_responses import SolarResponsesDownstream


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_function_call_and_result_keep_ids_and_history(
    monkeypatch: pytest.MonkeyPatch, stream: bool,
) -> None:
    recorded = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": None, "tool_calls": [{
                "id": "call_next", "type": "function", "function": {
                    "name": "read_file", "arguments": '{"path":"b.txt"}'}}]},
            "finish_reason": "tool_calls"}], "usage": {}})

    downstream, signer = _downstream(monkeypatch, handler)
    try:
        response = await downstream.invoke(_sealed(signer, {
            "model": "solar-pro4", "stream": stream, "input": [
                {"role": "user", "content": "inspect files"},
                {"type": "function_call", "call_id": "call_first", "name": "read_file",
                 "arguments": '{"path":"a.txt"}'},
                {"type": "function_call_output", "call_id": "call_first", "output": "ALPHA"}],
            "tools": [{"type": "function", "name": "read_file",
                       "parameters": {"type": "object", "properties": {
                           "path": {"type": "string"}}, "required": ["path"]}}]}))
    finally:
        await downstream.close()
    assert recorded[0]["messages"] == [
        {"role": "user", "content": "inspect files"},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_first", "type": "function", "function": {
                "name": "read_file", "arguments": '{"path":"a.txt"}'}}]},
        {"role": "tool", "tool_call_id": "call_first", "content": "ALPHA"}]
    assert recorded[0]["tools"][0]["function"]["name"] == "read_file"
    if stream:
        assert response.stream is not None
        wire = b"".join([chunk async for chunk in response.stream]).decode()
        events = [json.loads(line[6:]) for line in wire.splitlines()
                  if line.startswith("data: {")]
        assert any(e["type"] == "response.function_call_arguments.done" for e in events)
        output = next(e["response"]["output"] for e in events
                      if e["type"] == "response.completed")
    else:
        output = json.loads(response.body)["output"]
    assert len(output) == 1
    assert output[0]["type"] == "function_call"
    assert output[0]["call_id"] == "call_next"
    assert output[0]["arguments"] == '{"path":"b.txt"}'


@pytest.mark.asyncio
@pytest.mark.parametrize("choice, expected", [
    ("none", "none"), ("auto", "auto"), ("required", "required"),
    ({"type": "function", "name": "read_file"},
     {"type": "function", "function": {"name": "read_file"}}),
])
async def test_tool_execution_constraints_reach_provider(monkeypatch, choice, expected):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    downstream, signer = _downstream(monkeypatch, handler)
    try:
        await downstream.invoke(_sealed(signer, {
            "model": "solar-pro4", "input": "hello", "tool_choice": choice,
            "parallel_tool_calls": False,
            "tools": [{"type": "function", "name": "read_file", "parameters": {
                "type": "object", "properties": {}}}],
        }))
    finally:
        await downstream.close()
    assert sent[0]["tool_choice"] == expected
    assert sent[0]["parallel_tool_calls"] is False


@pytest.mark.asyncio
async def test_namespace_calls_keep_scope_when_local_names_overlap(monkeypatch):
    recorded = []

    def handler(request):
        body = json.loads(request.content)
        recorded.append(body)
        tools = body["tools"]
        assert len({t["function"]["name"] for t in tools}) == 3
        historical_name = body["messages"][1]["tool_calls"][0]["function"]["name"]
        assert historical_name == tools[1]["function"]["name"]
        return httpx.Response(200, json={"choices": [{"message": {
            "content": None, "tool_calls": [{"id": "next", "type": "function", "function": {
                "name": tools[2]["function"]["name"], "arguments": "{}"}}]}}]})

    downstream, signer = _downstream(monkeypatch, handler)
    function = {"type": "function", "name": "inspect", "parameters": {
        "type": "object", "properties": {"type": {"type": "string"}}}}
    try:
        result = await downstream.invoke(_sealed(signer, {
            "model": "solar-pro4", "input": [
                {"role": "user", "content": "inspect"},
                {"type": "function_call", "name": "inspect", "namespace": "one",
                 "call_id": "previous", "arguments": "{}"},
                {"type": "function_call_output", "call_id": "previous", "output": "done"}],
            "tools": [function, {"type": "namespace", "name": "one", "tools": [function]},
                      {"type": "namespace", "name": "two", "tools": [function]}],
        }))
    finally:
        await downstream.close()
    call = json.loads(result.body)["output"][0]
    assert call["namespace"] == "two"
    assert call["name"] == "inspect"
    assert call["call_id"] == "next"
    assert call["arguments"] == "{}"
    assert len(recorded) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [
    {"tools": [{"type": "web_search"}]},
    {"tools": [{"type": "custom", "name": "shell"}]},
    {"tool_choice": {"type": "function", "name": "undeclared"}},
    {"parallel_tool_calls": "false"},
    {"tools": [{"type": "namespace", "name": "bad", "tools": [
        {"type": "namespace", "name": "nested", "tools": []}]}]},
])
async def test_unsupported_tool_contract_never_calls_provider(monkeypatch, invalid):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    downstream, signer = _downstream(monkeypatch, handler)
    try:
        with pytest.raises(DownstreamGuardError):
            await downstream.invoke(_sealed(signer, {
                "model": "solar-pro4", "input": "hello", **invalid}))
    finally:
        await downstream.close()
    assert calls == []


def _sealed(
    signer: GateReceiptSigner,
    payload: dict[str, Any],
    *,
    nonce: str = "personal-request-nonce-1",
) -> SealedGatewayRequest:
    output_digest = digest_gateway_payload({"payload": payload, "request_nonce": nonce})
    binding = ReceiptBinding(
        target_id="solar-pro4",
        capability="non_vision",
        input_digest="a" * 64,
        output_digest=output_digest,
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
    )


def _downstream(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[SolarResponsesDownstream, GateReceiptSigner]:
    monkeypatch.setenv("TEST_SOLAR_API_KEY", "test-secret-not-logged")
    signer = GateReceiptSigner(secret=b"r" * 32)
    return (
        SolarResponsesDownstream(
            endpoint="https://api.example.test/v1/chat/completions",
            model="solar-pro4",
            receipt_signer=signer,
            api_key_env="TEST_SOLAR_API_KEY",
            transport=httpx.MockTransport(handler),
        ),
        signer,
    )


@pytest.mark.asyncio
async def test_translates_text_only_responses_to_solar_chat_and_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer test-secret-not-logged"
        assert request.headers["content-type"] == "application/json"
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "id": "chatcmpl-personal-1",
                "choices": [{"message": {"role": "assistant", "content": "Solar answer"}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            },
        )

    downstream, signer = _downstream(monkeypatch, handler)
    try:
        response = await downstream.invoke(
            _sealed(
                signer,
                {
                    "model": "solar-pro4",
                    "input": [
                        {
                            "role": "user",
                            "content": [{"type": "input_text", "text": "hello"}],
                        }
                    ],
                },
            )
        )
    finally:
        await downstream.close()

    assert recorded == [
        {
            "model": "solar-pro4",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": False,
        }
    ]
    body = json.loads(response.body)
    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert body["status"] == "completed"
    assert body["model"] == "solar-pro4"
    assert body["output"][0]["content"][0]["text"] == "Solar answer"
    assert body["usage"] == {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}


@pytest.mark.asyncio
async def test_rejects_remaining_media_before_solar_socket_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    downstream, signer = _downstream(monkeypatch, handler)
    try:
        with pytest.raises(DownstreamGuardError, match="media"):
            await downstream.invoke(
                _sealed(
                    signer,
                    {
                        "model": "solar-pro4",
                        "input": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_image",
                                        "image_url": "data:image/png;base64,aW1hZ2U=",
                                    }
                                ],
                            }
                        ],
                    },
                )
            )
    finally:
        await downstream.close()

    assert calls == 0


@pytest.mark.asyncio
async def test_stream_request_returns_buffered_responses_sse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "id": "chatcmpl-personal-stream",
                "choices": [{"message": {"role": "assistant", "content": "streamed answer"}}],
            },
        )

    downstream, signer = _downstream(monkeypatch, handler)
    try:
        response = await downstream.invoke(
            _sealed(
                signer,
                {"model": "solar-pro4", "input": "hello", "stream": True},
            )
        )
        assert response.stream is not None
        body = b"".join([chunk async for chunk in response.stream])
    finally:
        await downstream.close()

    assert response.content_type == "text/event-stream"
    assert b"response.created" in body
    assert b"response.output_text.delta" in body
    assert b"response.content_part.done" in body
    assert b"response.output_item.done" in body
    assert b"streamed answer" in body
    assert body.endswith(b"data: [DONE]\n\n")


@pytest.mark.asyncio
async def test_rejects_malformed_solar_usage_as_an_upstream_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "choices": [{"message": {"content": "answer"}}],
                "usage": "not-an-object",
            },
        )

    downstream, signer = _downstream(monkeypatch, handler)
    try:
        with pytest.raises(DownstreamError) as captured:
            await downstream.invoke(
                _sealed(signer, {"model": "solar-pro4", "input": "hello"})
            )
    finally:
        await downstream.close()

    assert captured.value.code == "solar_response_invalid"


@pytest.mark.asyncio
async def test_generic_responses_provider_uses_credential_loader_and_normalizes_response() -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer stored-provider-secret"
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "generic answer"}],
                    }
                ],
                "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
            },
        )

    signer = GateReceiptSigner(secret=b"r" * 32)
    downstream = SolarResponsesDownstream(
        endpoint="https://api.example.test/v1/responses",
        model="solar-pro4",
        receipt_signer=signer,
        credential_loader=lambda: "stored-provider-secret",
        protocol="openai-responses",
        provider_name="Text LLM",
        error_prefix="text_llm",
        transport=httpx.MockTransport(handler),
    )
    try:
        response = await downstream.invoke(
            _sealed(signer, {"model": "solar-pro4", "input": "hello"})
        )
    finally:
        await downstream.close()

    assert requests[0]["model"] == "solar-pro4"
    assert requests[0]["input"][0]["content"] == [
        {"type": "input_text", "text": "hello"}
    ]
    body = json.loads(response.body)
    assert body["output"][0]["content"][0]["text"] == "generic answer"
    assert body["usage"] == {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
