from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from media_bridge.contracts_v2 import (
    InteropV2Request,
    MediaBridgeV2ErrorCode,
    TargetCapabilitySnapshot,
)


def _request(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "contract_version": "media-bridge-interop/v2",
        "request_id": "req_123",
        "trace_id": "trace_123",
        "idempotency_key": "idem_123",
        "mode": "eoul",
        "canonical_messages": [{"role": "user", "content": "hello"}],
        "assets": [],
        "target": {
            "model_id": "provider/model",
            "capability_snapshot_version": "snapshot-1",
            "capability_snapshot_digest": "sha256:" + "a" * 64,
            "capabilities": {"vision": False, "input_modalities": ["text"]},
            "observed_at": "2026-08-26T00:00:00Z",
            "fresh_until": "2099-08-26T00:00:00Z",
        },
        "transformation_policy": {"profile": "default", "allowed_output_modalities": ["text"]},
        "original_retention": "delete_after_transform",
        "hop": {"hop_id": "hop-1", "visited_gateways": ["eoul"], "max_hops": 2},
    }
    value.update(overrides)
    return value


def test_v2_request_accepts_capability_snapshot_and_policy() -> None:
    request = InteropV2Request.model_validate(_request())
    assert request.contract_version == "media-bridge-interop/v2"
    assert request.target.model_id == "provider/model"
    assert request.target.is_fresh(datetime.now(UTC))


def test_v2_request_rejects_unknown_contract_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        InteropV2Request.model_validate(_request(contract_version="media-bridge-interop/v3"))
    with pytest.raises(ValidationError):
        InteropV2Request.model_validate(_request(unreviewed=True))


def test_v2_request_rejects_stale_capability_snapshot() -> None:
    stale = TargetCapabilitySnapshot(
        model_id="provider/model",
        capability_snapshot_version="snapshot-1",
        capability_snapshot_digest="sha256:" + "a" * 64,
        capabilities={"vision": False},
        observed_at=datetime.now(UTC) - timedelta(minutes=10),
        fresh_until=datetime.now(UTC) - timedelta(minutes=1),
    )
    assert not stale.is_fresh(datetime.now(UTC))


def test_stable_error_codes_are_explicit() -> None:
    assert MediaBridgeV2ErrorCode.ORIGINAL_MEDIA_REMAINS.value == "ORIGINAL_MEDIA_REMAINS"
