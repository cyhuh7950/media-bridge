"""Create a deterministic, Secret-screened database backup archive."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

MAX_DATABASE_BYTES = 500 * 1024 * 1024
SENSITIVE_PATTERNS = (
    re.compile(b"-----begin " + b"private key-----", re.I),
    re.compile(rb"data:image/", re.I),
    re.compile(rb"data:application/pdf;base64,", re.I),
    re.compile(rb"sk-[a-z0-9_-]{16,}", re.I),
    re.compile(rb"mbc_[a-z0-9_-]{16,}", re.I),
)


class BackupError(RuntimeError):
    pass


def _docker() -> str:
    executable = shutil.which("docker")
    if executable is None or not Path(executable).is_absolute():
        raise BackupError("docker_unavailable")
    return executable


def dump_from_compose(*, compose_files: tuple[Path, ...]) -> bytes:
    command = [_docker(), "compose"]
    for compose_file in compose_files:
        command.extend(("-f", str(compose_file.resolve(strict=True))))
    command.extend(
        (
            "exec",
            "-T",
            "media-bridge-db",
            "pg_dump",
            "-U",
            "media_bridge",
            "-d",
            "media_bridge",
            "--format=plain",
            "--no-owner",
            "--no-privileges",
        )
    )
    try:
        result = subprocess.run(command, check=True, capture_output=True)  # noqa: S603
    except (OSError, subprocess.CalledProcessError) as error:
        raise BackupError("database_dump_failed") from error
    return result.stdout


def _safe_database_dump(sql_dump: bytes) -> None:
    if not sql_dump or len(sql_dump) > MAX_DATABASE_BYTES:
        raise BackupError("database_dump_invalid")
    if any(pattern.search(sql_dump) for pattern in SENSITIVE_PATTERNS):
        raise BackupError("sensitive_content_detected")


def _tar_info(name: str, size: int, *, mtime: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = 0o600
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = mtime
    return info


def create_archive(
    *,
    output: Path,
    sql_dump: bytes,
    product_version: str,
    migration_revision: str,
    created_at: datetime,
) -> None:
    _safe_database_dump(sql_dump)
    if output.is_symlink() or not output.parent.is_dir():
        raise BackupError("backup_output_invalid")
    timestamp = int(created_at.timestamp())
    manifest = json.dumps(
        {
            "schema": "media-bridge-backup/v1",
            "product_version": product_version,
            "migration_revision": migration_revision,
            "created_at": created_at.isoformat(),
            "database_sha256": hashlib.sha256(sql_dump).hexdigest(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    descriptor, temporary_name = tempfile.mkstemp(prefix=".media-bridge-backup-", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with (
            os.fdopen(descriptor, "wb") as raw,
            gzip.GzipFile(fileobj=raw, mode="wb", mtime=timestamp) as compressed,
            tarfile.open(fileobj=compressed, mode="w") as archive,
        ):
            archive.addfile(
                _tar_info("manifest.json", len(manifest), mtime=timestamp),
                io.BytesIO(manifest),
            )
            archive.addfile(
                _tar_info("database.sql", len(sql_dump), mtime=timestamp),
                io.BytesIO(sql_dump),
            )
        temporary.replace(output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a Secret-screened Media Bridge backup")
    parser.add_argument("--compose-file", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--product-version", required=True)
    parser.add_argument("--migration-revision", required=True)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    create_archive(
        output=arguments.output,
        sql_dump=dump_from_compose(compose_files=tuple(arguments.compose_file)),
        product_version=arguments.product_version,
        migration_revision=arguments.migration_revision,
        created_at=datetime.now().astimezone(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
