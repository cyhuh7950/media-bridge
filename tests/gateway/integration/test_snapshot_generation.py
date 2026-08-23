from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from media_bridge.acquisition import MediaAcquirer
from media_bridge.assets import AssetStore
from media_bridge.backends import BackendStatus, OcrResult, VisionResult
from media_bridge.config_snapshot import (
    SignedSnapshot,
    SnapshotVerificationError,
    SnapshotVerifier,
)
from media_bridge.gate import PreRequestGate
from media_bridge.receipts import GateReceiptSigner
from media_bridge.responses_state import ResponsesStateStore
from media_bridge.runtime_snapshot import capability_registry_from_snapshot
from media_bridge_control.snapshots import SnapshotSigner
from media_bridge_gateway.contracts import (
    DataPlaneSubject,
    GatewayResponse,
    SealedGatewayRequest,
)
from media_bridge_gateway.runtime import (
    GatewayTransactionFactory,
    VerifiedSnapshotRuntime,
)
from tests.control.snapshot_helpers import private_key_pem, snapshot_body


class UnusedOcr:
    async def extract(self, **_kwargs: Any) -> OcrResult:
        return OcrResult(BackendStatus.SUCCESS, text="unused")


class UnusedVision:
    async def describe(self, **_kwargs: Any) -> VisionResult:
        return VisionResult(BackendStatus.SUCCESS, description="unused")


class BlockingDownstream:
    def __init__(self, response_id: str) -> None:
        self.response_id = response_id
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.requests: list[SealedGatewayRequest] = []

    async def invoke(self, request: SealedGatewayRequest) -> GatewayResponse:
        self.requests.append(request)
        self.started.set()
        await self.release.wait()
        return GatewayResponse(
            body=(f'{{"id":"{self.response_id}"}}').encode(),
            content_type="application/json",
            response_id=self.response_id,
            status_code=200,
        )


def _signed(signer: SnapshotSigner, version: int, *, model_id: str) -> SignedSnapshot:
    return signer.sign(
        snapshot_id=UUID(f"00000000-0000-0000-0000-{version:012d}"),
        version=version,
        issued_at=datetime(2026, 8, 24, 4, 0, tzinfo=UTC),
        body=snapshot_body(model_id=model_id),
    )


def _subject() -> DataPlaneSubject:
    return DataPlaneSubject(
        credential_selector="mbc-selector",
        tenant_id="tenant-a",
        scopes=frozenset({"responses:invoke"}),
    )


@pytest.mark.asyncio
async def test_request_is_bound_to_generation_while_new_snapshot_is_published(
    tmp_path: Path,
) -> None:
    signer = SnapshotSigner(key_id="gateway-key", private_key_pem=private_key_pem())
    verifier = SnapshotVerifier({"gateway-key": signer.public_key_bytes})
    receipt_signer = GateReceiptSigner(
        secret=b"r" * 32,
        clock=lambda: datetime(2026, 8, 24, tzinfo=UTC).timestamp(),
    )
    downstreams: dict[int, BlockingDownstream] = {}

    def gate_factory(snapshot: Any) -> PreRequestGate:
        return PreRequestGate(
            registry=capability_registry_from_snapshot(snapshot),
            acquirer=MediaAcquirer(asset_store=AssetStore(tmp_path / f"assets-{snapshot.version}")),
            ocr_backend=UnusedOcr(),
            vision_backend=UnusedVision(),
            receipt_signer=receipt_signer,
            now=lambda: datetime(2026, 8, 24, tzinfo=UTC),
        )

    def downstream_factory(snapshot: Any) -> BlockingDownstream:
        downstream = BlockingDownstream(f"resp_v{snapshot.version}")
        downstreams[snapshot.version] = downstream
        return downstream

    factory = GatewayTransactionFactory(
        gate_factory=gate_factory,
        downstream_factory=downstream_factory,
        receipt_signer=receipt_signer,
        state_store_factory=ResponsesStateStore,
    )
    runtime = VerifiedSnapshotRuntime(verifier=verifier, generation_factory=factory)
    snapshot_path = tmp_path / "active-snapshot.json"
    snapshot_path.write_text(_signed(signer, 1, model_id="vendor/model-v1").model_dump_json())
    runtime.load(snapshot_path)

    first_task = asyncio.create_task(
        runtime.invoke(
            {"model": "vendor/model-v1", "input": "first"},
            subject=_subject(),
        )
    )
    await downstreams[1].started.wait()

    snapshot_path.write_text(_signed(signer, 2, model_id="vendor/model-v2").model_dump_json())
    runtime.load(snapshot_path)
    downstreams[1].release.set()
    first = await first_task

    assert first.status == "completed"
    assert downstreams[1].requests[0].snapshot_version == 1
    assert runtime.current().version == 2

    second_task = asyncio.create_task(
        runtime.invoke(
            {"model": "vendor/model-v2", "input": "second"},
            subject=_subject(),
        )
    )
    await downstreams[2].started.wait()
    downstreams[2].release.set()
    second = await second_task
    assert second.status == "completed"
    assert downstreams[2].requests[0].snapshot_version == 2


def test_invalid_or_rollback_snapshot_keeps_last_known_generation(tmp_path: Path) -> None:
    signer = SnapshotSigner(key_id="gateway-key", private_key_pem=private_key_pem())
    verifier = SnapshotVerifier({"gateway-key": signer.public_key_bytes})
    receipt_signer = GateReceiptSigner(secret=b"r" * 32)

    def gate_factory(snapshot: Any) -> PreRequestGate:
        return PreRequestGate(
            registry=capability_registry_from_snapshot(snapshot),
            acquirer=MediaAcquirer(asset_store=AssetStore(tmp_path / "assets")),
            ocr_backend=UnusedOcr(),
            vision_backend=UnusedVision(),
            receipt_signer=receipt_signer,
        )

    factory = GatewayTransactionFactory(
        gate_factory=gate_factory,
        downstream_factory=lambda _snapshot: BlockingDownstream("resp_unused"),
        receipt_signer=receipt_signer,
        state_store_factory=ResponsesStateStore,
    )
    runtime = VerifiedSnapshotRuntime(verifier=verifier, generation_factory=factory)
    snapshot_path = tmp_path / "active-snapshot.json"
    valid = _signed(signer, 2, model_id="vendor/model-v2")
    snapshot_path.write_text(valid.model_dump_json())
    runtime.load(snapshot_path)

    tampered = valid.model_copy(update={"digest": "sha256:" + "0" * 64})
    snapshot_path.write_text(tampered.model_dump_json())
    with pytest.raises(SnapshotVerificationError):
        runtime.load(snapshot_path)
    assert runtime.current().version == 2

    snapshot_path.write_text(_signed(signer, 1, model_id="vendor/model-v1").model_dump_json())
    with pytest.raises(SnapshotVerificationError, match="stale|replayed"):
        runtime.load(snapshot_path)
    assert runtime.current().version == 2
