"""Atomic local active/previous snapshot storage for a single-user installation."""

from __future__ import annotations

import json
import os
import secrets
from contextlib import suppress
from pathlib import Path
from typing import Any

_FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "api_key",
        "credential",
        "media_body",
        "password",
        "secret",
        "token",
    }
)


class LocalStateError(RuntimeError):
    """The persisted personal runtime state is unavailable or invalid."""


class PersonalStateStore:
    """Maintain an active snapshot and the immediately preceding LKG snapshot."""

    def __init__(self, *, root: Path) -> None:
        self._root = root
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self._root.is_symlink() or not self._root.is_dir():
            raise LocalStateError("state_root_invalid")

    @property
    def _active_path(self) -> Path:
        return self._root / "active.json"

    @property
    def _previous_path(self) -> Path:
        return self._root / "previous.json"

    def publish(self, snapshot: dict[str, Any]) -> None:
        serialized = self._serialize(snapshot)
        previous = self._read_valid(self._active_path, missing_ok=True)
        if previous is not None:
            self._write_atomic(self._previous_path, self._serialize(previous))
        self._write_atomic(self._active_path, serialized)

    def load_last_known_good(self) -> dict[str, Any]:
        active = self._read_valid(self._active_path, missing_ok=True)
        if active is not None:
            return active
        previous = self._read_valid(self._previous_path, missing_ok=True)
        if previous is not None:
            return previous
        raise LocalStateError("no_valid_snapshot")

    def _read_valid(self, path: Path, *, missing_ok: bool) -> dict[str, Any] | None:
        try:
            if path.is_symlink() or not path.is_file():
                if missing_ok:
                    return None
                raise LocalStateError("snapshot_unavailable")
            return self._validate(json.loads(path.read_text(encoding="utf-8")))
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            LocalStateError,
            TypeError,
            ValueError,
        ):
            return None if missing_ok else self._raise_invalid()

    @staticmethod
    def _raise_invalid() -> None:
        raise LocalStateError("snapshot_invalid")

    @staticmethod
    def _validate(value: object) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("snapshot must be an object")
        version = value.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ValueError("snapshot version is invalid")
        PersonalStateStore._validate_safe_values(value)
        return value

    @classmethod
    def _validate_safe_values(cls, value: object, *, field_name: str | None = None) -> None:
        if field_name is not None and field_name.lower() in _FORBIDDEN_FIELD_NAMES:
            raise LocalStateError("snapshot_sensitive_value")
        if isinstance(value, dict):
            for key, nested in value.items():
                if not isinstance(key, str):
                    raise LocalStateError("snapshot_invalid")
                cls._validate_safe_values(nested, field_name=key)
            return
        if isinstance(value, list):
            for nested in value:
                cls._validate_safe_values(nested)
            return
        if isinstance(value, str):
            if (
                field_name is not None
                and field_name.lower().endswith("_path")
                and os.path.isabs(value)
            ):
                raise LocalStateError("snapshot_sensitive_value")
            return
        if value is None or isinstance(value, bool | int | float):
            return
        raise LocalStateError("snapshot_invalid")

    def _serialize(self, snapshot: dict[str, Any]) -> bytes:
        self._validate(snapshot)
        try:
            return (
                json.dumps(
                    snapshot,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError, OverflowError) as error:
            raise LocalStateError("snapshot_not_serializable") from error

    def _write_atomic(self, destination: Path, content: bytes) -> None:
        temporary = self._root / f".{destination.name}.{secrets.token_hex(8)}.tmp"
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
            directory = os.open(self._root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError as error:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
            raise LocalStateError("snapshot_write_failed") from error
