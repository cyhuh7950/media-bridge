"""Restore only a verified archive into an explicitly empty database."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tarfile
from collections.abc import Callable
from pathlib import Path

from deploy.scripts.verify_backup import BackupVerificationError, verify


class RestoreError(RuntimeError):
    pass


def _docker() -> str:
    executable = shutil.which("docker")
    if executable is None or not Path(executable).is_absolute():
        raise RestoreError("docker_unavailable")
    return executable


def _compose_command(
    compose_files: tuple[Path, ...],
    *,
    project_name: str | None = None,
    env_file: Path | None = None,
) -> list[str]:
    command = [_docker(), "compose"]
    if project_name is not None:
        command.extend(("--project-name", project_name))
    if env_file is not None:
        command.extend(("--env-file", str(env_file.resolve(strict=True))))
    for compose_file in compose_files:
        command.extend(("-f", str(compose_file.resolve(strict=True))))
    return command


def compose_database_is_empty(
    *,
    compose_files: tuple[Path, ...],
    project_name: str | None = None,
    env_file: Path | None = None,
) -> bool:
    command = _compose_command(
        compose_files,
        project_name=project_name,
        env_file=env_file,
    )
    command.extend(
        (
            "exec",
            "-T",
            "media-bridge-db",
            "psql",
            "-U",
            "media_bridge",
            "-d",
            "media_bridge",
            "-Atqc",
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'",
        )
    )
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)  # noqa: S603
    except (OSError, subprocess.CalledProcessError) as error:
        raise RestoreError("database_inspection_failed") from error
    return result.stdout.strip() == "0"


def apply_to_compose(
    sql_dump: bytes,
    *,
    compose_files: tuple[Path, ...],
    project_name: str | None = None,
    env_file: Path | None = None,
) -> None:
    command = _compose_command(
        compose_files,
        project_name=project_name,
        env_file=env_file,
    )
    command.extend(
        (
            "exec",
            "-T",
            "media-bridge-db",
            "psql",
            "-U",
            "media_bridge",
            "-d",
            "media_bridge",
            "--set",
            "ON_ERROR_STOP=1",
            "--single-transaction",
        )
    )
    try:
        subprocess.run(command, input=sql_dump, check=True, capture_output=True)  # noqa: S603
    except (OSError, subprocess.CalledProcessError) as error:
        raise RestoreError("database_restore_failed") from error


def restore_archive(
    path: Path,
    *,
    database_is_empty: bool,
    confirmed: bool,
    apply_sql: Callable[[bytes], None],
) -> None:
    if not confirmed:
        raise RestoreError("confirmation_required")
    if not database_is_empty:
        raise RestoreError("target_database_not_empty")
    try:
        verify(path)
        with tarfile.open(path, "r:gz") as archive:
            member = archive.getmember("database.sql")
            stream = archive.extractfile(member)
            if stream is None:
                raise RestoreError("archive_member_invalid")
            sql_dump = stream.read()
    except (BackupVerificationError, OSError, tarfile.TarError) as error:
        raise RestoreError("backup_verification_failed") from error
    apply_sql(sql_dump)


def readiness_after_restore(*, secret_refs_connected: bool) -> str:
    return "ready" if secret_refs_connected else "limited"


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore a verified Media Bridge backup")
    parser.add_argument("backup", type=Path)
    parser.add_argument("--compose-file", action="append", type=Path, required=True)
    parser.add_argument("--project-name")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--confirm-empty-database", action="store_true")
    arguments = parser.parse_args()
    compose_files = tuple(arguments.compose_file)
    restore_archive(
        arguments.backup,
        database_is_empty=compose_database_is_empty(
            compose_files=compose_files,
            project_name=arguments.project_name,
            env_file=arguments.env_file,
        ),
        confirmed=arguments.confirm_empty_database,
        apply_sql=lambda sql: apply_to_compose(
            sql,
            compose_files=compose_files,
            project_name=arguments.project_name,
            env_file=arguments.env_file,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
