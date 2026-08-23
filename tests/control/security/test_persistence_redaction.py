from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from starlette.testclient import TestClient

from media_bridge_control.api import build_control_app
from media_bridge_control.audit import AuditEventWriter, OperationalEventWriter
from media_bridge_control.bootstrap import ControlPlaneService
from media_bridge_control.db import Database
from media_bridge_control.redaction import RedactionError
from media_bridge_control.security import SecurityContext


def test_audit_event_and_database_reject_sensitive_bodies(
    migrated_postgres: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    database = Database(migrated_postgres)
    audit = AuditEventWriter(database)
    events = OperationalEventWriter(database)
    caplog.set_level(logging.DEBUG)

    raw_marker = "raw-sensitive-marker-never-persist"
    with pytest.raises(RedactionError):
        audit.write(
            actor_id=None,
            action="provider.created",
            target_type="provider",
            target_id="provider-1",
            details={"secret": raw_marker},
        )
    audit.write(
        actor_id=None,
        action="provider.created",
        target_type="provider",
        target_id="provider-1",
        details={"status": "created", "name": "provider-1"},
    )
    events.write(
        request_id="anonymous-request-1",
        event_type="blocked",
        model_id="vendor/text-model",
        policy_version=1,
        status_code="capability_unknown",
        latency_bucket="lt_100ms",
        size_bucket="lt_2mb",
        created_at=datetime(2026, 8, 24, 5, 0, tzinfo=UTC),
    )

    safe_queries = [
        text("SELECT row_to_json(entry)::text FROM audit_events AS entry"),
        text("SELECT row_to_json(entry)::text FROM operational_events AS entry"),
        text("SELECT row_to_json(entry)::text FROM providers AS entry"),
        text("SELECT row_to_json(entry)::text FROM users AS entry"),
        text("SELECT row_to_json(entry)::text FROM client_credentials AS entry"),
        text("SELECT row_to_json(entry)::text FROM snapshots AS entry"),
    ]
    with database.session() as session:
        dump = " ".join(
            str(value)
            for query in safe_queries
            for value in session.scalars(query)
        )
    assert raw_marker not in dump
    assert raw_marker not in caplog.text
    database.close()


def test_raw_auth_provider_and_credential_values_never_persist_or_log(
    migrated_postgres: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    database = Database(migrated_postgres)
    service = ControlPlaneService(
        database=database,
        security=SecurityContext(pepper=b"x" * 32),
        now=lambda: datetime(2026, 8, 24, 5, 30, tzinfo=UTC),
    )
    bootstrap_token = service.issue_bootstrap_token()
    admin_marker = "correct horse battery staple password-marker"
    bootstrap = service.complete_bootstrap(
        token=bootstrap_token,
        username="admin",
        password=admin_marker,
    )
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
        json={"username": "admin", "password": admin_marker},
    )
    csrf_token = login.json()["csrf_token"]
    session_token = client.cookies.get("mb_admin_session")
    assert session_token is not None
    headers = {
        "origin": "https://control.test",
        "x-csrf-token": csrf_token,
    }

    provider_marker = "provider-raw-secret-marker"
    rejected = client.post(
        "/admin/v1/providers",
        headers=headers,
        json={
            "name": "bad-provider",
            "kind": "ocr",
            "endpoint": "https://provider.test/v1/ocr",
            "secret_ref": {
                "kind": "env",
                "identifier": "MEDIA_BRIDGE_PROVIDER_API_KEY",
            },
            "enabled": True,
            "api_key": provider_marker,
        },
    )
    assert rejected.status_code == 400
    assert provider_marker not in rejected.text

    issued = client.post(
        "/admin/v1/credentials",
        headers=headers,
        json={"name": "reference-client", "scopes": ["mcp:invoke"]},
    )
    assert issued.status_code == 201
    raw_credential = issued.json()["credential"]
    assert raw_credential.startswith("mbc_")
    listed = client.get("/admin/v1/credentials")
    assert listed.status_code == 200
    assert raw_credential not in listed.text

    sensitive_queries = [
        text("SELECT row_to_json(entry)::text FROM bootstrap_tokens AS entry"),
        text("SELECT row_to_json(entry)::text FROM recovery_codes AS entry"),
        text("SELECT row_to_json(entry)::text FROM admin_sessions AS entry"),
        text("SELECT row_to_json(entry)::text FROM users AS entry"),
        text("SELECT row_to_json(entry)::text FROM providers AS entry"),
        text("SELECT row_to_json(entry)::text FROM client_credentials AS entry"),
        text("SELECT row_to_json(entry)::text FROM audit_events AS entry"),
    ]
    with database.session() as session:
        database_dump = " ".join(
            str(value)
            for query in sensitive_queries
            for value in session.scalars(query)
        )
    raw_values = [
        bootstrap_token,
        admin_marker,
        *bootstrap.recovery_codes,
        session_token,
        csrf_token,
        provider_marker,
        raw_credential,
    ]
    for raw_value in raw_values:
        assert raw_value not in database_dump
        assert raw_value not in caplog.text
    database.close()
