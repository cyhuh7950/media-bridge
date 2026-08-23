from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from media_bridge_control.db import Database
from media_bridge_control.models import SigningKey, Snapshot
from media_bridge_control.snapshots import SnapshotPublisher, SnapshotSigner
from tests.control.snapshot_helpers import private_key_pem, snapshot_body


def test_publish_persists_public_metadata_and_rollback_creates_new_version(
    migrated_postgres: str,
    tmp_path: object,
) -> None:
    from pathlib import Path

    output_path = Path(str(tmp_path)) / "active-snapshot.json"
    database = Database(migrated_postgres)
    private_pem = private_key_pem()
    signer = SnapshotSigner(key_id="test-key", private_key_pem=private_pem)
    publisher = SnapshotPublisher(
        database=database,
        signer=signer,
        output_path=output_path,
        now=lambda: datetime(2026, 8, 24, 4, 0, tzinfo=UTC),
    )

    first = publisher.publish(snapshot_body(model_id="vendor/first"))
    second = publisher.publish(snapshot_body(model_id="vendor/second"))
    rolled_back = publisher.rollback(first.version)

    assert (first.version, second.version, rolled_back.version) == (1, 2, 3)
    assert rolled_back.body == first.body
    assert output_path.read_text(encoding="utf-8") == rolled_back.model_dump_json()
    with database.session() as session:
        keys = list(session.scalars(select(SigningKey)))
        snapshots = list(session.scalars(select(Snapshot).order_by(Snapshot.version)))
        persisted = " ".join(
            [
                *(key.public_key for key in keys),
                *(item.signature for item in snapshots),
                *(item.digest for item in snapshots),
            ]
        )
        assert len(keys) == 1
        assert keys[0].algorithm == "ed25519"
        assert private_pem.decode() not in persisted
        assert [item.version for item in snapshots] == [1, 2, 3]
    database.close()
