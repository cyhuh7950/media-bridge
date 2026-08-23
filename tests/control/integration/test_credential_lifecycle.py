from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from media_bridge_control.api import build_control_app
from media_bridge_control.bootstrap import ControlPlaneService
from media_bridge_control.credentials import CredentialError, CredentialService
from media_bridge_control.db import Database
from media_bridge_control.models import ClientCredential
from media_bridge_control.security import SecurityContext


def _setup(database_url: str) -> tuple[TestClient, str, ControlPlaneService, Database]:
    database = Database(database_url)
    service = ControlPlaneService(
        database=database,
        security=SecurityContext(pepper=b"d" * 32),
        now=lambda: datetime(2026, 8, 24, 5, 0, tzinfo=UTC),
    )
    bootstrap = service.issue_bootstrap_token()
    value = "correct horse battery staple"
    service.complete_bootstrap(token=bootstrap, username="admin", password=value)
    client = TestClient(
        build_control_app(
            service=service,
            allowed_origin="https://control.test",
            allowed_host="control.test",
        ),
        base_url="https://control.test",
    )
    login = client.post(
        "/admin/v1/auth/login",
        headers={"origin": "https://control.test"},
        json={"username": "admin", "password": value},
    )
    return client, login.json()["csrf_token"], service, database


def test_client_credential_is_shown_once_stored_as_digest_and_revocable(
    migrated_postgres: str,
) -> None:
    client, csrf, control, database = _setup(migrated_postgres)
    headers = {"origin": "https://control.test", "x-csrf-token": csrf}
    created = client.post(
        "/admin/v1/credentials",
        headers=headers,
        json={
            "name": "desktop-agent",
            "scopes": ["responses:invoke"],
            "expires_at": (datetime(2026, 8, 24, 5, 0, tzinfo=UTC) + timedelta(days=30)).isoformat(),
        },
    )
    assert created.status_code == 201
    raw = created.json()["credential"]
    selector = created.json()["selector"]
    assert raw.startswith("mbc_")

    listed = client.get("/admin/v1/credentials")
    assert listed.status_code == 200
    assert raw not in listed.text
    assert "credential_digest" not in listed.text
    with database.session() as session:
        stored = session.get(ClientCredential, selector)
        assert stored is not None
        assert raw != stored.credential_digest
        assert raw not in stored.credential_digest

    verifier = CredentialService(
        database=database,
        security=control.security,
        now=lambda: datetime(2026, 8, 24, 5, 1, tzinfo=UTC),
    )
    assert verifier.verify(raw, required_scope="responses:invoke").selector == selector
    with pytest.raises(CredentialError):
        verifier.verify(raw, required_scope="mcp:invoke")

    revoked = client.delete(f"/admin/v1/credentials/{selector}", headers=headers)
    assert revoked.status_code == 204
    with pytest.raises(CredentialError):
        verifier.verify(raw, required_scope="responses:invoke")
    database.close()


def test_credential_api_is_admin_only(migrated_postgres: str) -> None:
    client, _, _, database = _setup(migrated_postgres)
    with database.session() as session:
        admin = session.scalar(select(ClientCredential))
        assert admin is None
    assert client.get("/admin/v1/credentials").status_code == 200
    database.close()
