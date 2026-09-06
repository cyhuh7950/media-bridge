"""Tenant-scoped, one-shot local asset storage."""

from __future__ import annotations

import os
import re
import secrets
import threading
import time
from collections.abc import Callable
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
    expires_at: float


_TENANT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_tenant_id(tenant_id: str) -> None:
    if _TENANT_ID.fullmatch(tenant_id) is None:
        raise AssetAccessError("tenant identifier is invalid")


class AssetStore:
    """An ephemeral asset store that deletes bytes before returning consumption."""

    def __init__(
        self,
        root: Path,
        *,
        max_bytes: int = 2 * 1024 * 1024,
        ttl_seconds: int = 300,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        if ttl_seconds < 1 or ttl_seconds > 3_600:
            raise ValueError("asset ttl must be between 1 and 3600 seconds")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root.chmod(0o700)
        self.root = root
        self.max_bytes = max_bytes
        self._ttl_seconds = ttl_seconds
        self._clock = clock
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
        self.purge_expired()
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
                expires_at=self._clock() + self._ttl_seconds,
            )
        return asset_id

    def consume(self, *, asset_id: str, tenant_id: str) -> ConsumedAsset:
        """Read, delete, verify deletion, then return a tenant-owned asset."""

        self.purge_expired()
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

    def delete(self, *, asset_id: str, tenant_id: str) -> bool:
        """Delete a tenant-owned asset, returning false when it is unavailable."""

        self.purge_expired()
        validate_tenant_id(tenant_id)
        with self._lock:
            record = self._records.get(asset_id)
            if record is None or not secrets.compare_digest(record.tenant_id, tenant_id):
                return False
            try:
                record.path.unlink(missing_ok=True)
            except OSError as error:
                raise AssetAccessError("asset could not be deleted safely") from error
            if record.path.exists():
                raise AssetAccessError("asset deletion could not be verified")
            del self._records[asset_id]
        return True

    def purge_expired(self) -> None:
        """Delete expired, unconsumed assets and verify every deletion."""

        now = self._clock()
        with self._lock:
            expired = [
                (asset_id, record)
                for asset_id, record in self._records.items()
                if record.expires_at <= now
            ]
            for asset_id, record in expired:
                try:
                    record.path.unlink(missing_ok=True)
                except OSError as error:
                    raise AssetAccessError("expired asset cleanup failed") from error
                if record.path.exists():
                    raise AssetAccessError("expired asset cleanup could not be verified")
                del self._records[asset_id]

    def clear(self) -> None:
        """Delete every outstanding asset during graceful shutdown."""

        with self._lock:
            for record in self._records.values():
                try:
                    record.path.unlink(missing_ok=True)
                except OSError as error:
                    raise AssetAccessError("asset shutdown cleanup failed") from error
                if record.path.exists():
                    raise AssetAccessError("asset shutdown cleanup could not be verified")
            self._records.clear()
