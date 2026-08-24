"""Bounded external Secret reference resolution for Gateway connections."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from media_bridge_control.schemas import SecretReference


class SecretResolutionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class GatewaySecretResolver:
    def __init__(
        self,
        *,
        docker_secret_root: Path = Path("/run/secrets"),
        external_resolver: Callable[[str], str] | None = None,
        max_bytes: int = 4_096,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("Secret byte limit must be positive")
        self._docker_secret_root = docker_secret_root
        self._external_resolver = external_resolver
        self._max_bytes = max_bytes

    def resolve(self, reference: SecretReference) -> str:
        if reference.kind == "env":
            value = os.environ.get(reference.identifier)
            return self._validated(value)
        if reference.kind == "docker_secret":
            return self._from_file(reference.identifier)
        if self._external_resolver is None:
            raise SecretResolutionError("secret_resolver_unavailable")
        try:
            value = self._external_resolver(reference.identifier)
        except Exception as error:
            raise SecretResolutionError("secret_unavailable") from error
        return self._validated(value)

    def _from_file(self, identifier: str) -> str:
        path = self._docker_secret_root / identifier
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > self._max_bytes:
                raise SecretResolutionError("secret_unavailable")
            raw = path.read_bytes()
        except OSError as error:
            raise SecretResolutionError("secret_unavailable") from error
        try:
            value = raw.decode().strip()
        except UnicodeDecodeError as error:
            raise SecretResolutionError("secret_unavailable") from error
        return self._validated(value)

    def _validated(self, value: str | None) -> str:
        if value is None or not value or len(value.encode()) > self._max_bytes:
            raise SecretResolutionError("secret_unavailable")
        if value.strip() != value or "\x00" in value:
            raise SecretResolutionError("secret_unavailable")
        return value
