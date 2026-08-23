from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from media_bridge_control.audit import AuditEventWriter, OperationalEventWriter
from media_bridge_control.db import Database
from media_bridge_control.redaction import RedactionError


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

    table_names = [
        "audit_events",
        "operational_events",
        "providers",
        "users",
        "client_credentials",
        "snapshots",
    ]
    with database.session() as session:
        dump = " ".join(
            str(value)
            for table_name in table_names
            for value in session.scalars(
                text(f"SELECT row_to_json(entry)::text FROM {table_name} AS entry")
            )
        )
    assert raw_marker not in dump
    assert raw_marker not in caplog.text
    database.close()
