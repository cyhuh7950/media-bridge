from __future__ import annotations

import base64

from starlette.testclient import TestClient

from media_bridge_control.api import build_control_app
from media_bridge_control.secrets import GatewaySecretResolver
from tests.control.p2b_helpers import StubGatewayClient, configured_control, sample_password
from tests.gateway.helpers import png_bytes


def _preview_payload() -> dict[str, object]:
    return {
        "target_model": "text-model",
        "conversion_profile": "error_screenshot",
        "user_request": "이 오류를 설명해줘",
        "media_type": "image",
        "filename": "error.png",
        "declared_mime": "image/png",
        "media_base64": base64.b64encode(png_bytes()).decode(),
    }


def test_preview_fails_closed_without_a_routing_profile(
    migrated_postgres: str,
    monkeypatch: object,
) -> None:
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
    payload = _preview_payload()

    preview = client.post("/admin/v1/test-lab/preview", headers=headers, json=payload)
    assert preview.status_code == 404
    assert preview.json() == {"error": {"code": "routing_profile_unavailable"}}
    assert gateway.calls == []

    missing_opt_in = client.post(
        "/admin/v1/test-lab/run",
        headers=headers,
        json={
            **payload,
            "gateway_url": "https://gateway.example.test",
            "api_key": "mbc_gateway.external-value",
        },
    )
    false_opt_in = client.post(
        "/admin/v1/test-lab/run",
        headers=headers,
        json={
            **payload,
            "gateway_url": "https://gateway.example.test",
            "api_key": "mbc_gateway.external-value",
            "execute_downstream": False,
        },
    )
    assert missing_opt_in.status_code == 400
    assert false_opt_in.status_code == 400
    assert gateway.calls == []
    run = client.post(
        "/admin/v1/test-lab/run",
        headers=headers,
        json={
            **payload,
            "gateway_url": "https://gateway.example.test",
            "api_key": "mbc_gateway.external-value",
            "execute_downstream": True,
        },
    )
    assert run.status_code == 200
    assert run.json()["id"] == "resp_test"
    assert gateway.calls[-3:] == ["upload", "responses", "delete"]
    database.close()


def test_preview_does_not_call_downstream_or_expose_credentials(
    migrated_postgres: str,
    monkeypatch: object,
) -> None:
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
    payload = _preview_payload()

    response = client.post("/admin/v1/test-lab/preview", headers=headers, json=payload)
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "routing_profile_unavailable"}}
    assert gateway.calls == []
    database.close()
