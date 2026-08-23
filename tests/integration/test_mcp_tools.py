from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from media_bridge.acquisition import MediaAcquirer
from media_bridge.assets import AssetStore
from media_bridge.backends import (
    AnalysisResult,
    BackendStatus,
    OcrResult,
    VisionResult,
)
from media_bridge.capabilities import CapabilityRegistry, ModelCapability
from media_bridge.gate import PreRequestGate
from media_bridge.mcp_server import build_mcp_server
from media_bridge.receipts import GateReceiptSigner
from media_bridge.service import MediaBridgeService


def _png_base64() -> str:
    output = BytesIO()
    Image.new("RGB", (2, 2), color="green").save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


class Ocr:
    async def extract(self, **_kwargs: Any) -> OcrResult:
        return OcrResult(BackendStatus.SUCCESS, text="Traceback line 42")


class Vision:
    async def describe(self, **_kwargs: Any) -> VisionResult:
        return VisionResult(BackendStatus.SUCCESS, description="A red error dialog")


class Analysis:
    def __init__(self) -> None:
        self.calls = 0

    async def analyze(self, **_kwargs: Any) -> AnalysisResult:
        self.calls += 1
        return AnalysisResult(BackendStatus.SUCCESS, analysis="Configuration mismatch")


def _service(tmp_path: Path) -> tuple[MediaBridgeService, Analysis]:
    now = datetime(2026, 8, 23, tzinfo=UTC)
    registry = CapabilityRegistry(
        [ModelCapability("text-model", {"text"}, now + timedelta(hours=1))],
        version="test-v1",
    )
    signer = GateReceiptSigner(secret=b"m" * 32, clock=lambda: now.timestamp())
    gate = PreRequestGate(
        registry=registry,
        acquirer=MediaAcquirer(asset_store=AssetStore(tmp_path / "assets")),
        ocr_backend=Ocr(),
        vision_backend=Vision(),
        receipt_signer=signer,
        now=lambda: now,
    )
    analysis = Analysis()
    return (
        MediaBridgeService(
            gate=gate,
            analysis_backends={"solar": analysis},
        ),
        analysis,
    )


@pytest.mark.asyncio
async def test_mcp_lists_exact_tools_with_structured_schemas(tmp_path: Path) -> None:
    service, _analysis = _service(tmp_path)
    server = build_mcp_server(service, tenant_provider=lambda: "tenant-a")

    tools = await server.list_tools()
    by_name = {tool.name: tool for tool in tools}

    assert set(by_name) == {
        "extract_image_context",
        "analyze_error_image",
        "prepare_for_model",
    }
    assert "content" in by_name["prepare_for_model"].input_schema["properties"]
    assert by_name["prepare_for_model"].output_schema is not None


@pytest.mark.asyncio
async def test_direct_mcp_calls_return_text_only_structured_output(tmp_path: Path) -> None:
    service, analysis = _service(tmp_path)
    server = build_mcp_server(service, tenant_provider=lambda: "tenant-a")
    media = {
        "type": "media",
        "media_type": "image",
        "source": {"kind": "base64", "data": _png_base64()},
        "filename": "must-not-return.png",
        "declared_mime": "image/png",
    }

    extracted = await server.call_tool(
        "extract_image_context",
        {"content": [media], "conversion_profile": "error_screenshot"},
    )
    analyzed = await server.call_tool(
        "analyze_error_image",
        {
            "content": [media],
            "user_request": "Diagnose",
            "analysis_backend": "solar",
        },
    )
    prepared = await server.call_tool(
        "prepare_for_model",
        {
            "content": [media],
            "target": {"registry_id": "text-model"},
            "conversion_profile": "error_screenshot",
        },
    )

    assert extracted.structured_content is not None
    assert extracted.structured_content["status"] == "converted"
    assert extracted.structured_content["ocr_text"] == "Traceback line 42"
    assert extracted.structured_content["visual_description"] == "A red error dialog"
    assert analyzed.structured_content is not None
    assert analyzed.structured_content["status"] == "analyzed"
    assert analysis.calls == 1
    assert prepared.structured_content is not None
    assert prepared.structured_content["action"] == "converted"

    serialized = json.dumps(
        [
            extracted.structured_content,
            analyzed.structured_content,
            prepared.structured_content,
        ]
    )
    assert "must-not-return.png" not in serialized
    assert _png_base64() not in serialized
    assert '"source"' not in serialized


def test_transport_construction_exposes_stdio_and_streamable_http(tmp_path: Path) -> None:
    service, _analysis = _service(tmp_path)
    server = build_mcp_server(service, tenant_provider=lambda: "tenant-a")

    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        max_request_body_size=4 * 1024 * 1024,
    )

    assert app is not None
    assert callable(server.run)
