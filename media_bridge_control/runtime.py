"""Control Plane composition without service registration or deployment side effects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from starlette.applications import Starlette

from media_bridge_control.api import build_control_app
from media_bridge_control.bootstrap import ControlPlaneService
from media_bridge_control.db import Database
from media_bridge_control.security import SecurityContext
from media_bridge_control.settings import ControlSettings
from media_bridge_control.snapshots import SnapshotPublisher, SnapshotSigner


@dataclass(slots=True)
class ControlRuntime:
    database: Database
    service: ControlPlaneService
    snapshot_publisher: SnapshotPublisher
    app: Starlette

    def close(self) -> None:
        self.database.close()


def build_control_runtime(settings: ControlSettings) -> ControlRuntime:
    database = Database(settings.database_url)
    security = SecurityContext(pepper=settings.security_pepper)
    service = ControlPlaneService(
        database=database,
        security=security,
        now=lambda: datetime.now(UTC),
    )
    signer = SnapshotSigner(
        key_id=settings.snapshot_key_id,
        private_key_pem=settings.snapshot_private_key_pem,
    )
    publisher = SnapshotPublisher(
        database=database,
        signer=signer,
        output_path=settings.snapshot_path,
        now=lambda: datetime.now(UTC),
    )
    app = build_control_app(
        service=service,
        allowed_origin=settings.allowed_origin,
        allowed_host=settings.allowed_host,
        snapshot_publisher=publisher,
    )
    return ControlRuntime(
        database=database,
        service=service,
        snapshot_publisher=publisher,
        app=app,
    )
