from __future__ import annotations

import base64
from datetime import UTC, datetime

from starlette.testclient import TestClient

from media_bridge_control.api import build_control_app
from media_bridge_control.bootstrap import ControlPlaneService
from media_bridge_control.db import Database
from media_bridge_control.security import SecurityContext
from media_bridge_control.totp import _hotp


def _client(database_url: str) -> tuple[TestClient, ControlPlaneService, Database]:
    database = Database(database_url)
    service = ControlPlaneService(
        database=database,
        security=SecurityContext(pepper=b"s" * 32),
        now=lambda: datetime(2026, 8, 24, 1, 0, tzinfo=UTC),
    )
    service.ensure_default_admin()
    return (
        TestClient(
            build_control_app(
                service=service, allowed_origin="https://control.test", allowed_host="control.test"
            ),
            base_url="https://control.test",
        ),
        service,
        database,
    )


def test_login_requires_totp_then_session_cookie_csrf_and_logout(migrated_postgres: str) -> None:
    client, _, database = _client(migrated_postgres)
    origin = {"origin": "https://control.test"}
    pending = client.post(
        "/admin/v1/auth/login", headers=origin, json={"username": "admin", "password": "admin"}
    )
    assert pending.status_code == 401
    assert pending.json() == {"error": {"code": "totp_required"}}
    enrollment = client.post(
        "/admin/v1/auth/totp/enroll",
        headers=origin,
        json={"username": "admin", "password": "admin"},
    )
    assert enrollment.status_code == 200
    secret = enrollment.json()["secret"]
    counter = int(datetime(2026, 8, 24, 1, 0, tzinfo=UTC).timestamp()) // 30
    code = _hotp(base64.b32decode(secret + "=" * (-len(secret) % 8)), counter)
    assert (
        client.post(
            "/admin/v1/auth/totp/confirm",
            headers=origin,
            json={"user_id": enrollment.json()["user_id"], "code": code},
        ).status_code
        == 204
    )
    response = client.post(
        "/admin/v1/auth/totp/login",
        headers=origin,
        json={"username": "admin", "password": "admin", "code": code},
    )
    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    csrf_token = response.json()["csrf_token"]
    assert "mb_admin_session=" in response.headers["set-cookie"]
    me = client.get("/admin/v1/me").json()
    assert me["username"] == "admin"
    assert me["role"] == "admin"
    refreshed_csrf_token = me["csrf_token"]
    assert refreshed_csrf_token != csrf_token
    assert client.post("/admin/v1/auth/logout", headers=origin).status_code == 403
    assert (
        client.post(
            "/admin/v1/auth/logout", headers={**origin, "x-csrf-token": refreshed_csrf_token}
        ).status_code
        == 204
    )
    assert client.get("/admin/v1/me").status_code == 401
    database.close()


def test_http_control_endpoint_can_login_when_explicitly_enabled(
    migrated_postgres: str,
) -> None:
    database = Database(migrated_postgres)
    service = ControlPlaneService(
        database=database,
        security=SecurityContext(pepper=b"s" * 32),
        now=lambda: datetime(2026, 8, 24, 1, 0, tzinfo=UTC),
    )
    service.ensure_default_admin()
    client = TestClient(
        build_control_app(
            service=service,
            allowed_origin="http://control.test",
            allowed_host="control.test",
            allow_insecure_http=True,
        ),
        base_url="http://control.test",
    )

    response = client.post(
        "/admin/v1/auth/login",
        headers={"origin": "http://control.test"},
        json={"username": "admin", "password": "admin"},
    )

    assert response.status_code == 401
    assert response.json() == {"error": {"code": "totp_required"}}
    database.close()


def test_http_totp_login_sets_cookie_usable_without_tls(migrated_postgres: str) -> None:
    database = Database(migrated_postgres)
    now = datetime(2026, 8, 24, 1, 0, tzinfo=UTC)
    service = ControlPlaneService(
        database=database,
        security=SecurityContext(pepper=b"s" * 32),
        now=lambda: now,
    )
    service.ensure_default_admin()
    enrollment = service.begin_totp_enrollment_with_password(
        username="admin",
        password="admin",
    )
    counter = int(now.timestamp()) // 30
    code = _hotp(base64.b32decode(enrollment.secret + "=" * (-len(enrollment.secret) % 8)), counter)
    service.confirm_totp_enrollment(user_id=enrollment.user_id, code=code)
    client = TestClient(
        build_control_app(
            service=service,
            allowed_origin="http://control.test",
            allowed_host="control.test",
            allow_insecure_http=True,
        ),
        base_url="http://control.test",
    )

    response = client.post(
        "/admin/v1/auth/totp/login",
        headers={"origin": "http://control.test"},
        json={"username": "admin", "password": "admin", "code": code},
    )

    assert response.status_code == 200
    assert "Secure" not in response.headers["set-cookie"]
    database.close()


def test_password_recovery_endpoint_is_disabled(migrated_postgres: str) -> None:
    client, _, database = _client(migrated_postgres)
    response = client.post(
        "/admin/v1/auth/recover",
        headers={"origin": "https://control.test"},
        json={
            "username": "admin",
            "recovery_code": "unused-recovery-code",
            "new_password": "unused-password-value",
        },
    )
    assert response.status_code == 405
    assert response.json() == {"error": {"code": "password_change_disabled"}}
    database.close()
