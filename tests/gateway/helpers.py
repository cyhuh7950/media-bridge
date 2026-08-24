from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID

from PIL import Image

from media_bridge.acquisition import MediaAcquirer
from media_bridge.assets import AssetStore
from media_bridge.backends import BackendStatus, OcrResult, VisionResult
from media_bridge.config_snapshot import SnapshotVerifier
from media_bridge.gate import PreRequestGate
from media_bridge.receipts import GateReceiptSigner
from media_bridge.runtime_snapshot import capability_registry_from_snapshot
from media_bridge_control.snapshots import SnapshotSigner
from media_bridge_gateway.contracts import GatewayResponse, SealedGatewayRequest
from media_bridge_gateway.runtime import GatewayTransactionFactory, VerifiedSnapshotRuntime
from media_bridge_gateway.state import GatewayStateStore
from tests.control.snapshot_helpers import private_key_pem

TEST_PEPPER = b"p" * 32
TEST_RAW_CREDENTIAL = "mbc_gateway-client.super-secret-value"


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (2, 2), color="blue").save(output, format="PNG")
    return output.getvalue()


def image_uri() -> str:
    return "data:image/png;base64," + base64.b64encode(png_bytes()).decode()


class FakeOcr:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def extract(self, **_kwargs: Any) -> OcrResult:
        self.calls += 1
        if self.fail:
            return OcrResult(BackendStatus.FAILURE, error_code="timeout")
        return OcrResult(BackendStatus.SUCCESS, text="ERROR 104")


class FakeVision:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def describe(self, **_kwargs: Any) -> VisionResult:
        self.calls += 1
        if self.fail:
            return VisionResult(BackendStatus.FAILURE, error_code="timeout")
        return VisionResult(BackendStatus.SUCCESS, description="A red terminal error")


class RecordingDownstream:
    def __init__(self) -> None:
        self.requests: list[SealedGatewayRequest] = []

    async def invoke(self, request: SealedGatewayRequest) -> GatewayResponse:
        self.requests.append(request)
        if request.payload.get("stream") is True:
            return GatewayResponse(
                body=(
                    b"event: response.created\n"
                    b'data: {"type":"response.created","response":{"id":"resp_gateway"}}\n\n'
                    b"data: [DONE]\n\n"
                ),
                content_type="text/event-stream",
                response_id="resp_gateway",
                status_code=200,
            )
        return GatewayResponse(
            body=b'{"id":"resp_gateway","output":[]}',
            content_type="application/json",
            response_id="resp_gateway",
            status_code=200,
        )


def build_test_runtime(
    tmp_path: Path,
    *,
    ocr: FakeOcr | None = None,
    vision: FakeVision | None = None,
    sanitizer: Any = None,
    workspace_factory: Any = None,
) -> tuple[VerifiedSnapshotRuntime, RecordingDownstream, AssetStore]:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    signer = SnapshotSigner(key_id="gateway-key", private_key_pem=private_key_pem())
    verifier = SnapshotVerifier({"gateway-key": signer.public_key_bytes})
    digest = hmac.new(
        TEST_PEPPER,
        f"client_credential\0{TEST_RAW_CREDENTIAL}".encode(),
        hashlib.sha256,
    ).hexdigest()
    body: dict[str, object] = {
        "registry": {
            "version": "gateway-app-test",
            "models": [
                {
                    "id": "text-model",
                    "input_modalities": ["text"],
                    "expires_at": (now + timedelta(hours=1)).isoformat(),
                    "pdf_passthrough_verified": False,
                },
                {
                    "id": "vision-model",
                    "input_modalities": ["text", "image", "pdf"],
                    "expires_at": (now + timedelta(hours=1)).isoformat(),
                    "pdf_passthrough_verified": True,
                },
                {
                    "id": "stale-model",
                    "input_modalities": ["text"],
                    "expires_at": (now - timedelta(seconds=1)).isoformat(),
                    "pdf_passthrough_verified": False,
                },
            ],
        },
        "providers": [],
        "policy": {"name": "default", "fail_closed": True},
        "data_plane_auth": {
            "entries": [
                {
                    "selector": "gateway-client",
                    "digest": digest,
                    "scopes": ["assets:write", "mcp:invoke", "responses:invoke"],
                    "expires_at": (now + timedelta(days=30)).isoformat(),
                    "revoked": False,
                }
            ]
        },
    }
    snapshot = signer.sign(
        snapshot_id=UUID("00000000-0000-0000-0000-000000000001"),
        version=1,
        issued_at=now,
        body=body,
    )
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(snapshot.model_dump_json(), encoding="utf-8")
    receipt_signer = GateReceiptSigner(secret=b"r" * 32, clock=lambda: now.timestamp())
    asset_store = AssetStore(tmp_path / "assets")
    downstream = RecordingDownstream()

    def gate_factory(candidate: Any) -> PreRequestGate:
        return PreRequestGate(
            registry=capability_registry_from_snapshot(candidate),
            acquirer=MediaAcquirer(asset_store=asset_store),
            ocr_backend=ocr or FakeOcr(),
            vision_backend=vision or FakeVision(),
            receipt_signer=receipt_signer,
            sanitizer=sanitizer,
            workspace_factory=workspace_factory,
            now=lambda: now,
        )

    factory = GatewayTransactionFactory(
        gate_factory=gate_factory,
        downstream_factory=lambda _snapshot: downstream,
        receipt_signer=receipt_signer,
        state_store_factory=GatewayStateStore,
        credential_pepper=TEST_PEPPER,
    )
    runtime = VerifiedSnapshotRuntime(verifier=verifier, generation_factory=factory)
    runtime.load(snapshot_path)
    return runtime, downstream, asset_store
