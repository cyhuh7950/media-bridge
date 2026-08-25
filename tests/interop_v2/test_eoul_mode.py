from datetime import UTC, datetime, timedelta

from media_bridge.contracts_v2 import (
    AssetReference,
    HopMetadata,
    InteropV2Request,
    TargetCapabilitySnapshot,
)
from media_bridge.router import V2ResponsibilityRouter


def test_eoul_stale_capability_blocks_before_bridge() -> None:
    now = datetime.now(UTC)
    request = InteropV2Request(
        contract_version="media-bridge-interop/v2",
        request_id="request",
        trace_id="trace",
        idempotency_key="idempotency",
        mode="eoul",
        canonical_messages=[{"role": "user", "content": "describe"}],
        assets=[AssetReference(asset_id="asset-1", media_type_hint="image")],
        target=TargetCapabilitySnapshot(
            model_id="model",
            capability_snapshot_version="v1",
            capability_snapshot_digest="sha256:" + "a" * 64,
            capabilities={"vision": False},
            observed_at=now - timedelta(minutes=10),
            fresh_until=now - timedelta(seconds=1),
        ),
        hop=HopMetadata(hop_id="hop"),
    )
    called = False

    def transform(_: InteropV2Request):
        nonlocal called
        called = True
        raise AssertionError("stale capability must stop before transform")

    decision = V2ResponsibilityRouter().prepare(request, transform=transform)
    assert decision.result.status == "BLOCKED"
    assert decision.result.error is not None
    assert decision.result.error.code == "CAPABILITY_STALE"
    assert decision.provider_call_allowed is False
    assert called is False
