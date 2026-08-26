from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from media_bridge.contracts_v2 import (
    AssetReference,
    HopMetadata,
    InteropV2Request,
    TargetCapabilitySnapshot,
)
from media_bridge.router import V2ResponsibilityRouter
from media_bridge_adapters.contracts import ResponsibilityMode


def _request(
    *, mode: str, fresh_until: datetime, host_id: str | None = "host-a"
) -> InteropV2Request:
    return InteropV2Request(
        contract_version="media-bridge-interop/v2",
        request_id="request",
        trace_id="trace",
        idempotency_key="idempotency",
        mode=mode,
        host_id=host_id,
        canonical_messages=[{"role": "user", "content": "describe"}],
        assets=[AssetReference(asset_id="asset-1", media_type_hint="image")],
        target=TargetCapabilitySnapshot(
            model_id="model",
            capability_snapshot_version="v1",
            capability_snapshot_digest="sha256:" + "a" * 64,
            capabilities={"vision": False},
            observed_at=datetime.now(UTC),
            fresh_until=fresh_until,
        ),
        hop=HopMetadata(hop_id="hop"),
    )


def test_host_managed_request_requires_host_identity() -> None:
    with pytest.raises(ValidationError):
        _request(
            mode="host_managed",
            host_id=None,
            fresh_until=datetime.now(UTC) + timedelta(minutes=1),
        )


def test_eoul_alias_normalizes_to_generic_host_managed_profile() -> None:
    request = _request(mode="eoul", fresh_until=datetime.now(UTC) + timedelta(minutes=1))

    assert request.normalized_mode == "host_managed"
    assert request.normalized_owner == "external_host"
    assert request.host_id == "host-a"


def test_host_managed_responsibility_uses_external_host_owner() -> None:
    mode = ResponsibilityMode(
        mode="host_managed",
        host_id="host-a",
        capability_owner="external_host",
        routing_owner="external_host",
        provider_execution_owner="external_host",
    )

    assert mode.normalized_mode == "host_managed"
    assert mode.normalized_owner == "external_host"


def test_host_managed_stale_capability_blocks_before_transform() -> None:
    request = _request(mode="host_managed", fresh_until=datetime.now(UTC) - timedelta(seconds=1))
    called = False

    def transform(_request: InteropV2Request):
        nonlocal called
        called = True
        raise AssertionError("stale capability must stop before transform")

    decision = V2ResponsibilityRouter().prepare(request, transform=transform)

    assert decision.result.status == "BLOCKED"
    assert decision.result.error is not None
    assert decision.result.error.code.value == "CAPABILITY_STALE"
    assert decision.provider_call_allowed is False
    assert called is False
