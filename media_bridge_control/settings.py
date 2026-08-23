"""Exact environment and Secret-file settings for the Control Plane."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


class ControlSettingsError(RuntimeError):
    pass


def _secret(value_name: str, file_name: str, *, max_bytes: int = 65_536) -> bytes:
    value = os.environ.get(value_name)
    file_value = os.environ.get(file_name)
    if value and file_value:
        raise ControlSettingsError(f"{value_name} has conflicting secret sources")
    if value:
        encoded = value.encode()
        if len(encoded) > max_bytes:
            raise ControlSettingsError(f"{value_name} is oversized")
        return encoded
    if not file_value:
        raise ControlSettingsError(f"{value_name} is not configured")
    path = Path(file_value)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
            raise ControlSettingsError(f"{value_name} secret file is invalid")
        result = path.read_bytes().strip()
    except OSError as error:
        raise ControlSettingsError(f"{value_name} secret file is unavailable") from error
    if not result:
        raise ControlSettingsError(f"{value_name} secret file is empty")
    return result


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ControlSettingsError(f"{name} is not configured")
    return value


@dataclass(frozen=True, slots=True)
class ControlSettings:
    database_url: str = field(repr=False)
    security_pepper: bytes = field(repr=False)
    snapshot_private_key_pem: bytes = field(repr=False)
    snapshot_key_id: str
    snapshot_path: Path
    allowed_origin: str
    allowed_host: str
    console_static_root: Path | None = None

    @classmethod
    def from_environment(cls) -> ControlSettings:
        database_url = _secret(
            "MEDIA_BRIDGE_CONTROL_DATABASE_URL",
            "MEDIA_BRIDGE_CONTROL_DATABASE_URL_FILE",
            max_bytes=4_096,
        ).decode()
        if not database_url.startswith("postgresql+psycopg://"):
            raise ControlSettingsError("Control Plane database must use PostgreSQL")
        pepper = _secret(
            "MEDIA_BRIDGE_CONTROL_SECURITY_PEPPER",
            "MEDIA_BRIDGE_CONTROL_SECURITY_PEPPER_FILE",
            max_bytes=4_096,
        )
        if len(pepper) < 32:
            raise ControlSettingsError("Control Plane security pepper is too short")
        private_key = _secret(
            "MEDIA_BRIDGE_SNAPSHOT_PRIVATE_KEY",
            "MEDIA_BRIDGE_SNAPSHOT_PRIVATE_KEY_FILE",
        )
        key_id = _required("MEDIA_BRIDGE_SNAPSHOT_KEY_ID")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", key_id) is None:
            raise ControlSettingsError("snapshot key identifier is invalid")
        snapshot_path = Path(_required("MEDIA_BRIDGE_SNAPSHOT_PATH"))
        if not snapshot_path.is_absolute() or snapshot_path.is_symlink():
            raise ControlSettingsError("snapshot path must be absolute and non-symlink")
        origin = _required("MEDIA_BRIDGE_CONTROL_ORIGIN")
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ControlSettingsError("Control Plane origin must be credential-free HTTPS")
        host = _required("MEDIA_BRIDGE_CONTROL_HOST").lower()
        if host != parsed.hostname.lower():
            raise ControlSettingsError("Control Plane host and origin do not match")
        static_value = os.environ.get("MEDIA_BRIDGE_CONSOLE_STATIC_ROOT", "").strip()
        console_static_root = Path(static_value) if static_value else None
        if console_static_root is not None and (
            not console_static_root.is_absolute() or console_static_root.is_symlink()
        ):
            raise ControlSettingsError("Web Console static root is invalid")
        return cls(
            database_url=database_url,
            security_pepper=pepper,
            snapshot_private_key_pem=private_key,
            snapshot_key_id=key_id,
            snapshot_path=snapshot_path,
            allowed_origin=origin,
            allowed_host=host,
            console_static_root=console_static_root,
        )
