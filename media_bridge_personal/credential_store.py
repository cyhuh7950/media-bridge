"""Private per-user credentials for the npm personal runtime."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
from pathlib import Path
from typing import Any

_REFERENCE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class CredentialStoreError(RuntimeError):
    """Raised when the local credential store is invalid or unsafe."""


class CredentialStore:
    """Store secrets separately from normal configuration with private permissions."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def _validate_reference(reference: str) -> str:
        value = reference.strip()
        if _REFERENCE.fullmatch(value) is None:
            raise CredentialStoreError("credential reference is invalid")
        return value

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            status = self.path.lstat()
            if self.path.is_symlink() or not self.path.is_file() or status.st_size > 65_536:
                raise CredentialStoreError("credential store is invalid")
            if os.name != "nt" and status.st_mode & 0o077:
                raise CredentialStoreError("credential store permissions are unsafe")
            payload: Any = json.loads(self.path.read_text(encoding="utf-8"))
            credentials = payload["credentials"]
            if payload.get("schemaVersion") != 1 or not isinstance(credentials, dict):
                raise CredentialStoreError("credential store is invalid")
            result: dict[str, str] = {}
            for key, value in credentials.items():
                reference = self._validate_reference(str(key))
                if not isinstance(value, str) or not value:
                    raise CredentialStoreError("credential store is invalid")
                result[reference] = self._unprotect(value)
            return result
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            if isinstance(error, CredentialStoreError):
                raise
            raise CredentialStoreError("credential store is invalid") from error

    def _write(self, credentials: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.path.parent.chmod(0o700)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                protected = {
                    reference: self._protect(value) for reference, value in credentials.items()
                }
                json.dump(
                    {"schemaVersion": 1, "credentials": protected},
                    stream,
                    ensure_ascii=False,
                    indent=2,
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            if os.name != "nt":
                self.path.chmod(0o600)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _protect(value: str) -> str:
        if os.name != "nt":
            return value
        encrypted = _windows_dpapi(value.encode("utf-8"), protect=True)
        return "dpapi:" + base64.b64encode(encrypted).decode("ascii")

    @staticmethod
    def _unprotect(value: str) -> str:
        if not value.startswith("dpapi:"):
            return value
        if os.name != "nt":
            raise CredentialStoreError("DPAPI credential cannot be read on this platform")
        try:
            encrypted = base64.b64decode(value.removeprefix("dpapi:"), validate=True)
            return _windows_dpapi(encrypted, protect=False).decode("utf-8")
        except (ValueError, UnicodeDecodeError, binascii.Error) as error:
            raise CredentialStoreError("credential store is invalid") from error

    def set(self, reference: str, secret: str) -> None:
        key = self._validate_reference(reference)
        value = secret.strip()
        if not value or len(value) > 16_384:
            raise CredentialStoreError("credential value is invalid")
        credentials = self._load()
        credentials[key] = value
        self._write(credentials)

    def delete(self, reference: str) -> None:
        key = self._validate_reference(reference)
        credentials = self._load()
        if key in credentials:
            del credentials[key]
            self._write(credentials)

    def get(self, reference: str) -> str | None:
        return self._load().get(self._validate_reference(reference))

    def resolve(self, reference: str, environment_name: str | None = None) -> str:
        value = self.get(reference)
        if value:
            return value
        if environment_name:
            environment_value = os.environ.get(environment_name, "").strip()
            if environment_value:
                return environment_value
        raise CredentialStoreError("credential is not configured")

    def status(self) -> dict[str, bool]:
        return {reference: True for reference in self._load()}


__all__ = ["CredentialStore", "CredentialStoreError"]


def _windows_dpapi(data: bytes, *, protect: bool) -> bytes:
    """Protect data for the current Windows user without prompting."""
    if os.name != "nt":
        raise CredentialStoreError("DPAPI is only available on Windows")
    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    source_buffer = ctypes.create_string_buffer(data)
    source = DataBlob(
        len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte))
    )
    destination = DataBlob()
    flags = 0x1  # CRYPTPROTECT_UI_FORBIDDEN
    crypt32 = ctypes.windll.crypt32
    if protect:
        succeeded = crypt32.CryptProtectData(
            ctypes.byref(source),
            "Media Bridge credential",
            None,
            None,
            None,
            flags,
            ctypes.byref(destination),
        )
    else:
        succeeded = crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            flags,
            ctypes.byref(destination),
        )
    if not succeeded:
        raise CredentialStoreError("Windows credential protection failed")
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(destination.pbData)
