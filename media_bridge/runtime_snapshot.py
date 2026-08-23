"""Data Plane registry adapter for a last-known-good signed snapshot."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, ValidationError, field_validator

from media_bridge.capabilities import CapabilityRegistry, ModelCapability
from media_bridge.config_snapshot import LastKnownGoodSnapshot, SnapshotVerificationError
from media_bridge.contracts import StrictModel


class SnapshotModelEntry(StrictModel):
    model_id: Annotated[
        str,
        StringConstraints(pattern=r"^[a-z0-9][a-z0-9./:_-]{0,127}$"),
    ] = Field(alias="id")
    input_modalities: set[Literal["text", "image", "pdf"]]
    expires_at: datetime
    pdf_passthrough_verified: bool = False

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("capability expiry must be timezone-aware")
        return value


class SnapshotRegistry(StrictModel):
    version: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    models: Annotated[list[SnapshotModelEntry], Field(min_length=1)]


class SnapshotRuntimeSource:
    def __init__(self, store: LastKnownGoodSnapshot) -> None:
        self._store = store

    @property
    def snapshot_version(self) -> int:
        return self._store.current().version

    def capability_registry(self) -> CapabilityRegistry:
        snapshot = self._store.current()
        try:
            registry = SnapshotRegistry.model_validate(snapshot.body.get("registry"))
            capabilities = [
                ModelCapability(
                    model_id=item.model_id,
                    input_modalities=set(item.input_modalities),
                    expires_at=item.expires_at,
                    pdf_passthrough_verified=item.pdf_passthrough_verified,
                )
                for item in registry.models
            ]
            return CapabilityRegistry(capabilities, version=registry.version)
        except (ValidationError, ValueError, TypeError) as error:
            raise SnapshotVerificationError("snapshot registry is invalid") from error
