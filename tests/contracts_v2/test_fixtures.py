import json
from pathlib import Path

from media_bridge.contracts_v2 import InteropV2Result, provider_call_allowed


def test_v2_fixtures_validate_and_preserve_fail_closed_states() -> None:
    root = Path(__file__).parent / "fixtures"
    prepared = InteropV2Result.model_validate(json.loads((root / "v2-prepared.json").read_text()))
    blocked = InteropV2Result.model_validate(json.loads((root / "v2-blocked.json").read_text()))
    failed = InteropV2Result.model_validate(json.loads((root / "v2-failed.json").read_text()))
    assert provider_call_allowed(prepared)
    assert not provider_call_allowed(blocked)
    assert not provider_call_allowed(failed)
