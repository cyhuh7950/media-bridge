"""Marker-scoped OpenCodex custom-provider configuration management."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ENV = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
_TENANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class OpenCodexConfigError(ValueError):
    """Safe, user-facing configuration error without secret material."""


def _canonical(value: object) -> bytes:
    text = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    return text.encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(_canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        os.chmod(path, 0o600)
    finally:
        temp.unlink(missing_ok=True)


def _validate_base_url(value: str) -> str:
    if value != value.strip():
        raise OpenCodexConfigError("endpoint_invalid")
    parsed = urlsplit(value)
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/v1"
    ):
        raise OpenCodexConfigError("endpoint_invalid")
    if parsed.scheme == "https":
        return value
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1", "localhost"}:
        return value
    raise OpenCodexConfigError("endpoint_invalid")


class OpenCodexConfigManager:
    """Apply and remove only a provider entry owned by this manager."""

    def __init__(self, *, config_path: Path, marker_path: Path) -> None:
        self.config_path = config_path
        self.marker_path = marker_path

    def apply(
        self,
        *,
        provider_name: str,
        endpoint: str,
        model: str,
        credential_env: str,
        tenant_id: str,
    ) -> dict[str, str]:
        if (
            not _NAME.fullmatch(provider_name)
            or not _NAME.fullmatch(model)
            or not _TENANT.fullmatch(tenant_id)
        ):
            raise OpenCodexConfigError("identifier_invalid")
        if not _ENV.fullmatch(credential_env):
            raise OpenCodexConfigError("credential_reference_invalid")
        endpoint = _validate_base_url(endpoint)
        config = self._read_config()
        providers = config.setdefault("providers", {})
        if not isinstance(providers, dict):
            raise OpenCodexConfigError("config_invalid")
        if provider_name in providers and self.marker_path.exists():
            raise OpenCodexConfigError("already_owned")
        if provider_name in providers:
            raise OpenCodexConfigError("unowned_provider_present")
        previous = json.loads(json.dumps(config))
        managed = json.loads(json.dumps(config))
        managed["defaultProvider"] = provider_name
        managed["providers"][provider_name] = {
            "adapter": "openai-responses",
            "baseUrl": endpoint,
            "apiKey": f"env:{credential_env}",
            "defaultModel": model,
            "allowPrivateNetwork": True,
            "headers": {"X-Media-Bridge-Tenant": tenant_id},
        }
        backup = self.marker_path.with_name(
            f"{self.marker_path.name}.{_digest(previous)[:16]}.backup.json"
        )
        _atomic_write(backup, previous)
        _atomic_write(self.config_path, managed)
        _atomic_write(
            self.marker_path,
            {
                "schema": 1,
                "provider": provider_name,
                "preimage_digest": _digest(previous),
                "managed_digest": _digest(managed),
                "backup_name": backup.name,
            },
        )
        return {"status": "applied", "provider": provider_name, "config_digest": _digest(managed)}

    def remove(self) -> dict[str, str]:
        marker = self._read_marker()
        config = self._read_config()
        if _digest(config) != marker.get("managed_digest"):
            raise OpenCodexConfigError("owned_config_changed")
        backup = self.marker_path.with_name(str(marker.get("backup_name", "")))
        previous = self._read_json(backup)
        _atomic_write(self.config_path, previous)
        self.marker_path.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)
        return {"status": "removed", "provider": str(marker["provider"])}

    def _read_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {"providers": {}}
        value = self._read_json(self.config_path)
        if not isinstance(value, dict):
            raise OpenCodexConfigError("config_invalid")
        return value

    def _read_marker(self) -> dict[str, Any]:
        if not self.marker_path.exists():
            raise OpenCodexConfigError("ownership_marker_missing")
        marker = self._read_json(self.marker_path)
        if (
            not isinstance(marker, dict)
            or marker.get("schema") != 1
            or not isinstance(marker.get("provider"), str)
        ):
            raise OpenCodexConfigError("ownership_marker_invalid")
        return marker

    @staticmethod
    def _read_json(path: Path) -> Any:
        try:
            with path.open(encoding="utf-8") as stream:
                return json.load(stream)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OpenCodexConfigError("config_unreadable") from error
