from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from media_bridge_control.configuration import ConfigurationService
from media_bridge_control.db import Database
from media_bridge_control.models import (
    ClientCredential,
    ModelCapability,
    Policy,
    Provider,
    User,
)
from media_bridge_control.security import SecurityContext


def _test_password_hash() -> str:
    return "argon2id-placeholder"


def _test_secret_ref() -> tuple[str, str]:
    return "env", "MEDIA_BRIDGE_OCR_KEY"


def test_control_snapshot_publishes_only_data_plane_credential_digest(
    migrated_postgres: str,
) -> None:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    database = Database(migrated_postgres)
    security = SecurityContext(pepper=b"p" * 32)
    raw = "mbc_selector-a.super-secret-value"
    secret_ref_kind, secret_ref_identifier = _test_secret_ref()
    with database.session() as session:
        user = User(username="admin", password_hash=_test_password_hash(), role="admin")
        session.add(user)
        session.flush()
        session.add_all(
            [
                ClientCredential(
                    selector="selector-a",
                    name="gateway-client",
                    credential_digest=security.digest(raw, purpose="client_credential"),
                    scopes=["responses:invoke"],
                    expires_at=now + timedelta(days=1),
                    created_by=user.id,
                ),
                Provider(
                    name="ocr",
                    kind="ocr",
                    endpoint="https://provider.test/v1/ocr",
                    secret_ref_kind=secret_ref_kind,
                    secret_ref_identifier=secret_ref_identifier,
                ),
                ModelCapability(
                    model_id="vendor/text-model",
                    aliases=[],
                    input_modalities=["text"],
                    evidence="provider documentation",
                    reviewed_at=now,
                    expires_at=now + timedelta(days=30),
                ),
                Policy(
                    name="default",
                    body={
                        "fail_closed": True,
                        "max_files": 4,
                        "max_media_bytes": 2_097_152,
                        "max_pdf_pages": 20,
                    },
                ),
            ]
        )

    body = ConfigurationService(database).snapshot_body()
    serialized = json.dumps(body)
    entry = body["data_plane_auth"]["entries"][0]

    assert entry["selector"] == "selector-a"
    assert entry["digest"] == security.digest(raw, purpose="client_credential")
    assert entry["scopes"] == ["responses:invoke"]
    assert raw not in serialized
    assert "super-secret-value" not in serialized
    database.close()
