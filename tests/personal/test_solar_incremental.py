"""upstream 완료 전 클라이언트 delta 전달 및 연결 종료를 검증한다."""
import asyncio
import json

import httpx
import pytest

from media_bridge_gateway.contracts import DownstreamError
from tests.personal.test_solar_responses import _downstream, _sealed


@pytest.mark.asyncio
async def test_json_body_transport_failure_is_a_safe_downstream_error(monkeypatch):
    class Broken(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"choices":'
            raise httpx.ReadError("private transport details")

    downstream, signer = _downstream(monkeypatch, lambda _: httpx.Response(
        200, headers={"content-type": "application/json"}, stream=Broken()))
    try:
        with pytest.raises(DownstreamError) as error:
            await downstream.invoke(_sealed(signer, {"model": "solar-pro4", "input": "hello"}))
        assert error.value.code == "solar_transport"
        assert "private" not in error.value.safe_message
    finally:
        await downstream.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["eof", "malformed", "transport"])
async def test_failed_stream_never_emits_completed_and_closes(monkeypatch, failure):
    closed = []

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            if failure == "malformed":
                yield b"data: broken-secret-fixture\n\n"
            if failure == "transport":
                raise httpx.ReadError("private upstream diagnostic")

        async def aclose(self):
            closed.append(True)

    downstream, signer = _downstream(monkeypatch, lambda _: httpx.Response(
        200, headers={"content-type": "text/event-stream"}, stream=Chunks()))
    events = []
    try:
        result = await downstream.invoke(_sealed(signer, {
            "model": "solar-pro4", "input": "hello", "stream": True}))
        with pytest.raises(DownstreamError):
            async for chunk in result.stream:
                events.append(chunk)
    finally:
        await downstream.close()
    wire = b"".join(events)
    assert b"response.failed" in wire
    assert b"response.completed" not in wire
    assert b"[DONE]" not in wire
    assert b"secret-fixture" not in wire and b"private upstream" not in wire
    assert closed


@pytest.mark.asyncio
@pytest.mark.parametrize("started", [False, True])
async def test_cancelled_stream_closes_upstream(monkeypatch, started):
    closed = []

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            raise AssertionError("consumer cancelled before reading more")

        async def aclose(self):
            closed.append(True)

    downstream, signer = _downstream(monkeypatch, lambda _: httpx.Response(
        200, headers={"content-type": "text/event-stream"}, stream=Chunks()))
    try:
        result = await downstream.invoke(_sealed(signer, {
            "model": "solar-pro4", "input": "hello", "stream": True}))
        if started:
            await anext(result.stream)
        await result.stream.aclose()
        assert closed
    finally:
        await downstream.close()


@pytest.mark.asyncio
async def test_tool_arguments_stream_in_fragments(monkeypatch):
    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            frames = [
                {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0,
                    "id": "c_stream", "type": "function", "function": {
                        "name": "read_file", "arguments": '{"path":'}}]}}]},
                {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0,
                    "function": {"arguments": '"a.txt"}'}}]}}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            ]
            for frame in frames:
                yield ("data: " + json.dumps(frame) + "\n\n").encode()
            yield b"data: [DONE]\n\n"

    downstream, signer = _downstream(monkeypatch, lambda _: httpx.Response(
        200, headers={"content-type": "text/event-stream"}, stream=Chunks()))
    try:
        result = await downstream.invoke(_sealed(signer, {
            "model": "solar-pro4", "input": "read", "stream": True,
            "tools": [{"type": "function", "name": "read_file", "parameters": {
                "type": "object", "properties": {"path": {"type": "string"}}}}]}))
        wire = b"".join([chunk async for chunk in result.stream]).decode()
    finally:
        await downstream.close()
    events = [json.loads(line[6:]) for line in wire.splitlines() if line.startswith("data: {")]
    deltas = [e["delta"] for e in events if e["type"] == "response.function_call_arguments.delta"]
    assert deltas == ['{"path":', '"a.txt"}']
    completed = next(e["response"] for e in events if e["type"] == "response.completed")
    assert completed["output"][0]["call_id"] == "c_stream"
    assert completed["output"][0]["arguments"] == '{"path":"a.txt"}'


@pytest.mark.asyncio
async def test_text_delta_arrives_before_upstream_finishes(monkeypatch):
    release = asyncio.Event()
    closed = False

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"index":0,"delta":{"content":"first"}}]}\n\n'
            await release.wait()
            yield b'data: {"choices":[{"index":0,"delta":{"content":" second"}}]}\n\n'
            yield b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
            yield b'data: [DONE]\n\n'

        async def aclose(self):
            nonlocal closed
            closed = True

    def provider(request):
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Chunks())

    downstream, signer = _downstream(monkeypatch, provider)
    try:
        result = await asyncio.wait_for(downstream.invoke(_sealed(signer, {
            "model": "solar-pro4", "input": "hello", "stream": True})), 1)
        assert result.stream is not None
        events = []
        while True:
            chunk = await asyncio.wait_for(anext(result.stream), 1)
            events.append(chunk)
            if b'response.output_text.delta' in chunk:
                assert b'first' in chunk
                break
        assert not release.is_set()
        release.set()
        events.extend([chunk async for chunk in result.stream])
        wire = b"".join(events)
        assert b'first second' in wire
        assert b'response.completed' in wire
        assert wire.endswith(b'data: [DONE]\n\n')
        assert closed
    finally:
        release.set()
        await downstream.close()
