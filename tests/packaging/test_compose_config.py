from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"


def _compose() -> dict[str, object]:
    return yaml.safe_load((DEPLOY / "compose.yaml").read_text(encoding="utf-8"))


def test_compose_has_three_isolated_services() -> None:
    config = _compose()
    services = config["services"]
    assert set(services) == {"media-bridge-db", "media-bridge-control", "media-bridge-data"}
    assert "ports" not in services["media-bridge-db"]
    assert config["networks"]["database"]["internal"] is True
    assert set(services["media-bridge-db"]["networks"]) == {"database"}
    assert set(services["media-bridge-data"]["networks"]) == {"product", "egress"}
    assert set(services["media-bridge-control"]["networks"]) == {"database", "product"}


def test_compose_applies_runtime_confinement() -> None:
    services = _compose()["services"]
    for name, service in services.items():
        assert service["read_only"] is True, name
        assert service["security_opt"] == ["no-new-privileges:true"], name
        assert service["cap_drop"] == ["ALL"], name
        assert service["pids_limit"] <= 256, name
        assert service["tmpfs"], name
        assert service["healthcheck"]["test"][0] == "CMD", name


def test_snapshot_is_rw_for_control_and_ro_for_data() -> None:
    services = _compose()["services"]
    assert "snapshots:/var/lib/media-bridge/snapshots" in services["media-bridge-control"]["volumes"]
    assert (
        "snapshots:/var/lib/media-bridge/snapshots:ro"
        in services["media-bridge-data"]["volumes"]
    )
    assert "media-bridge-control" not in services["media-bridge-data"].get("depends_on", {})


def test_compose_uses_secret_files_not_literal_values() -> None:
    config = _compose()
    for secret in config["secrets"].values():
        assert set(secret) == {"file"}
    serialized = (DEPLOY / "compose.yaml").read_text(encoding="utf-8")
    assert "PASSWORD=" not in serialized
    assert "PRIVATE_KEY=" not in serialized
    assert ":latest" not in serialized


def test_test_override_only_publishes_loopback_ports() -> None:
    source = (DEPLOY / "compose.test.yaml").read_text(encoding="utf-8")
    assert "127.0.0.1:${MEDIA_BRIDGE_TEST_CONTROL_PORT:-18081}:8081" in source
    assert "127.0.0.1:${MEDIA_BRIDGE_TEST_DATA_PORT:-18001}:8001" in source
    assert "0.0.0.0:" not in source

