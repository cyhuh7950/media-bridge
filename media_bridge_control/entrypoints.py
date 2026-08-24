"""Control Plane startup with a fail-closed migration guard."""

from __future__ import annotations

import ipaddress
import os

import uvicorn
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from media_bridge_control.db import Database
from media_bridge_control.runtime import build_control_runtime
from media_bridge_control.settings import ControlSettings

EXPECTED_MIGRATION_HEAD = "0002_connections"


class MigrationStateError(RuntimeError):
    pass


class ControlEntrypointError(RuntimeError):
    pass


def require_migration_head(database_url: str) -> None:
    database = Database(database_url)
    try:
        with database.engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    except SQLAlchemyError as error:
        raise MigrationStateError("control_plane_migration_required") from error
    finally:
        database.close()
    if revision != EXPECTED_MIGRATION_HEAD:
        raise MigrationStateError("control_plane_migration_required")


def run_control() -> None:
    settings = ControlSettings.from_environment()
    require_migration_head(settings.database_url)
    bind_host = os.environ.get("MEDIA_BRIDGE_CONTROL_BIND_HOST", "127.0.0.1").strip()
    try:
        ipaddress.ip_address(bind_host)
        bind_port = int(os.environ.get("MEDIA_BRIDGE_CONTROL_PORT", "8081"))
    except ValueError as error:
        raise ControlEntrypointError("control_plane_bind_invalid") from error
    if bind_port < 1 or bind_port > 65_535:
        raise ControlEntrypointError("control_plane_bind_invalid")
    runtime = build_control_runtime(settings)
    try:
        uvicorn.run(
            runtime.app,
            host=bind_host,
            port=bind_port,
            access_log=False,
            server_header=False,
        )
    finally:
        runtime.close()
