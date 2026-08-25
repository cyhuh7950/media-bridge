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
from media_bridge_gateway.hops import HopGuardError, build_external_provider_messages


def prepared(messages: list[dict[str, object]]) -> InteropV2Result:
    digest = "sha256:" + "a" * 64
    return InteropV2Result(
        contract_version="media-bridge-interop/v2",
        status="PREPARED",
        request_id="request",
        trace_id="trace",
        idempotency_key="idempotency",
        sanitized_messages=messages,
        original_media_removed=True,
        asset_digests=[digest],
        media_types=["image"],
        transformations=[
            TransformationEvidence(
                kind="ocr",
                backend="local",
                version="1",
                input_digest=digest,
                output_digest=digest,
            )
        ],
        backend=BackendEvidence(id="local", version="1"),
        provenance=[ProvenanceEvidence(source="asset", stage="ocr", evidence_digest=digest)],
        confidence=ConfidenceEvidence(overall=1),
        information_loss=InformationLossEvidence(present=False),
        required_capabilities_after={},
        token_estimate=TokenEstimate(input=1, method="estimate"),
        prepared_marker=PreparedMarker(
            schema_digest=digest,
            expires_at=datetime.now(UTC) + timedelta(seconds=20),
        ),
    )


def test_external_wire_drops_internal_metadata() -> None:
    result = prepared([{"role": "user", "content": "safe", "_media_bridge_provenance": "digest"}])
    assert build_external_provider_messages(result) == [{"role": "user", "content": "safe"}]


def test_external_wire_rejects_original_media_reference() -> None:
    result = prepared([{"role": "user", "content": "safe", "asset_id": "asset-1"}])
    with pytest.raises(HopGuardError, match="media reference"):
        build_external_provider_messages(result)


def test_blocked_result_cannot_reach_omniroute_wire() -> None:
    result = prepared([]).model_copy(
        update={
            "status": "BLOCKED",
            "original_media_removed": False,
            "sanitized_messages": [],
            "error": {"code": "POLICY_DENIED", "message": "blocked"},
        }
    )
    with pytest.raises(HopGuardError, match="authorized"):
        build_external_provider_messages(result)
