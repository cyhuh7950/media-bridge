from __future__ import annotations

import json
from pathlib import Path

import pytest

from media_bridge_adapters.opencodex.manager import OpenCodexConfigError, OpenCodexConfigManager


def manager(tmp_path: Path) -> OpenCodexConfigManager:
    return OpenCodexConfigManager(
        config_path=tmp_path / "config.json",
        marker_path=tmp_path / ".media-bridge-opencodex.json",
    )


def test_apply_writes_env_reference_and_owned_marker_then_remove_restores_clean_config(
    tmp_path: Path,
) -> None:
    item = manager(tmp_path)
    result = item.apply(
        provider_name="solar",
        endpoint="http://127.0.0.1:18081/v1",
        model="solar-test",
        credential_env="MEDIA_BRIDGE_CREDENTIAL",
        tenant_id="local-user",
    )
    payload = json.loads((tmp_path / "config.json").read_text())
    assert result["status"] == "applied"
    assert payload["providers"]["solar"]["apiKey"] == "env:MEDIA_BRIDGE_CREDENTIAL"
    assert payload["providers"]["solar"]["headers"] == {"X-Media-Bridge-Tenant": "local-user"}
    assert "secret" not in (tmp_path / ".media-bridge-opencodex.json").read_text().lower()
    assert item.remove() == {"status": "removed", "provider": "solar"}
    assert json.loads((tmp_path / "config.json").read_text()) == {"providers": {}}
    assert not (tmp_path / ".media-bridge-opencodex.json").exists()


def test_unowned_provider_is_never_overwritten(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(json.dumps({"providers": {"solar": {"baseUrl": "https://user.example/v1"}}}))
    with pytest.raises(OpenCodexConfigError, match="unowned_provider_present"):
        manager(tmp_path).apply(
            provider_name="solar",
            endpoint="http://127.0.0.1:18081/v1",
            model="solar-test",
            credential_env="MEDIA_BRIDGE_CREDENTIAL",
            tenant_id="local-user",
        )


def test_tampered_owned_config_fails_closed_without_restore(tmp_path: Path) -> None:
    item = manager(tmp_path)
    item.apply(
        provider_name="solar",
        endpoint="http://127.0.0.1:18081/v1",
        model="solar-test",
        credential_env="MEDIA_BRIDGE_CREDENTIAL",
        tenant_id="local-user",
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(config_path.read_text().replace("solar-test", "other-model"))
    with pytest.raises(OpenCodexConfigError, match="owned_config_changed"):
        item.remove()
    assert (tmp_path / ".media-bridge-opencodex.json").exists()
