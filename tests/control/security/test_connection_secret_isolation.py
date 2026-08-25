from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from media_bridge_control.bootstrap import ControlPlaneService
from media_bridge_control.connections import ConnectionService
from media_bridge_control.db import Database
from media_bridge_control.schemas import ConnectionCreate, SecretReference
from media_bridge_control.secrets import GatewaySecretResolver
from media_bridge_control.security import SecurityContext


def _test_password() -> str:
    return "correct horse battery staple"


def test_connection_credential_value_never_persists_or_logs(
    migrated_postgres: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_marker = "mbc_gateway.raw-credential-must-never-persist"
    monkeypatch.setenv("MEDIA_BRIDGE_GATEWAY_CREDENTIAL", raw_marker)
    caplog.set_level(logging.DEBUG)
    database = Database(migrated_postgres)
    control = ControlPlaneService(
        database=database,
        security=SecurityContext(pepper=b"x" * 32),
        now=lambda: datetime(2026, 8, 25, tzinfo=UTC),
    )
    token = control.issue_bootstrap_token()
    admin = control.complete_bootstrap(
        token=token,
        username="admin",
        password=_test_password(),
    )
    service = ConnectionService(database)
    created = service.create(
        ConnectionCreate(
            name="gateway",
            gateway_url="https://gateway.example.test",
            credential_secret_ref={
                "kind": "env",
                "identifier": "MEDIA_BRIDGE_GATEWAY_CREDENTIAL",
            },
        ),
        created_by=admin.user_id,
    )

    resolver = GatewaySecretResolver()
    resolved = resolver.resolve(
        SecretReference(kind="env", identifier="MEDIA_BRIDGE_GATEWAY_CREDENTIAL")
    )
    assert resolved == raw_marker
    assert raw_marker not in repr(resolver)
    assert raw_marker not in repr(created)

    with database.session() as session:
        dump = " ".join(
            str(value)
            for value in session.scalars(
                text("SELECT row_to_json(entry)::text FROM connections AS entry")
            )
        )
    assert raw_marker not in dump
    assert raw_marker not in caplog.text
    database.close()
