from __future__ import annotations

from datetime import UTC, datetime

from media_bridge.capabilities import CapabilityState
from media_bridge.config_snapshot import LastKnownGoodSnapshot, SnapshotVerifier
from media_bridge.runtime_snapshot import SnapshotRuntimeSource
from media_bridge_control.db import Database
from media_bridge_control.snapshots import SnapshotPublisher, SnapshotSigner
from tests.control.snapshot_helpers import private_key_pem, snapshot_body


def test_data_plane_uses_last_snapshot_without_control_plane_database(
    migrated_postgres: str,
    tmp_path: object,
) -> None:
    from pathlib import Path

    path = Path(str(tmp_path)) / "active.json"
    database = Database(migrated_postgres)
    signer = SnapshotSigner(key_id="test-key", private_key_pem=private_key_pem())
    publisher = SnapshotPublisher(
        database=database,
        signer=signer,
        output_path=path,
        now=lambda: datetime(2026, 8, 24, 4, 0, tzinfo=UTC),
    )
    publisher.publish(snapshot_body())

    store = LastKnownGoodSnapshot(SnapshotVerifier({"test-key": signer.public_key_bytes}))
    store.load(path)
    source = SnapshotRuntimeSource(store)
    database.close()

    resolution = source.capability_registry().resolve(
        "vendor/text-model",
        now=datetime(2026, 8, 24, 4, 1, tzinfo=UTC),
    )
    assert resolution.state is CapabilityState.NON_VISION
    assert source.snapshot_version == 1
