from __future__ import annotations

from datetime import UTC, datetime, timedelta

from media_bridge_control.bootstrap import ControlPlaneService
from media_bridge_control.connections import ConnectionService
from media_bridge_control.db import Database
from media_bridge_control.schemas import ConnectionCreate, ConnectionUpdate
from media_bridge_control.security import SecurityContext


def _test_password() -> str:
    return "correct horse battery staple"


def _admin(database: Database) -> str:
    control = ControlPlaneService(
        database=database,
        security=SecurityContext(pepper=b"p" * 32),
        now=lambda: datetime(2026, 8, 25, tzinfo=UTC),
    )
    token = control.issue_bootstrap_token()
    result = control.complete_bootstrap(
        token=token,
        username="admin",
        password=_test_password(),
    )
    return result.user_id


def test_connection_lifecycle_masks_secret_reference_and_records_success(
    migrated_postgres: str,
) -> None:
    database = Database(migrated_postgres)
    admin_id = _admin(database)
    service = ConnectionService(database)
    created = service.create(
        ConnectionCreate(
            name="primary-gateway",
            gateway_url="https://gateway.example.test",
            credential_secret_ref={
                "kind": "env",
                "identifier": "MEDIA_BRIDGE_GATEWAY_CREDENTIAL",
            },
            enabled=True,
        ),
        created_by=admin_id,
    )

    assert created["status"] == "untested"
    assert created["last_success_at"] is None
    assert created["credential_secret_ref"] == {
        "kind": "env",
        "identifier": "MED***IAL",
    }
    assert "MEDIA_BRIDGE_GATEWAY_CREDENTIAL" not in repr(created)

    updated = service.update(
        created["id"],
        ConnectionUpdate(name="renamed-gateway", enabled=False),
    )
    assert updated["name"] == "renamed-gateway"
    assert updated["enabled"] is False

    tested_at = datetime(2026, 8, 25, 1, 0, tzinfo=UTC)
    failed = service.record_test_result(
        created["id"],
        succeeded=False,
        error_code="gateway_unavailable",
        tested_at=tested_at,
    )
    assert failed["status"] == "failed"
    assert failed["last_success_at"] is None
    assert failed["last_error_code"] == "gateway_unavailable"

    succeeded = service.record_test_result(
        created["id"],
        succeeded=True,
        error_code=None,
        tested_at=tested_at + timedelta(minutes=1),
    )
    assert succeeded["status"] == "ready"
    assert succeeded["last_success_at"] == "2026-08-25T01:01:00+00:00"
    assert succeeded["last_error_code"] is None

    revoked = service.revoke(created["id"], revoked_at=tested_at + timedelta(minutes=2))
    assert revoked["status"] == "revoked"
    assert revoked["revoked_at"] == "2026-08-25T01:02:00+00:00"
    assert service.list()[0]["status"] == "revoked"
    database.close()


def test_connection_url_rejects_credential_query_fragment_and_plain_http() -> None:
    invalid_urls = [
        "http://gateway.example.test",
        "https://user:password@gateway.example.test",
        "https://gateway.example.test?token=value",
        "https://gateway.example.test/#secret",
    ]

    for gateway_url in invalid_urls:
        try:
            ConnectionCreate(
                name="gateway",
                gateway_url=gateway_url,
                credential_secret_ref={"kind": "env", "identifier": "GATEWAY_KEY"},
            )
        except ValueError:
            continue
        raise AssertionError(f"unsafe Gateway URL was accepted: {gateway_url}")
