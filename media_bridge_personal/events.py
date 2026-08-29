"""Bounded, metadata-only local event storage for the personal runtime."""

from __future__ import annotations

import json
import os
import secrets
from contextlib import suppress
from pathlib import Path
from typing import Any

_FORBIDDEN_FIELD_NAMES = frozenset(
    {"api_key", "credential", "media_body", "password", "secret", "token"}
)
_MAX_EVENT_BYTES = 1024


class PersonalEventLogError(RuntimeError):
    pass


class PersonalEventLog:
    def __init__(self, *, root: Path, max_entries: int) -> None:
        if max_entries < 1:
            raise ValueError("event limit must be positive")
        self._root = root
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self._root.is_symlink() or not self._root.is_dir():
            raise PersonalEventLogError("event_root_invalid")
        self._max_entries = max_entries

    @property
    def _path(self) -> Path:
        return self._root / "events.jsonl"

    def append(self, event: dict[str, Any]) -> None:
        validated = self._validate_event(event)
        entries = self.read()
        entries.append(validated)
        self._write_atomic(entries[-self._max_entries :])

    def read(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            if self._path.is_symlink() or not self._path.is_file():
                raise PersonalEventLogError("event_log_invalid")
            rows = self._path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as error:
            raise PersonalEventLogError("event_log_unavailable") from error
        try:
            return [self._validate_event(json.loads(row)) for row in rows]
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise PersonalEventLogError("event_log_invalid") from error

    @staticmethod
    def _validate_event(event: object) -> dict[str, Any]:
        if not isinstance(event, dict):
            raise PersonalEventLogError("event_invalid")
        safe: dict[str, Any] = {}
        for key, value in event.items():
            if not isinstance(key, str):
                raise PersonalEventLogError("event_invalid")
            lowered = key.lower()
            if lowered in _FORBIDDEN_FIELD_NAMES:
                raise PersonalEventLogError("event_sensitive_value")
            if not isinstance(value, str | int | bool) and value is not None:
                raise PersonalEventLogError("event_invalid")
            if isinstance(value, str) and (
                len(value.encode("utf-8")) > 256
                or (lowered.endswith("_path") and os.path.isabs(value))
            ):
                raise PersonalEventLogError("event_sensitive_value")
            safe[key] = value
        encoded = json.dumps(
            safe,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
        ).encode("utf-8")
        if len(encoded) > _MAX_EVENT_BYTES:
            raise PersonalEventLogError("event_invalid")
        return safe

    def _write_atomic(self, entries: list[dict[str, Any]]) -> None:
        content = b"".join(
            json.dumps(
                entry,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
            for entry in entries
        )
        temporary = self._root / f".{self._path.name}.{secrets.token_hex(8)}.tmp"
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        except OSError as error:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
            raise PersonalEventLogError("event_write_failed") from error
