"""Tenant-scoped, one-shot local asset storage."""

from __future__ import annotations

import os
import re
import secrets
import threading
from dataclasses import dataclass
from pathlib import Path


class AssetAccessError(RuntimeError):
    """Raised for missing, unauthorized, already-consumed, or undeletable assets."""


@dataclass(frozen=True, slots=True)
class ConsumedAsset:
    data: bytes
    filename: str | None
    declared_mime: str | None


@dataclass(frozen=True, slots=True)
class _AssetRecord:
    tenant_id: str
    path: Path
    filename: str | None
    declared_mime: str | None


_TENANT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_tenant_id(tenant_id: str) -> None:
    if _TENANT_ID.fullmatch(tenant_id) is None:
        raise AssetAccessError("tenant identifier is invalid")


class AssetStore:
    """An ephemeral asset store that deletes bytes before returning consumption."""

    def __init__(self, root: Path, *, max_bytes: int = 2 * 1024 * 1024) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root.chmod(0o700)
        self.root = root
        self.max_bytes = max_bytes
        self._records: dict[str, _AssetRecord] = {}
        self._lock = threading.Lock()

    def put(
        self,
        *,
        tenant_id: str,
        data: bytes,
        filename: str | None = None,
        declared_mime: str | None = None,
    ) -> str:
        validate_tenant_id(tenant_id)
        if len(data) > self.max_bytes:
            raise AssetAccessError("asset exceeds the configured byte limit")
        if filename is not None and (Path(filename).name != filename or len(filename) > 255):
            raise AssetAccessError("asset filename is unsafe")

        asset_id = f"mb_{secrets.token_urlsafe(24)}"
        destination = self.root / f"{asset_id}.bin"
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
        except BaseException:
            if destination.exists():
                destination.unlink()
            raise

        with self._lock:
            self._records[asset_id] = _AssetRecord(
                tenant_id=tenant_id,
                path=destination,
                filename=filename,
                declared_mime=declared_mime,
            )
        return asset_id

    def consume(self, *, asset_id: str, tenant_id: str) -> ConsumedAsset:
        """Read, delete, verify deletion, then return a tenant-owned asset."""

        validate_tenant_id(tenant_id)
        with self._lock:
            record = self._records.get(asset_id)
            if record is None or not secrets.compare_digest(record.tenant_id, tenant_id):
                raise AssetAccessError("asset is unavailable")
            try:
                data = record.path.read_bytes()
                record.path.unlink()
            except OSError as error:
                raise AssetAccessError("asset could not be consumed safely") from error
            if record.path.exists():
                raise AssetAccessError("asset deletion could not be verified")
            del self._records[asset_id]

        if len(data) > self.max_bytes:
            raise AssetAccessError("asset exceeds the configured byte limit")
        return ConsumedAsset(
            data=data,
            filename=record.filename,
            declared_mime=record.declared_mime,
        )
