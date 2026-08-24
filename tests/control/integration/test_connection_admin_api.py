from __future__ import annotations

from starlette.testclient import TestClient

from media_bridge_control.api import build_control_app
from media_bridge_control.secrets import GatewaySecretResolver
from tests.control.p2b_helpers import (
    StubGatewayClient,
    configured_control,
    sample_password,
)


def _login(app: object, username: str) -> tuple[TestClient, str]:
    client = TestClient(app, base_url="https://control.test")
    response = client.post(
        "/admin/v1/auth/login",
        headers={"origin": "https://control.test"},
        json={"username": username, "password": sample_password()},
    )
    assert response.status_code == 200
    return client, response.json()["csrf_token"]


def _payload() -> dict[str, object]:
    return {
        "name": "primary-gateway",
        "gateway_url": "https://gateway.example.test",
        "credential_secret_ref": {
            "kind": "env",
            "identifier": "MEDIA_BRIDGE_GATEWAY_CREDENTIAL",
        },
        "enabled": True,
    }


def test_connection_admin_api_enforces_rbac_csrf_masking_and_lifecycle(
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
    admin, admin_csrf = _login(app, "admin")
    operator, operator_csrf = _login(app, "operator")
    viewer, viewer_csrf = _login(app, "viewer")
    write_headers = {
        "origin": "https://control.test",
        "x-csrf-token": admin_csrf,
    }

    assert admin.post("/admin/v1/connections", json=_payload()).status_code == 403
    assert (
        operator.post(
            "/admin/v1/connections",
            headers={
                "origin": "https://control.test",
                "x-csrf-token": operator_csrf,
            },
            json=_payload(),
        ).status_code
        == 403
    )
    created = admin.post("/admin/v1/connections", headers=write_headers, json=_payload())
    assert created.status_code == 201
    connection_id = created.json()["id"]
    assert "MEDIA_BRIDGE_GATEWAY_CREDENTIAL" not in created.text
    assert created.json()["credential_secret_ref"]["identifier"] == "MED***IAL"

    assert viewer.get("/admin/v1/connections").status_code == 200
    assert (
        viewer.post(
            f"/admin/v1/connections/{connection_id}/test",
            headers={
                "origin": "https://control.test",
                "x-csrf-token": viewer_csrf,
            },
        ).status_code
        == 403
    )
    tested = operator.post(
        f"/admin/v1/connections/{connection_id}/test",
        headers={
            "origin": "https://control.test",
            "x-csrf-token": operator_csrf,
        },
    )
    assert tested.status_code == 200
    assert tested.json()["status"] == "ready"
    assert tested.json()["last_success_at"] == "2026-08-25T04:00:00+00:00"
    assert gateway.calls == ["status"]

    patched = admin.patch(
        f"/admin/v1/connections/{connection_id}",
        headers=write_headers,
        json={"name": "renamed-gateway"},
    )
    assert patched.status_code == 200
    revoked = admin.delete(
        f"/admin/v1/connections/{connection_id}",
        headers=write_headers,
    )
    assert revoked.status_code == 204
    assert admin.get("/admin/v1/connections").json()[0]["status"] == "revoked"
    database.close()
