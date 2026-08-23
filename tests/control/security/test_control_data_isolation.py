from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from media_bridge.acquisition import MediaAcquirer
from media_bridge.assets import AssetStore
from media_bridge.backends import OcrResult, VisionResult
from media_bridge.capabilities import CapabilityRegistry, ModelCapability
from media_bridge.contracts import PrepareForModelRequest, TargetModel, TextPart
from media_bridge.gate import PreRequestGate
from media_bridge.receipts import GateReceiptSigner
from media_bridge.router import DownstreamRequest, GuardedDownstream, RouterAdapter
from media_bridge_control.api import build_control_app
from media_bridge_control.bootstrap import ControlPlaneService
from media_bridge_control.db import Database
from media_bridge_control.models import User
from media_bridge_control.security import SecurityContext


class UnusedOcr:
    async def extract(self, *, data: bytes, mime_type: str, filename: str | None) -> OcrResult:
        raise AssertionError("text request must not invoke OCR")


class UnusedVision:
    async def describe(self, *, data: bytes, mime_type: str, profile: str) -> VisionResult:
        raise AssertionError("text request must not invoke Vision")


class CountingDownstream:
    def __init__(self) -> None:
        self.calls = 0

    async def invoke(self, request: DownstreamRequest) -> object:
        self.calls += 1
        return {"target": request.target_id}


@pytest.mark.asyncio
async def test_control_plane_forbidden_response_does_not_touch_core_or_downstream(
    migrated_postgres: str,
    tmp_path: Path,
) -> None:
    database = Database(migrated_postgres)
    security = SecurityContext(pepper=b"i" * 32)
    service = ControlPlaneService(
        database=database,
        security=security,
        now=lambda: datetime(2026, 8, 24, 5, 0, tzinfo=UTC),
    )
    token = service.issue_bootstrap_token()
    value = "correct horse battery staple"
    service.complete_bootstrap(token=token, username="admin", password=value)
    with database.session() as session:
        session.add(
            User(
                username="viewer",
                password_hash=security.passwords.hash(value),
                role="viewer",
                is_active=True,
            )
        )
    client = TestClient(
        build_control_app(
            service=service,
            allowed_origin="https://control.test",
            allowed_host="control.test",
        ),
        base_url="https://control.test",
    )
    login = client.post(
        "/admin/v1/auth/login",
        headers={"origin": "https://control.test"},
        json={"username": "viewer", "password": value},
    )

    downstream = CountingDownstream()
    signer = GateReceiptSigner(secret=b"g" * 32)
    registry = CapabilityRegistry(
        [
            ModelCapability(
                model_id="vendor/text-model",
                input_modalities={"text"},
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        ],
        version="test",
    )
    gate = PreRequestGate(
        registry=registry,
        acquirer=MediaAcquirer(asset_store=AssetStore(tmp_path / "assets")),
        ocr_backend=UnusedOcr(),
        vision_backend=UnusedVision(),
        receipt_signer=signer,
    )
    router = RouterAdapter(gate=gate, downstream=GuardedDownstream(downstream, signer))

    assert login.status_code == 200
    assert client.get("/admin/v1/users").status_code == 403
    assert downstream.calls == 0
    result = await router.invoke(
        PrepareForModelRequest(
            content=[TextPart(text="continue")],
            target=TargetModel(registry_id="vendor/text-model"),
        ),
        tenant_id="tenant_a",
    )
    assert result.gate_result.action == "passthrough"
    assert downstream.calls == 1
    database.close()
