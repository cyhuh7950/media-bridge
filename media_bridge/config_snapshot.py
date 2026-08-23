"""Signed immutable configuration snapshots consumed by the Data Plane."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import ConfigDict, Field, StringConstraints, ValidationError, field_validator

from media_bridge.contracts import StrictModel

MAX_SNAPSHOT_BYTES = 1024 * 1024
SENSITIVE_BODY_KEYS = frozenset(
    {
        "api_key",
        "base64",
        "credential",
        "file_data",
        "image_url",
        "local_path",
        "ocr_text",
        "password",
        "private_key",
        "prompt",
        "provider_secret",
        "secret",
        "token",
        "visual_description",
    }
)


class SnapshotVerificationError(RuntimeError):
    pass


class SignedSnapshot(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True, serialize_by_alias=True)

    schema_name: Literal["media-bridge-config/v1"] = Field(alias="schema")
    snapshot_id: UUID
    version: Annotated[int, Field(ge=1)]
    issued_at: datetime
    body: dict[str, Any]
    digest: Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
    signature: Annotated[
        str,
        StringConstraints(pattern=r"^ed25519:[A-Za-z0-9_-]{86}$"),
    ]
    key_id: Annotated[
        str,
        StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"),
    ]

    @field_validator("issued_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("snapshot issued_at must be timezone-aware")
        return value


def canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    except (TypeError, ValueError, OverflowError) as error:
        raise SnapshotVerificationError("snapshot is not canonicalizable") from error


def validate_snapshot_body(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str) or key.lower().replace("-", "_") in SENSITIVE_BODY_KEYS:
                raise SnapshotVerificationError("snapshot body contains a forbidden field")
            validate_snapshot_body(nested)
        return
    if isinstance(value, list):
        for nested in value:
            validate_snapshot_body(nested)
        return
    if value is not None and not isinstance(value, str | int | float | bool):
        raise SnapshotVerificationError("snapshot body contains an unsupported value")


def snapshot_digest(body: dict[str, Any]) -> str:
    validate_snapshot_body(body)
    return f"sha256:{hashlib.sha256(canonical_json(body)).hexdigest()}"


def snapshot_signature_message(snapshot: SignedSnapshot) -> bytes:
    return canonical_json(
        {
            "schema": snapshot.schema_name,
            "snapshot_id": str(snapshot.snapshot_id),
            "version": snapshot.version,
            "issued_at": snapshot.issued_at.isoformat(),
            "body": snapshot.body,
            "digest": snapshot.digest,
            "key_id": snapshot.key_id,
        }
    )


def _decode_signature(value: str) -> bytes:
    encoded = value.removeprefix("ed25519:")
    try:
        return base64.urlsafe_b64decode(encoded + "==")
    except ValueError as error:
        raise SnapshotVerificationError("snapshot signature is invalid") from error


class SnapshotVerifier:
    def __init__(self, public_keys: dict[str, bytes]) -> None:
        if not public_keys:
            raise ValueError("at least one snapshot public key is required")
        self._keys = {
            key_id: Ed25519PublicKey.from_public_bytes(value)
            for key_id, value in public_keys.items()
        }

    def verify_json(self, serialized: str) -> SignedSnapshot:
        if len(serialized.encode()) > MAX_SNAPSHOT_BYTES:
            raise SnapshotVerificationError("snapshot exceeds the configured limit")
        try:
            payload = json.loads(serialized)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise SnapshotVerificationError("snapshot JSON is invalid") from error
        return self.verify_object(payload)

    def verify_object(self, payload: object) -> SignedSnapshot:
        try:
            snapshot = SignedSnapshot.model_validate(payload)
            validate_snapshot_body(snapshot.body)
            if snapshot.digest != snapshot_digest(snapshot.body):
                raise SnapshotVerificationError("snapshot digest does not match")
            key = self._keys.get(snapshot.key_id)
            if key is None:
                raise SnapshotVerificationError("snapshot signing key is unknown")
            key.verify(_decode_signature(snapshot.signature), snapshot_signature_message(snapshot))
            return snapshot
        except SnapshotVerificationError:
            raise
        except (InvalidSignature, ValidationError, ValueError, TypeError) as error:
            raise SnapshotVerificationError("snapshot verification failed") from error


class LastKnownGoodSnapshot:
    """Atomically replace state only after full snapshot verification."""

    def __init__(self, verifier: SnapshotVerifier) -> None:
        self._verifier = verifier
        self._lock = threading.Lock()
        self._current: SignedSnapshot | None = None

    def load(self, path: Path) -> SignedSnapshot:
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SNAPSHOT_BYTES:
                raise SnapshotVerificationError("snapshot file is unavailable or oversized")
            serialized = path.read_text(encoding="utf-8")
        except OSError as error:
            raise SnapshotVerificationError("snapshot file could not be read") from error
        candidate = self._verifier.verify_json(serialized)
        with self._lock:
            if self._current is not None and candidate.version <= self._current.version:
                raise SnapshotVerificationError("snapshot version is stale or replayed")
            self._current = copy.deepcopy(candidate)
            return copy.deepcopy(candidate)

    def current(self) -> SignedSnapshot:
        with self._lock:
            if self._current is None:
                raise SnapshotVerificationError("no valid snapshot has been loaded")
            return copy.deepcopy(self._current)
