from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from media_bridge_gateway.app import build_gateway_app
from media_bridge_gateway.rate_limit import CredentialRouteRateLimiter
from tests.gateway.helpers import TEST_RAW_CREDENTIAL, build_test_runtime


@pytest.mark.asyncio
async def test_actual_tcp_responses_json_sse_mcp_limits_and_no_redirect(
    tmp_path: Path,
) -> None:
    runtime, _downstream, asset_store = build_test_runtime(tmp_path)
    app = build_gateway_app(
        runtime=runtime,
        asset_store=asset_store,
        rate_limiter=CredentialRouteRateLimiter(
            capacity=50,
            refill_per_second=50,
            max_keys=100,
            idle_ttl_seconds=60,
        ),
        max_responses_body_bytes=256,
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            log_config=None,
            access_log=False,
            server_header=False,
            lifespan="on",
        )
    )
    serve_task = asyncio.create_task(server.serve(sockets=[listener]))
    authorization = {"Authorization": f"Bearer {TEST_RAW_CREDENTIAL}"}

    try:
        async with asyncio.timeout(5):
            while not server.started:
                await asyncio.sleep(0.01)
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
            follow_redirects=False,
        ) as client:
            json_response = await client.post(
                "/v1/responses",
                headers=authorization,
                json={"model": "text-model", "input": "hello"},
            )
            sse_response = await client.post(
                "/v1/responses",
                headers=authorization,
                json={"model": "text-model", "input": "stream", "stream": True},
            )
            oversized = await client.post(
                "/v1/responses",
                headers={**authorization, "Content-Type": "application/json"},
                content=b'{"padding":"' + b"x" * 300 + b'"}',
            )
            slash = await client.post(
                "/v1/responses/",
                headers=authorization,
                json={"model": "text-model", "input": "no redirect"},
            )

        assert json_response.status_code == 200
        assert json_response.json()["id"] == "resp_gateway"
        assert sse_response.status_code == 200
        assert sse_response.headers["content-type"].startswith("text/event-stream")
        assert "response.created" in sse_response.text
        assert oversized.status_code == 413
        assert slash.status_code == 404

        http_client = create_mcp_http_client(headers=authorization)
        async with (
            http_client,
            streamable_http_client(
                f"http://127.0.0.1:{port}/mcp",
                http_client=http_client,
            ) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            initialized = await session.initialize()
            tools = await session.list_tools()
            called = await session.call_tool(
                "prepare_for_model",
                {
                    "content": [{"type": "text", "text": "hello"}],
                    "target": {"registry_id": "text-model"},
                },
            )

        assert initialized.server_info.name == "nonvision-media-bridge"
        assert {tool.name for tool in tools.tools} == {
            "extract_image_context",
            "analyze_error_image",
            "prepare_for_model",
        }
        assert called.structured_content is not None
        assert called.structured_content["action"] == "passthrough"
    finally:
        server.should_exit = True
        await asyncio.wait_for(serve_task, timeout=5)
