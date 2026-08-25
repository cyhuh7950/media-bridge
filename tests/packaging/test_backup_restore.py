import io
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from deploy.scripts import backup, restore, verify_backup


SAFE_SQL = b"CREATE TABLE policies (id uuid);\nINSERT INTO policies VALUES ('safe');\n"


def test_backup_contains_only_manifest_and_database_dump(tmp_path: Path) -> None:
    output = tmp_path / "backup.tar.gz"
    backup.create_archive(
        output=output,
        sql_dump=SAFE_SQL,
        product_version="0.1.0",
        migration_revision="0002_connections",
        created_at=datetime(2026, 8, 25, tzinfo=UTC),
    )

    result = verify_backup.verify(output)
    assert result.product_version == "0.1.0"
    assert result.migration_revision == "0002_connections"
    with tarfile.open(output, "r:gz") as archive:
        assert set(archive.getnames()) == {"manifest.json", "database.sql"}
        assert all("secret" not in name and "media" not in name for name in archive.getnames())


@pytest.mark.parametrize(
    "marker",
    [
        b"sk-private-provider-value-1234567890",
        b"mbc_private-client-value-1234567890",
        b"-----BEGIN PRIVATE KEY-----",
        b"data:image/png;base64,private-body",
    ],
)
def test_backup_rejects_raw_secret_or_media_markers(tmp_path: Path, marker: bytes) -> None:
    with pytest.raises(backup.BackupError, match="sensitive_content_detected"):
        backup.create_archive(
            output=tmp_path / "unsafe.tar.gz",
            sql_dump=SAFE_SQL + marker,
            product_version="0.1.0",
            migration_revision="0002_connections",
            created_at=datetime(2026, 8, 25, tzinfo=UTC),
        )
    assert not (tmp_path / "unsafe.tar.gz").exists()


def test_verify_rejects_digest_tampering(tmp_path: Path) -> None:
    output = tmp_path / "tampered.tar.gz"
    manifest = {
        "schema": "media-bridge-backup/v1",
        "product_version": "0.1.0",
        "migration_revision": "0002_connections",
        "created_at": "2026-08-25T00:00:00+00:00",
        "database_sha256": "0" * 64,
    }
    with tarfile.open(output, "w:gz") as archive:
        for name, body in (
            ("manifest.json", json.dumps(manifest).encode()),
            ("database.sql", SAFE_SQL),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
    with pytest.raises(verify_backup.BackupVerificationError, match="digest_mismatch"):
        verify_backup.verify(output)


def test_restore_requires_empty_database_and_explicit_confirmation(tmp_path: Path) -> None:
    output = tmp_path / "backup.tar.gz"
    backup.create_archive(
        output=output,
        sql_dump=SAFE_SQL,
        product_version="0.1.0",
        migration_revision="0002_connections",
        created_at=datetime(2026, 8, 25, tzinfo=UTC),
    )
    calls: list[bytes] = []

    with pytest.raises(restore.RestoreError, match="confirmation_required"):
        restore.restore_archive(output, database_is_empty=True, confirmed=False, apply_sql=calls.append)
    with pytest.raises(restore.RestoreError, match="target_database_not_empty"):
        restore.restore_archive(output, database_is_empty=False, confirmed=True, apply_sql=calls.append)
    assert calls == []

    restore.restore_archive(output, database_is_empty=True, confirmed=True, apply_sql=calls.append)
    assert calls == [SAFE_SQL]


def test_restore_readiness_requires_external_secret_reconnection() -> None:
    assert restore.readiness_after_restore(secret_refs_connected=False) == "limited"
    assert restore.readiness_after_restore(secret_refs_connected=True) == "ready"

