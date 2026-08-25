"""Migration decision boundary used before Control Plane startup."""

from __future__ import annotations

import argparse
import os
import shutil
from collections.abc import Callable
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

SUPPORTED_REVISIONS = frozenset({None, "0001_control_plane", "0002_connections"})


class MigrationError(RuntimeError):
    pass


def run_migration(
    *,
    current_revision: str | None,
    target_revision: str,
    apply: bool,
    upgrade: Callable[[str], None],
) -> str:
    if current_revision not in SUPPORTED_REVISIONS or target_revision not in SUPPORTED_REVISIONS:
        raise MigrationError("schema_revision_unsupported")
    if current_revision == target_revision:
        return "schema_current"
    if current_revision == "0002_connections" and target_revision != current_revision:
        raise MigrationError("schema_revision_unsupported")
    if not apply:
        return "migration_required"
    upgrade(target_revision)
    return "migration_applied"


def read_database_url(path: Path) -> str:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4_096:
            raise MigrationError("database_secret_invalid")
        value = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise MigrationError("database_secret_invalid") from error
    if not value.startswith("postgresql+psycopg://"):
        raise MigrationError("database_secret_invalid")
    return value


def current_revision(database_url: str) -> str | None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            if not inspect(connection).has_table("alembic_version"):
                return None
            value = connection.scalar(text("SELECT version_num FROM alembic_version"))
            return str(value) if value is not None else None
    except SQLAlchemyError as error:
        raise MigrationError("database_unavailable") from error
    finally:
        engine.dispose()


def apply_database_migration(*, database_url: str, alembic_ini: Path, apply: bool) -> str:
    current = current_revision(database_url)

    def upgrade(target: str) -> None:
        config = Config(str(alembic_ini))
        config.set_main_option("script_location", str(alembic_ini.parent))
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, target)

    result = run_migration(
        current_revision=current,
        target_revision="0002_connections",
        apply=apply,
        upgrade=upgrade,
    )
    if apply and current_revision(database_url) != "0002_connections":
        raise MigrationError("migration_verification_failed")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate the Media Bridge Control Plane schema")
    parser.add_argument("--database-url-file", type=Path, required=True)
    parser.add_argument("--alembic-ini", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--start-control", action="store_true")
    arguments = parser.parse_args()
    result = apply_database_migration(
        database_url=read_database_url(arguments.database_url_file),
        alembic_ini=arguments.alembic_ini,
        apply=arguments.apply,
    )
    if arguments.start_control:
        if not arguments.apply:
            raise MigrationError("start_requires_apply")
        executable = shutil.which("media-bridge-control")
        if executable is None or not Path(executable).is_absolute():
            raise MigrationError("control_executable_unavailable")
        os.execv(executable, [executable])  # noqa: S606
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
