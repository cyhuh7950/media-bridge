from datetime import UTC, datetime, timedelta

from media_bridge.contracts_v2 import (
    AssetReference,
    HopMetadata,
    InteropV2Request,
    TargetCapabilitySnapshot,
)
from media_bridge_adapters.contracts import ResponsibilityMode
from media_bridge.router import V2ResponsibilityRouter


def make_request(vision: object) -> InteropV2Request:
    now = datetime.now(UTC)
    return InteropV2Request(
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
            capabilities={"vision": vision} if isinstance(vision, bool) else {},
            observed_at=now,
            fresh_until=now + timedelta(seconds=30),
        ),
        hop=HopMetadata(hop_id="hop"),
    )


def test_native_vision_bypasses_bridge() -> None:
    called = False

    def transform(_):
        nonlocal called
        called = True
        raise AssertionError("native vision must not invoke bridge")

    decision = V2ResponsibilityRouter().prepare(make_request(True), transform=transform)
    assert decision.result.status == "UNCHANGED"
    assert decision.bridge_called is False
    assert decision.provider_call_allowed is True
    assert called is False


def test_unknown_capability_is_fail_closed() -> None:
    decision = V2ResponsibilityRouter().prepare(make_request("unknown"), transform=lambda _: None)
    assert decision.result.status == "BLOCKED"
    assert decision.result.error is not None
    assert decision.result.error.code == "CAPABILITY_UNKNOWN"
    assert decision.provider_call_allowed is False


def test_eoul_mode_cannot_claim_media_bridge_routing_ownership() -> None:
    try:
        ResponsibilityMode(
            mode="eoul",
            capability_owner="media_bridge",
            routing_owner="media_bridge",
            provider_execution_owner="media_bridge",
        )
    except ValueError as error:
        assert "Eoul mode" in str(error)
    else:
        raise AssertionError("invalid Eoul responsibility ownership was accepted")
