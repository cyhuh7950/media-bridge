from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "deploy" / "staging" / "compose.a1.yaml"
MOCK = ROOT / "deploy" / "staging" / "mock_provider.py"


def _render() -> dict[str, object]:
    docker = shutil.which("docker")
    assert docker is not None
    result = subprocess.run(  # noqa: S603
        [
            docker,
            "compose",
            "--project-name",
            "media-bridge-staging",
            "-f",
            str(ROOT / "deploy" / "compose.yaml"),
            "-f",
            str(OVERLAY),
            "config",
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "MEDIA_BRIDGE_STAGING_ROOT": "/run/media-bridge-staging-test",
            "MEDIA_BRIDGE_CONTROL_ORIGIN": "https://media-bridge-staging.sinsan.kr",
            "MEDIA_BRIDGE_CONTROL_HOST": "media-bridge-staging.sinsan.kr",
            "MEDIA_BRIDGE_OCR_ENDPOINT": "https://media-bridge-staging-mock:8443/v1/document-digitization",
            "MEDIA_BRIDGE_VISION_ENDPOINT": "https://media-bridge-staging-mock:8443/v1/chat/completions",
            "MEDIA_BRIDGE_DOWNSTREAM_RESPONSES_URL": "https://media-bridge-staging-mock:8443/v1/responses",
        },
    )
    return json.loads(result.stdout)


def test_a1_overlay_isolates_db_edge_and_mock_networks() -> None:
    rendered = _render()
    services = rendered["services"]
    assert set(services) == {
        "media-bridge-control",
        "media-bridge-data",
        "media-bridge-db",
        "media-bridge-staging-mock",
    }
    assert services["media-bridge-db"].get("ports", []) == []
    assert set(services["media-bridge-db"]["networks"]) == {"database"}
    assert "edge" in services["media-bridge-control"]["networks"]
    control_secret_sources = {
        secret["source"] for secret in services["media-bridge-control"]["secrets"]
    }
    assert "gateway_client_credential" in control_secret_sources
    assert rendered["secrets"]["gateway_client_credential"]["file"] == (
        "/run/media-bridge-staging-test/secrets/client-credential.secret"
    )
    assert services["media-bridge-control"]["environment"]["FORWARDED_ALLOW_IPS"] == (
        "172.20.0.2"
    )
    assert services["media-bridge-control"]["environment"][
        "MEDIA_BRIDGE_CONTROL_PORT"
    ] == "8381"
    assert "8381" in " ".join(services["media-bridge-control"]["healthcheck"]["test"])
    assert "edge" in services["media-bridge-data"]["networks"]
    assert services["media-bridge-data"]["environment"][
        "MEDIA_BRIDGE_GATEWAY_PORT"
    ] == "8301"
    assert "8301" in " ".join(
        services["media-bridge-data"]["healthcheck"]["test"]
    )
    assert "mock" not in services["media-bridge-control"]["networks"]
    assert "mock" in services["media-bridge-data"]["networks"]
    assert set(services["media-bridge-staging-mock"]["networks"]) == {"mock"}
    assert services["media-bridge-staging-mock"].get("ports", []) == []
    assert rendered["networks"]["edge"]["external"] is True
    assert rendered["networks"]["edge"]["name"] == "proxy-network"


def test_a1_mock_is_internal_non_root_read_only_and_bodyless_logging() -> None:
    rendered = _render()
    mock = rendered["services"]["media-bridge-staging-mock"]
    assert mock["user"] == "10001:10001"
    assert mock["read_only"] is True
    assert mock["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in mock["security_opt"]
    assert mock.get("ports", []) == []
    source = MOCK.read_text(encoding="utf-8")
    assert "def log_message" in source
    assert "self.rfile.read" in source
    assert "request_body" not in source
    assert "raw_body" not in source
    assert "prompt_body" not in source


def test_a1_data_uses_file_secrets_and_internal_tls_mock_only() -> None:
    rendered = _render()
    data = rendered["services"]["media-bridge-data"]
    environment = data["environment"]
    assert environment["MEDIA_BRIDGE_OCR_ENDPOINT"].startswith(
        "https://media-bridge-staging-mock:8443/"
    )
    assert environment["MEDIA_BRIDGE_VISION_ENDPOINT"].startswith(
        "https://media-bridge-staging-mock:8443/"
    )
    assert environment["MEDIA_BRIDGE_DOWNSTREAM_RESPONSES_URL"].startswith(
        "https://media-bridge-staging-mock:8443/"
    )
    assert environment["MEDIA_BRIDGE_DOWNSTREAM_API_KEY_FILE"] == (
        "/run/secrets/downstream_api_key"
    )
    assert environment["SSL_CERT_FILE"] == "/run/secrets/mock_ca_certificate"
    assert environment["MEDIA_BRIDGE_BACKEND_CA_FILE"] == (
        "/run/secrets/mock_ca_certificate"
    )
    serialized = yaml.safe_dump(rendered)
    assert "MEDIA_BRIDGE_DOWNSTREAM_API_KEY=" not in serialized
