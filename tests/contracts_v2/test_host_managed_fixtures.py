import json
from pathlib import Path

from media_bridge.contracts_v2 import InteropV2Request

FIXTURE_ROOT = Path(__file__).parents[1] / "conformance" / "fixtures" / "media-bridge" / "v2"


def test_canonical_host_managed_prepared_fixture_has_generic_owner_boundary() -> None:
    payload = json.loads((FIXTURE_ROOT / "v2-host-managed-prepared.json").read_text())
    request = InteropV2Request.model_validate(payload)

    assert request.mode == "host_managed"
    assert request.normalized_mode == "host_managed"
    assert request.normalized_owner == "external_host"
    assert request.host_id == "host-fixture"


def test_canonical_host_managed_blocked_fixture_preserves_stale_capability_input() -> None:
    payload = json.loads((FIXTURE_ROOT / "v2-host-managed-blocked.json").read_text())
    expected_error = payload.pop("expected_error")
    request = InteropV2Request.model_validate(payload)

    assert request.normalized_mode == "host_managed"
    assert request.target.is_fresh() is False
    assert expected_error == "CAPABILITY_STALE"
