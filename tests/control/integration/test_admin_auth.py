from __future__ import annotations

from datetime import UTC, datetime

from starlette.testclient import TestClient

from media_bridge_control.api import build_control_app
from media_bridge_control.bootstrap import ControlPlaneService
from media_bridge_control.db import Database
from media_bridge_control.security import SecurityContext


def _long_test_value() -> str:
    return "correct horse battery staple"


def _client(database_url: str) -> tuple[TestClient, ControlPlaneService, Database]:
    database = Database(database_url)
    service = ControlPlaneService(
        database=database,
        security=SecurityContext(pepper=b"s" * 32),
        now=lambda: datetime(2026, 8, 24, 1, 0, tzinfo=UTC),
    )
    token = service.issue_bootstrap_token()
    service.complete_bootstrap(
        token=token,
        username="admin",
        password=_long_test_value(),
    )
    app = build_control_app(
        service=service,
        allowed_origin="https://control.test",
        allowed_host="control.test",
    )
    return TestClient(app, base_url="https://control.test"), service, database


def test_login_session_cookie_csrf_and_logout(migrated_postgres: str) -> None:
    client, _, database = _client(migrated_postgres)
    origin = {"origin": "https://control.test"}
    response = client.post(
        "/admin/v1/auth/login",
        headers=origin,
        json={"username": "admin", "password": "correct horse battery staple"},
    )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    csrf_token = response.json()["csrf_token"]
    cookie = response.headers["set-cookie"]
    assert "mb_admin_session=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=strict" in cookie
    assert response.json().get("session_token") is None

    me = client.get("/admin/v1/me")
    assert me.status_code == 200
    assert me.json() == {"username": "admin", "role": "admin"}

    missing_csrf = client.post("/admin/v1/auth/logout", headers=origin)
    assert missing_csrf.status_code == 403
    logged_out = client.post(
        "/admin/v1/auth/logout",
        headers={**origin, "x-csrf-token": csrf_token},
    )
    assert logged_out.status_code == 204
    assert client.get("/admin/v1/me").status_code == 401
    database.close()


def test_login_rejects_bad_origin_http_and_rate_limits(migrated_postgres: str) -> None:
    client, _, database = _client(migrated_postgres)
    payload = {"username": "admin", "password": "wrong password"}

    assert client.post("/admin/v1/auth/login", json=payload).status_code == 403
    http_client = TestClient(client.app, base_url="http://control.test")
    assert (
        http_client.post(
            "/admin/v1/auth/login",
            headers={"origin": "https://control.test"},
            json=payload,
        ).status_code
        == 400
    )
    for _ in range(5):
        assert (
            client.post(
                "/admin/v1/auth/login",
                headers={"origin": "https://control.test"},
                json=payload,
            ).status_code
            == 401
        )
    blocked = client.post(
        "/admin/v1/auth/login",
        headers={"origin": "https://control.test"},
        json={"username": "admin", "password": "correct horse battery staple"},
    )
    assert blocked.status_code == 429
    assert blocked.json() == {"error": {"code": "login_rate_limited"}}
    database.close()
