"""Ed25519 signing, immutable persistence, rollback, and atomic publication."""

from __future__ import annotations

import base64
import os
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import func, select, text

from media_bridge.config_snapshot import (
    SignedSnapshot,
    SnapshotVerificationError,
    snapshot_digest,
    snapshot_signature_message,
    validate_snapshot_body,
)
from media_bridge_control.db import Database
from media_bridge_control.models import SigningKey, Snapshot


class SnapshotPublishError(RuntimeError):
    pass


class SnapshotSigner:
    def __init__(self, *, key_id: str, private_key_pem: bytes) -> None:
        if not key_id or len(key_id) > 64:
            raise ValueError("snapshot key identifier is invalid")
        try:
            key = serialization.load_pem_private_key(private_key_pem, password=None)
        except (TypeError, ValueError) as error:
            raise ValueError("snapshot private key is invalid") from error
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("snapshot key must use Ed25519")
        self.key_id = key_id
        self._key = key

    @property
    def public_key_bytes(self) -> bytes:
        return self._key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    @property
    def public_key_text(self) -> str:
        return base64.urlsafe_b64encode(self.public_key_bytes).decode().rstrip("=")

    def sign(
        self,
        *,
        snapshot_id: UUID,
        version: int,
        issued_at: datetime,
        body: dict[str, Any],
    ) -> SignedSnapshot:
        try:
            validate_snapshot_body(body)
        except SnapshotVerificationError as error:
            raise ValueError("snapshot body is unsafe") from error
        unsigned = SignedSnapshot(
            schema="media-bridge-config/v1",
            snapshot_id=snapshot_id,
            version=version,
            issued_at=issued_at,
            body=body,
            digest=snapshot_digest(body),
            signature="ed25519:" + "A" * 86,
            key_id=self.key_id,
        )
        encoded = base64.urlsafe_b64encode(
            self._key.sign(snapshot_signature_message(unsigned))
        ).decode().rstrip("=")
        return unsigned.model_copy(update={"signature": f"ed25519:{encoded}"})


class SnapshotPublisher:
    def __init__(
        self,
        *,
        database: Database,
        signer: SnapshotSigner,
        output_path: Path,
        now: Callable[[], datetime],
    ) -> None:
        if not output_path.is_absolute():
            raise ValueError("snapshot output path must be absolute")
        self._database = database
        self._signer = signer
        self._output_path = output_path
        self._now = now

    def publish(
        self,
        body: dict[str, Any],
        *,
        source_draft_id: UUID | None = None,
        created_by: UUID | None = None,
    ) -> SignedSnapshot:
        with self._database.session() as session:
            session.execute(text("SELECT pg_advisory_xact_lock(628194733)"))
            stored_key = session.get(SigningKey, self._signer.key_id)
            if stored_key is None:
                session.add(
                    SigningKey(
                        key_id=self._signer.key_id,
                        algorithm="ed25519",
                        public_key=self._signer.public_key_text,
                    )
                )
            elif (
                stored_key.algorithm != "ed25519"
                or stored_key.public_key != self._signer.public_key_text
            ):
                raise SnapshotPublishError("snapshot public key metadata conflicts")
            current_version = session.scalar(
                select(func.coalesce(func.max(Snapshot.version), 0))
            )
            version = int(current_version or 0) + 1
            signed = self._signer.sign(
                snapshot_id=uuid4(),
                version=version,
                issued_at=self._now(),
                body=body,
            )
            session.add(
                Snapshot(
                    id=signed.snapshot_id,
                    version=signed.version,
                    schema_version=signed.schema_name,
                    body=signed.body,
                    digest=signed.digest,
                    signature=signed.signature,
                    key_id=signed.key_id,
                    source_draft_id=source_draft_id,
                    created_by=created_by,
                )
            )
        self._atomic_write(signed)
        return signed

    def rollback(self, version: int, *, created_by: UUID | None = None) -> SignedSnapshot:
        with self._database.session() as session:
            previous = session.scalar(select(Snapshot).where(Snapshot.version == version))
            if previous is None:
                raise SnapshotPublishError("snapshot version was not found")
            body = dict(previous.body)
        return self.publish(body, created_by=created_by)

    def list(self) -> list[dict[str, Any]]:
        with self._database.session() as session:
            rows = list(session.scalars(select(Snapshot).order_by(Snapshot.version.desc())))
            return [
                {
                    "snapshot_id": str(row.id),
                    "version": row.version,
                    "schema": row.schema_version,
                    "digest": row.digest,
                    "key_id": row.key_id,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]

    def _atomic_write(self, snapshot: SignedSnapshot) -> None:
        parent = self._output_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        if parent.is_symlink() or self._output_path.is_symlink():
            raise SnapshotPublishError("snapshot output path cannot use symlinks")
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=parent,
                prefix=".media-bridge-snapshot-",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(snapshot.model_dump_json())
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.chmod(0o600)
            os.replace(temporary_path, self._output_path)
            directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as error:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise SnapshotPublishError("snapshot could not be published atomically") from error
