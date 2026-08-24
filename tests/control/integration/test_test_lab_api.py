from __future__ import annotations

import base64

from starlette.testclient import TestClient

from media_bridge_control.api import build_control_app
from media_bridge_control.secrets import GatewaySecretResolver
from tests.control.p2b_helpers import StubGatewayClient, configured_control, sample_password
from tests.gateway.helpers import png_bytes


def _preview_payload() -> dict[str, object]:
    return {
        "connection_id": "",
        "target_model": "text-model",
        "conversion_profile": "error_screenshot",
        "user_request": "이 오류를 설명해줘",
        "media_type": "image",
        "filename": "error.png",
        "declared_mime": "image/png",
        "media_base64": base64.b64encode(png_bytes()).decode(),
    }


def test_preview_has_zero_downstream_and_run_requires_literal_opt_in(
    migrated_postgres: str,
    monkeypatch: object,
) -> None:
    monkeypatch.setenv(
        "MEDIA_BRIDGE_GATEWAY_CREDENTIAL",
        "mbc_gateway.external-value",
    )
    database, service = configured_control(migrated_postgres)
    gateway = StubGatewayClient()
    app = build_control_app(
        service=service,
        allowed_origin="https://control.test",
        allowed_host="control.test",
        gateway_client=gateway,
        secret_resolver=GatewaySecretResolver(),
    )
    client = TestClient(app, base_url="https://control.test")
    login = client.post(
        "/admin/v1/auth/login",
        headers={"origin": "https://control.test"},
        json={"username": "admin", "password": sample_password()},
    )
    headers = {
        "origin": "https://control.test",
        "x-csrf-token": login.json()["csrf_token"],
    }
    created = client.post(
        "/admin/v1/connections",
        headers=headers,
        json={
            "name": "primary-gateway",
            "gateway_url": "https://gateway.example.test",
            "credential_secret_ref": {
                "kind": "env",
                "identifier": "MEDIA_BRIDGE_GATEWAY_CREDENTIAL",
            },
        },
    )
    payload = {**_preview_payload(), "connection_id": created.json()["id"]}

    preview = client.post("/admin/v1/test-lab/preview", headers=headers, json=payload)
    assert preview.status_code == 200
    assert preview.json()["action"] == "converted"
    assert preview.json()["original_image_removed"] is True
    assert gateway.calls == ["upload", "prepare", "delete"]
    assert "responses" not in gateway.calls

    missing_opt_in = client.post(
        "/admin/v1/test-lab/run",
        headers=headers,
        json=payload,
    )
    false_opt_in = client.post(
        "/admin/v1/test-lab/run",
        headers=headers,
        json={**payload, "execute_downstream": False},
    )
    assert missing_opt_in.status_code == 400
    assert false_opt_in.status_code == 400
    assert gateway.calls == ["upload", "prepare", "delete"]

    run = client.post(
        "/admin/v1/test-lab/run",
        headers=headers,
        json={**payload, "execute_downstream": True},
    )
    assert run.status_code == 200
    assert run.json()["id"] == "resp_test"
    assert gateway.calls[-3:] == ["upload", "responses", "delete"]
    database.close()


def test_preview_failure_still_attempts_cleanup_and_returns_only_safe_error(
    migrated_postgres: str,
    monkeypatch: object,
) -> None:
    monkeypatch.setenv(
        "MEDIA_BRIDGE_GATEWAY_CREDENTIAL",
        "mbc_gateway.raw-marker-never-return",
    )
    database, service = configured_control(migrated_postgres)
    gateway = StubGatewayClient(fail_action="prepare")
    app = build_control_app(
        service=service,
        allowed_origin="https://control.test",
        allowed_host="control.test",
        gateway_client=gateway,
        secret_resolver=GatewaySecretResolver(),
    )
    client = TestClient(app, base_url="https://control.test")
    login = client.post(
        "/admin/v1/auth/login",
        headers={"origin": "https://control.test"},
        json={"username": "admin", "password": sample_password()},
    )
    headers = {
        "origin": "https://control.test",
        "x-csrf-token": login.json()["csrf_token"],
    }
    created = client.post(
        "/admin/v1/connections",
        headers=headers,
        json={
            "name": "primary-gateway",
            "gateway_url": "https://gateway.example.test",
            "credential_secret_ref": {
                "kind": "env",
                "identifier": "MEDIA_BRIDGE_GATEWAY_CREDENTIAL",
            },
        },
    )
    payload = {**_preview_payload(), "connection_id": created.json()["id"]}

    response = client.post("/admin/v1/test-lab/preview", headers=headers, json=payload)
    assert response.status_code == 502
    assert response.json() == {"error": {"code": "gateway_unavailable"}}
    assert gateway.calls == ["upload", "prepare", "delete"]
    assert "raw-marker-never-return" not in response.text
    database.close()
