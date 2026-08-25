from datetime import UTC, datetime, timedelta

import pytest

from media_bridge.contracts_v2 import (
    BackendEvidence,
    ConfidenceEvidence,
    InformationLossEvidence,
    InteropV2Result,
    PreparedMarker,
    ProvenanceEvidence,
    TokenEstimate,
    TransformationEvidence,
)
from media_bridge.interop_v2 import (
    CleanupBarrier,
    ReceiptValidationError,
    build_transformation_receipt,
)


def _prepared() -> InteropV2Result:
    now = datetime.now(UTC)
    return InteropV2Result(
        contract_version="media-bridge-interop/v2",
        status="PREPARED",
        request_id="req-1",
        trace_id="trace-1",
        idempotency_key="idem-1",
        sanitized_messages=[{"role": "user", "content": "safe text"}],
        original_media_removed=True,
        asset_digests=["sha256:" + "1" * 64],
        media_types=["image"],
        transformations=[
            TransformationEvidence(
                kind="ocr",
                backend="local",
                version="1",
                input_digest="sha256:" + "1" * 64,
                output_digest="sha256:" + "2" * 64,
            )
        ],
        backend=BackendEvidence(id="local", version="1"),
        provenance=[
            ProvenanceEvidence(
                source="asset",
                stage="ocr",
                evidence_digest="sha256:" + "3" * 64,
            )
        ],
        confidence=ConfidenceEvidence(overall=0.9),
        information_loss=InformationLossEvidence(present=False),
        required_capabilities_after={},
        token_estimate=TokenEstimate(input=3, method="estimate"),
        prepared_marker=PreparedMarker(
            schema_digest="sha256:" + "4" * 64,
            expires_at=now + timedelta(seconds=60),
        ),
    )


def test_receipt_contains_digest_only_and_respects_ttl() -> None:
    now = datetime.now(UTC)
    receipt = build_transformation_receipt(_prepared(), now=now, ttl_seconds=30)
    assert receipt.input_digest.startswith("sha256:")
    assert receipt.output_digest.startswith("sha256:")
    assert receipt.expires_at == now + timedelta(seconds=30)
    assert "safe text" not in receipt.safe_dict()


def test_receipt_rejects_media_remaining_or_digest_mismatch() -> None:
    result = _prepared().model_copy(update={"original_media_removed": False})
    with pytest.raises(ReceiptValidationError):
        build_transformation_receipt(result)

    with pytest.raises(ReceiptValidationError):
        build_transformation_receipt(_prepared(), expected_schema_digest="sha256:" + "9" * 64)


def test_cleanup_barrier_requires_every_asset_and_verified_deletion() -> None:
    barrier = CleanupBarrier(["asset-a", "asset-b"])
    barrier.mark_deleted("asset-a", verified=True)
    with pytest.raises(ReceiptValidationError):
        barrier.finalize()
    barrier.mark_deleted("asset-b", verified=False)
    with pytest.raises(ReceiptValidationError):
        barrier.finalize()
    barrier.mark_deleted("asset-b", verified=True)
    assert barrier.finalize() is True
