"""Verify a bounded Media Bridge backup without extracting it."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path

MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_DATABASE_BYTES = 500 * 1024 * 1024
EXPECTED_MEMBERS = frozenset({"manifest.json", "database.sql"})


class BackupVerificationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class VerifiedBackup:
    product_version: str
    migration_revision: str
    database_sha256: str


def _member_bytes(archive: tarfile.TarFile, member: tarfile.TarInfo, limit: int) -> bytes:
    if not member.isfile() or member.size < 0 or member.size > limit:
        raise BackupVerificationError("archive_member_invalid")
    stream = archive.extractfile(member)
    if stream is None:
        raise BackupVerificationError("archive_member_invalid")
    body = stream.read(limit + 1)
    if len(body) > limit:
        raise BackupVerificationError("archive_member_invalid")
    return body


def verify(path: Path) -> VerifiedBackup:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise BackupVerificationError("backup_file_invalid")
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            if {member.name for member in members} != EXPECTED_MEMBERS or len(members) != 2:
                raise BackupVerificationError("archive_members_invalid")
            by_name = {member.name: member for member in members}
            manifest_body = _member_bytes(archive, by_name["manifest.json"], 16_384)
            database = _member_bytes(archive, by_name["database.sql"], MAX_DATABASE_BYTES)
    except BackupVerificationError:
        raise
    except (OSError, tarfile.TarError) as error:
        raise BackupVerificationError("backup_file_invalid") from error
    try:
        manifest = json.loads(manifest_body)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BackupVerificationError("manifest_invalid") from error
    expected_keys = {
        "schema",
        "product_version",
        "migration_revision",
        "created_at",
        "database_sha256",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_keys:
        raise BackupVerificationError("manifest_invalid")
    if manifest.get("schema") != "media-bridge-backup/v1":
        raise BackupVerificationError("manifest_invalid")
    digest = hashlib.sha256(database).hexdigest()
    if manifest.get("database_sha256") != digest:
        raise BackupVerificationError("digest_mismatch")
    product_version = manifest.get("product_version")
    migration_revision = manifest.get("migration_revision")
    if not isinstance(product_version, str) or not isinstance(migration_revision, str):
        raise BackupVerificationError("manifest_invalid")
    return VerifiedBackup(
        product_version=product_version,
        migration_revision=migration_revision,
        database_sha256=digest,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a Media Bridge backup archive")
    parser.add_argument("backup", type=Path)
    result = verify(parser.parse_args().backup)
    print(
        json.dumps(
            {
                "status": "verified",
                "product_version": result.product_version,
                "migration_revision": result.migration_revision,
                "database_sha256": result.database_sha256,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
