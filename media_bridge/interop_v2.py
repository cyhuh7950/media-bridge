"""Transformation receipts and cleanup barriers for Media Bridge interop v2."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from media_bridge.contracts_v2 import InteropV2Result, PreparedMarker


class ReceiptValidationError(ValueError):
    """Raised when transformation evidence cannot authorize downstream use."""


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class TransformationReceipt:
    contract_version: str
    request_id: str
    trace_id: str
    idempotency_key: str
    transformation_version: str
    input_digest: str
    output_digest: str
    schema_digest: str
    original_media_removed: bool
    issued_at: datetime
    expires_at: datetime

    def safe_dict(self) -> dict[str, Any]:
        """Return metadata only; no prompt, OCR text, Secret, or media bytes."""

        return {
            "contract_version": self.contract_version,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "idempotency_key": self.idempotency_key,
            "transformation_version": self.transformation_version,
            "input_digest": self.input_digest,
            "output_digest": self.output_digest,
            "schema_digest": self.schema_digest,
            "original_media_removed": self.original_media_removed,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


def build_transformation_receipt(
    result: InteropV2Result,
    *,
    now: datetime | None = None,
    ttl_seconds: int = 30,
    expected_schema_digest: str | None = None,
) -> TransformationReceipt:
    if result.status != "PREPARED" or not result.original_media_removed:
        raise ReceiptValidationError("only media-free PREPARED results can be receipted")
    marker = result.prepared_marker
    if marker is None:
        raise ReceiptValidationError("prepared marker is required")
    if expected_schema_digest is not None and marker.schema_digest != expected_schema_digest:
        raise ReceiptValidationError("schema digest mismatch")
    issued = now or datetime.now(UTC)
    if issued.tzinfo is None:
        issued = issued.replace(tzinfo=UTC)
    if ttl_seconds < 1 or ttl_seconds > 300:
        raise ReceiptValidationError("receipt ttl is outside the allowed range")
    expires = issued + timedelta(seconds=ttl_seconds)
    if expires > marker.expires_at:
        raise ReceiptValidationError("receipt ttl exceeds asset ttl")
    return TransformationReceipt(
        contract_version=result.contract_version,
        request_id=result.request_id,
        trace_id=result.trace_id,
        idempotency_key=result.idempotency_key,
        transformation_version=result.backend.version if result.backend else "unknown",
        input_digest=_digest(result.asset_digests),
        output_digest=_digest(result.sanitized_messages),
        schema_digest=marker.schema_digest,
        original_media_removed=True,
        issued_at=issued,
        expires_at=expires,
    )


class CleanupBarrier:
    """Require verified deletion of every referenced asset before release."""

    def __init__(self, asset_ids: list[str] | tuple[str, ...]) -> None:
        if not asset_ids or len(set(asset_ids)) != len(asset_ids):
            raise ValueError("cleanup barrier requires unique asset ids")
        self._expected = frozenset(asset_ids)
        self._verified: set[str] = set()

    def mark_deleted(self, asset_id: str, *, verified: bool) -> None:
        if asset_id not in self._expected:
            raise ReceiptValidationError("unexpected asset cleanup reference")
        if verified:
            self._verified.add(asset_id)

    def finalize(self) -> bool:
        if self._verified != self._expected:
            raise ReceiptValidationError("cleanup barrier is incomplete")
        return True


def validate_cleanup_ttl(marker: PreparedMarker, *, asset_expires_at: datetime) -> None:
    if asset_expires_at.tzinfo is None:
        asset_expires_at = asset_expires_at.replace(tzinfo=UTC)
    if asset_expires_at <= datetime.now(UTC):
        raise ReceiptValidationError("asset has expired")
    if marker.expires_at > asset_expires_at:
        raise ReceiptValidationError("result ttl cannot outlive asset ttl")
