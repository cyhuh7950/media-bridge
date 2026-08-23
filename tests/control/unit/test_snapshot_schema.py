from __future__ import annotations

import copy
from datetime import UTC, datetime
from uuid import UUID

import pytest

from media_bridge.config_snapshot import SnapshotVerificationError, SnapshotVerifier
from media_bridge_control.snapshots import SnapshotSigner
from tests.control.snapshot_helpers import private_key_pem, snapshot_body


def test_signed_snapshot_verifies_without_private_key_material() -> None:
    private_pem = private_key_pem()
    signer = SnapshotSigner(key_id="test-key", private_key_pem=private_pem)
    snapshot = signer.sign(
        snapshot_id=UUID("00000000-0000-0000-0000-000000000001"),
        version=1,
        issued_at=datetime(2026, 8, 24, 4, 0, tzinfo=UTC),
        body=snapshot_body(),
    )
    serialized = snapshot.model_dump_json()

    assert private_pem.decode() not in serialized
    verifier = SnapshotVerifier({"test-key": signer.public_key_bytes})
    assert verifier.verify_json(serialized).version == 1


@pytest.mark.parametrize("field", ["body", "digest", "signature", "key_id"])
def test_snapshot_tampering_is_rejected(field: str) -> None:
    signer = SnapshotSigner(key_id="test-key", private_key_pem=private_key_pem())
    snapshot = signer.sign(
        snapshot_id=UUID("00000000-0000-0000-0000-000000000001"),
        version=1,
        issued_at=datetime(2026, 8, 24, 4, 0, tzinfo=UTC),
        body=snapshot_body(),
    )
    payload = copy.deepcopy(snapshot.model_dump(mode="json"))
    if field == "body":
        payload["body"]["policy"]["max_files"] = 99
    else:
        payload[field] = f"tampered-{payload[field]}"

    verifier = SnapshotVerifier({"test-key": signer.public_key_bytes})
    with pytest.raises(SnapshotVerificationError):
        verifier.verify_object(payload)


def test_snapshot_rejects_sensitive_body_fields() -> None:
    signer = SnapshotSigner(key_id="test-key", private_key_pem=private_key_pem())
    body = snapshot_body()
    body["provider_secret"] = "must-never-be-signed"
    with pytest.raises(ValueError):
        signer.sign(
            snapshot_id=UUID("00000000-0000-0000-0000-000000000001"),
            version=1,
            issued_at=datetime(2026, 8, 24, 4, 0, tzinfo=UTC),
            body=body,
        )
