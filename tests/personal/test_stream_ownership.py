"""거래·HTTP 응답도 읽기 시작 전 upstream 소유권을 해제해야 한다."""
import httpx
import pytest
from starlette.requests import ClientDisconnect

from media_bridge_gateway.contracts import GatewayResponse
from media_bridge_gateway.streams import ClosingStreamingResponse
from media_bridge_personal.npm_runtime import build_personal_runtime
from media_bridge_personal.solar_responses import SolarResponsesDownstream
from tests.personal.test_npm_runtime import FakeOcr


@pytest.mark.asyncio
@pytest.mark.parametrize("via_http", [False, True])
async def test_unstarted_transaction_and_http_failure_close_upstream(tmp_path, via_http):
    closed = []

    class Unread(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("body must remain unread")
            yield b""  # pragma: no cover

        async def aclose(self):
            closed.append(True)

    runtime = build_personal_runtime(
        model="solar-pro4", asset_root=tmp_path / "assets", receipt_secret=b"r" * 32,
        ocr_backend=FakeOcr(), downstream_factory=lambda signer: SolarResponsesDownstream(
            endpoint="https://synthetic.example.test/v1/chat/completions", model="solar-pro4",
            receipt_signer=signer, credential_loader=lambda: "synthetic",
            transport=httpx.MockTransport(lambda _: httpx.Response(200,
                headers={"content-type": "text/event-stream"}, stream=Unread()))),
    )
    try:
        result = await runtime.invoke({"model": "solar-pro4", "input": "hi", "stream": True})
        assert isinstance(result, GatewayResponse)
        if via_http:
            async def send(_message):
                raise OSError("client disconnected before response headers")

            async def receive():
                return {"type": "http.disconnect"}

            with pytest.raises(ClientDisconnect):
                await ClosingStreamingResponse(result.stream)(
                    {"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        else:
            await result.stream.aclose()
        assert closed
    finally:
        await runtime.close()
