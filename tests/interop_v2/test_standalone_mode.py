from datetime import UTC, datetime, timedelta

from media_bridge.contracts_v2 import (
    AssetReference,
    BackendEvidence,
    ConfidenceEvidence,
    HopMetadata,
    InformationLossEvidence,
    InteropV2Request,
    InteropV2Result,
    PreparedMarker,
    ProvenanceEvidence,
    TargetCapabilitySnapshot,
    TokenEstimate,
    TransformationEvidence,
    TransformationPolicy,
)
from media_bridge.router import V2ResponsibilityRouter


def request(*, mode: str = "standalone", vision: bool = False) -> InteropV2Request:
    now = datetime.now(UTC)
    return InteropV2Request(
        contract_version="media-bridge-interop/v2",
        request_id="request",
        trace_id="trace",
        idempotency_key="idempotency",
        mode=mode,
        canonical_messages=[{"role": "user", "content": "describe"}],
        assets=[AssetReference(asset_id="asset-1", media_type_hint="image")],
        target=TargetCapabilitySnapshot(
            model_id="model",
            capability_snapshot_version="v1",
            capability_snapshot_digest="sha256:" + "a" * 64,
            capabilities={"vision": vision},
            observed_at=now,
            fresh_until=now + timedelta(seconds=30),
        ),
        transformation_policy=TransformationPolicy(),
        hop=HopMetadata(hop_id="hop"),
    )


def prepared(input_request: InteropV2Request) -> InteropV2Result:
    now = datetime.now(UTC)
    digest = "sha256:" + "b" * 64
    return InteropV2Result(
        contract_version="media-bridge-interop/v2",
        status="PREPARED",
        request_id=input_request.request_id,
        trace_id=input_request.trace_id,
        idempotency_key=input_request.idempotency_key,
        sanitized_messages=[{"role": "user", "content": "safe"}],
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
        confidence=ConfidenceEvidence(overall=0.9),
        information_loss=InformationLossEvidence(present=False),
        required_capabilities_after={},
        token_estimate=TokenEstimate(input=1, method="estimate"),
        prepared_marker=PreparedMarker(
            schema_digest=digest,
            expires_at=now + timedelta(seconds=20),
        ),
    )


def test_standalone_non_vision_calls_bridge_and_allows_text_only_provider() -> None:
    calls = 0

    def transform(value: InteropV2Request) -> InteropV2Result:
        nonlocal calls
        calls += 1
        return prepared(value)

    decision = V2ResponsibilityRouter().prepare(request(), transform=transform)
    assert calls == 1
    assert decision.bridge_called is True
    assert decision.provider_call_allowed is True
    assert decision.result.status == "PREPARED"
