from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from media_bridge.config_snapshot import (
    LastKnownGoodSnapshot,
    SnapshotVerificationError,
    SnapshotVerifier,
)
from media_bridge_control.snapshots import SnapshotSigner
from tests.control.snapshot_helpers import private_key_pem, snapshot_body


def test_invalid_partial_and_replayed_snapshot_leave_last_known_good_unchanged(
    tmp_path: object,
) -> None:
    from pathlib import Path

    path = Path(str(tmp_path)) / "active.json"
    signer = SnapshotSigner(key_id="test-key", private_key_pem=private_key_pem())
    verifier = SnapshotVerifier({"test-key": signer.public_key_bytes})
    store = LastKnownGoodSnapshot(verifier)
    first = signer.sign(
        snapshot_id=uuid4(),
        version=1,
        issued_at=datetime(2026, 8, 24, 4, 0, tzinfo=UTC),
        body=snapshot_body(model_id="vendor/first"),
    )
    path.write_text(first.model_dump_json(), encoding="utf-8")
    assert store.load(path).version == 1

    path.write_text('{"schema":', encoding="utf-8")
    with pytest.raises(SnapshotVerificationError):
        store.load(path)
    assert store.current().version == 1

    second = signer.sign(
        snapshot_id=uuid4(),
        version=2,
        issued_at=datetime(2026, 8, 24, 4, 1, tzinfo=UTC),
        body=snapshot_body(model_id="vendor/second"),
    )
    tampered = second.model_dump(mode="json")
    tampered["body"]["policy"]["max_files"] = 99
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(SnapshotVerificationError):
        store.load(path)
    assert store.current().version == 1

    path.write_text(second.model_dump_json(), encoding="utf-8")
    assert store.load(path).version == 2
    path.write_text(first.model_dump_json(), encoding="utf-8")
    with pytest.raises(SnapshotVerificationError):
        store.load(path)
    assert store.current().version == 2
