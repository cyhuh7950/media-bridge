from __future__ import annotations

import asyncio
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from media_bridge.acquisition import MediaAcquirer
from media_bridge.assets import AssetStore
from media_bridge.backends import BackendStatus, OcrResult, VisionResult
from media_bridge.capabilities import CapabilityRegistry, ModelCapability
from media_bridge.gate import PreRequestGate
from media_bridge.http_app import build_http_app
from media_bridge.mcp_server import build_mcp_server
from media_bridge.receipts import GateReceiptSigner
from media_bridge.service import MediaBridgeService


class Ocr:
    async def extract(self, **_kwargs: Any) -> OcrResult:
        return OcrResult(BackendStatus.SUCCESS, text="unused")


class Vision:
    async def describe(self, **_kwargs: Any) -> VisionResult:
        return VisionResult(BackendStatus.SUCCESS, description="unused")


def _service(tmp_path: Path) -> MediaBridgeService:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    registry = CapabilityRegistry(
        [ModelCapability("text-model", {"text"}, now + timedelta(hours=1))],
        version="network-test",
    )
    gate = PreRequestGate(
        registry=registry,
        acquirer=MediaAcquirer(asset_store=AssetStore(tmp_path / "gate-assets")),
        ocr_backend=Ocr(),
        vision_backend=Vision(),
        receipt_signer=GateReceiptSigner(
            secret=b"n" * 32,
            clock=lambda: now.timestamp(),
        ),
        now=lambda: now,
    )
    return MediaBridgeService(gate=gate)


@pytest.mark.asyncio
async def test_actual_tcp_mcp_initialize_list_and_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MEDIA_BRIDGE_SERVICE_TOKEN", "service-secret")
    server = build_mcp_server(_service(tmp_path), tenant_provider=lambda: "tenant-a")
    app = build_http_app(server=server, asset_store=AssetStore(tmp_path / "upload-assets"))
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    uvicorn_server = uvicorn.Server(
        uvicorn.Config(
            app,
            log_config=None,
            access_log=False,
            server_header=False,
            lifespan="on",
        )
    )
    serve_task = asyncio.create_task(uvicorn_server.serve(sockets=[listener]))

    try:
        async with asyncio.timeout(5):
            while not uvicorn_server.started:
                await asyncio.sleep(0.01)
        http_client = create_mcp_http_client(
            headers={
                "Authorization": "Bearer service-secret",
                "X-Media-Bridge-Tenant": "tenant-a",
            }
        )
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
        uvicorn_server.should_exit = True
        await asyncio.wait_for(serve_task, timeout=5)
