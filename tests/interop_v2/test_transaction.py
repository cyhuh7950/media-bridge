from datetime import UTC, datetime, timedelta

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
from media_bridge_gateway.transaction import V2PreparationTransaction


def prepared() -> InteropV2Result:
    now = datetime.now(UTC)

    def digest(value: str) -> str:
        return "sha256:" + value * 64

    return InteropV2Result(
        contract_version="media-bridge-interop/v2",
        status="PREPARED",
        request_id="request",
        trace_id="trace",
        idempotency_key="idempotency",
        sanitized_messages=[{"role": "user", "content": "safe"}],
        original_media_removed=True,
        asset_digests=[digest("1")],
        media_types=["image"],
        transformations=[
            TransformationEvidence(
                kind="ocr",
                backend="local",
                version="1",
                input_digest=digest("1"),
                output_digest=digest("2"),
            )
        ],
        backend=BackendEvidence(id="local", version="1"),
        provenance=[ProvenanceEvidence(source="asset", stage="ocr", evidence_digest=digest("3"))],
        confidence=ConfidenceEvidence(overall=1),
        information_loss=InformationLossEvidence(present=False),
        required_capabilities_after={},
        token_estimate=TokenEstimate(input=1, method="estimate"),
        prepared_marker=PreparedMarker(
            schema_digest=digest("4"),
            expires_at=now + timedelta(seconds=60),
        ),
    )


def test_transaction_cleanup_failure_blocks_and_does_not_release_receipt() -> None:
    transaction = V2PreparationTransaction(ttl_seconds=20)
    calls = 0

    def transform() -> InteropV2Result:
        nonlocal calls
        calls += 1
        return prepared()

    result, receipt = transaction.execute(
        idempotency_key="k",
        fingerprint="fp",
        transform=transform,
        cleanup=lambda: False,
    )
    assert calls == 1
    assert result.status == "BLOCKED"
    assert result.error is not None
    assert result.error.code == "ORIGINAL_MEDIA_REMAINS"
    assert receipt is None


def test_transaction_replays_receipt_without_second_transform() -> None:
    transaction = V2PreparationTransaction(ttl_seconds=20)
    calls = 0

    def transform() -> InteropV2Result:
        nonlocal calls
        calls += 1
        return prepared()

    first, first_receipt = transaction.execute(
        idempotency_key="k",
        fingerprint="fp",
        transform=transform,
        cleanup=lambda: True,
    )
    second, second_receipt = transaction.execute(
        idempotency_key="k",
        fingerprint="fp",
        transform=transform,
        cleanup=lambda: True,
    )
    assert calls == 1
    assert first.status == second.status == "PREPARED"
    assert first_receipt == second_receipt
