from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from starlette.testclient import TestClient

from media_bridge_control.api import build_control_app
from media_bridge_control.bootstrap import ControlPlaneService
from media_bridge_control.db import Database
from media_bridge_control.models import Provider, User
from media_bridge_control.security import SecurityContext


def _value() -> str:
    return "correct horse battery staple"


def _reference_name() -> str:
    return "MEDIA_BRIDGE_TEST_API_KEY"


def _setup(database_url: str) -> tuple[ControlPlaneService, Database, object]:
    database = Database(database_url)
    security = SecurityContext(pepper=b"r" * 32)
    service = ControlPlaneService(
        database=database,
        security=security,
        now=lambda: datetime(2026, 8, 24, 2, 0, tzinfo=UTC),
    )
    token = service.issue_bootstrap_token()
    service.complete_bootstrap(token=token, username="admin", password=_value())
    with database.session() as session:
        session.add_all(
            [
                User(
                    username="operator",
                    password_hash=security.passwords.hash(_value()),
                    role="operator",
                    is_active=True,
                ),
                User(
                    username="viewer",
                    password_hash=security.passwords.hash(_value()),
                    role="viewer",
                    is_active=True,
                ),
            ]
        )
    app = build_control_app(
        service=service,
        allowed_origin="https://control.test",
        allowed_host="control.test",
    )
    return service, database, app


def _login(app: object, username: str) -> tuple[TestClient, str]:
    client = TestClient(app, base_url="https://control.test")
    response = client.post(
        "/admin/v1/auth/login",
        headers={"origin": "https://control.test"},
        json={"username": username, "password": _value()},
    )
    assert response.status_code == 200
    return client, response.json()["csrf_token"]


def _provider_payload(name: str) -> dict[str, object]:
    return {
        "name": name,
        "kind": "ocr",
        "endpoint": "https://provider.test/v1/ocr",
        "secret_ref": {"kind": "env", "identifier": _reference_name()},
        "enabled": True,
    }


def test_roles_are_enforced_by_admin_api(migrated_postgres: str) -> None:
    _, database, app = _setup(migrated_postgres)
    admin, admin_csrf = _login(app, "admin")
    operator, operator_csrf = _login(app, "operator")
    viewer, viewer_csrf = _login(app, "viewer")

    assert admin.get("/admin/v1/users").status_code == 200
    assert operator.get("/admin/v1/users").status_code == 403
    assert viewer.get("/admin/v1/users").status_code == 403
    assert admin.get("/admin/v1/providers").status_code == 200
    assert operator.get("/admin/v1/providers").status_code == 200
    assert viewer.get("/admin/v1/providers").status_code == 200

    for client, csrf, name, expected in [
        (admin, admin_csrf, "admin-provider", 201),
        (operator, operator_csrf, "operator-provider", 201),
        (viewer, viewer_csrf, "viewer-provider", 403),
    ]:
        response = client.post(
            "/admin/v1/providers",
            headers={"origin": "https://control.test", "x-csrf-token": csrf},
            json=_provider_payload(name),
        )
        assert response.status_code == expected
    database.close()


def test_provider_api_rejects_raw_secret_and_persists_reference_only(
    migrated_postgres: str,
) -> None:
    _, database, app = _setup(migrated_postgres)
    operator, csrf = _login(app, "operator")

    raw_value = "sk-test-raw-value-never-store"
    rejected = operator.post(
        "/admin/v1/providers",
        headers={"origin": "https://control.test", "x-csrf-token": csrf},
        json={**_provider_payload("bad"), "api_key": raw_value},
    )
    assert rejected.status_code == 400
    created = operator.post(
        "/admin/v1/providers",
        headers={"origin": "https://control.test", "x-csrf-token": csrf},
        json=_provider_payload("good"),
    )
    assert created.status_code == 201
    assert raw_value not in created.text

    with database.session() as session:
        provider = session.scalar(select(Provider).where(Provider.name == "good"))
        assert provider is not None
        persisted = " ".join(
            [
                provider.name,
                provider.endpoint,
                provider.secret_ref_kind,
                provider.secret_ref_identifier,
            ]
        )
        assert raw_value not in persisted
        assert provider.secret_ref_identifier == _reference_name()
    database.close()
