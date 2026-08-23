from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from pypdf import PdfWriter

from media_bridge.acquisition import MediaAcquirer
from media_bridge.assets import AssetStore
from media_bridge.backends import BackendStatus, OcrResult, VisionResult
from media_bridge.capabilities import CapabilityRegistry, ModelCapability
from media_bridge.gate import PreRequestGate
from media_bridge.pdf_pipeline import RenderedPdfPage
from media_bridge.receipts import GateReceiptSigner
from media_bridge.responses_state import ResponsesStateStore
from media_bridge_gateway.contracts import (
    DataPlaneSubject,
    GatewayResponse,
    SealedGatewayRequest,
)
from media_bridge_gateway.transaction import GatewayTransaction


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (2, 2), color="blue").save(output, format="PNG")
    return output.getvalue()


def _pdf() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=10, height=10)
    writer.write(output)
    return output.getvalue()


class FakeOcr:
    async def extract(self, **_kwargs: Any) -> OcrResult:
        return OcrResult(BackendStatus.SUCCESS, text="ERROR 104")


class FakeVision:
    async def describe(self, **_kwargs: Any) -> VisionResult:
        return VisionResult(BackendStatus.SUCCESS, description="A red terminal error")


class FakePdfRenderer:
    def render(self, _data: bytes) -> tuple[RenderedPdfPage, ...]:
        return (
            RenderedPdfPage(
                page_number=1,
                data=_png(),
                mime_type="image/png",
                filename="page-1.png",
            ),
        )


class FakeDownstream:
    def __init__(self) -> None:
        self.requests: list[SealedGatewayRequest] = []

    async def invoke(self, request: SealedGatewayRequest) -> GatewayResponse:
        self.requests.append(request)
        return GatewayResponse(
            body=b'{"id":"resp_gateway","output":[]}',
            content_type="application/json",
            response_id="resp_gateway",
            status_code=200,
        )


def _transaction(tmp_path: Path) -> tuple[GatewayTransaction, FakeDownstream]:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    signer = GateReceiptSigner(secret=b"r" * 32, clock=lambda: now.timestamp())
    registry = CapabilityRegistry(
        [ModelCapability("text-model", {"text"}, now + timedelta(hours=1))],
        version="gateway-neutral-test",
    )
    gate = PreRequestGate(
        registry=registry,
        acquirer=MediaAcquirer(asset_store=AssetStore(tmp_path / "assets")),
        ocr_backend=FakeOcr(),
        vision_backend=FakeVision(),
        receipt_signer=signer,
        pdf_renderer=FakePdfRenderer(),
        now=lambda: now,
    )
    downstream = FakeDownstream()
    return (
        GatewayTransaction(
            gate=gate,
            downstream=downstream,
            receipt_signer=signer,
            state_store=ResponsesStateStore(clock=lambda: now.timestamp()),
            snapshot_version=7,
        ),
        downstream,
    )


def _subject() -> DataPlaneSubject:
    return DataPlaneSubject(
        credential_selector="mbc-selector",
        tenant_id="tenant-a",
        scopes=frozenset({"responses:invoke"}),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"model": "text-model", "input": "hello"},
        {
            "model": "text-model",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": "data:image/png;base64,"
                            + base64.b64encode(_png()).decode(),
                        }
                    ],
                }
            ],
        },
        {
            "model": "text-model",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "file_data": "data:application/pdf;base64,"
                            + base64.b64encode(_pdf()).decode(),
                            "filename": "error.pdf",
                        }
                    ],
                }
            ],
        },
    ],
)
async def test_product_neutral_transaction_handles_text_image_and_pdf(
    tmp_path: Path,
    payload: dict[str, object],
) -> None:
    transaction, downstream = _transaction(tmp_path)

    result = await transaction.invoke(payload, subject=_subject())

    assert result.status == "completed"
    assert len(downstream.requests) == 1
    sealed = downstream.requests[0]
    assert sealed.snapshot_version == 7
    serialized = json.dumps(sealed.payload)
    if "data:" in json.dumps(payload):
        assert "data:" not in serialized
        assert "input_image" not in serialized
        assert "input_file" not in serialized
        assert "ERROR 104" in serialized
        assert "red terminal" in serialized
    else:
        assert sealed.payload == payload
