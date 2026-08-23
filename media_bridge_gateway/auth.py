"""Signed-snapshot, digest-only authentication for Data Plane routes."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from pydantic import Field, StringConstraints, ValidationError, field_validator

from media_bridge.config_snapshot import SignedSnapshot, SnapshotVerificationError
from media_bridge.contracts import StrictModel
from media_bridge_gateway.contracts import DataPlaneSubject

_ALLOWED_SCOPES = frozenset({"assets:write", "mcp:invoke", "responses:invoke"})
_SELECTOR = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


class CredentialAuthenticationError(RuntimeError):
    def __init__(self, code: str = "credential_invalid") -> None:
        super().__init__("Data-plane credential was rejected.")
        self.code = code


class SnapshotCredentialEntry(StrictModel):
    selector: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,32}$")]
    digest: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    scopes: Annotated[set[str], Field(min_length=1, max_length=3)]
    expires_at: datetime | None = None
    revoked: bool = False

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: set[str]) -> set[str]:
        if not value <= _ALLOWED_SCOPES:
            raise ValueError("data-plane credential scope is invalid")
        return value

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("credential expiry must be timezone-aware")
        return value


class SnapshotAuthDocument(StrictModel):
    entries: Annotated[list[SnapshotCredentialEntry], Field(max_length=10_000)]


class SnapshotCredentialVerifier:
    """Authenticate P1-issued opaque credentials from one signed generation."""

    def __init__(
        self,
        *,
        snapshot: SignedSnapshot,
        pepper: bytes,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if len(pepper) < 32:
            raise ValueError("data-plane credential pepper is too short")
        raw_document = snapshot.body.get("data_plane_auth")
        if raw_document is None:
            document = SnapshotAuthDocument(entries=[])
        else:
            try:
                document = SnapshotAuthDocument.model_validate(raw_document)
            except ValidationError as error:
                raise SnapshotVerificationError(
                    "snapshot data-plane authentication is invalid"
                ) from error
        selectors = [entry.selector for entry in document.entries]
        if len(selectors) != len(set(selectors)):
            raise SnapshotVerificationError(
                "snapshot data-plane authentication has duplicate selectors"
            )
        self._entries = {entry.selector: entry for entry in document.entries}
        self._pepper = pepper
        self._now = now

    def authenticate(
        self,
        *,
        authorization: str | None,
        required_scope: str,
        cookie_header: str | None,
    ) -> DataPlaneSubject:
        if cookie_header is not None and cookie_header.strip():
            raise CredentialAuthenticationError("admin_session_not_allowed")
        if required_scope not in _ALLOWED_SCOPES:
            raise CredentialAuthenticationError()
        raw = self._bearer(authorization)
        selector = self._selector(raw)
        entry = self._entries.get(selector) if selector is not None else None
        now = self._now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise CredentialAuthenticationError()
        if (
            entry is None
            or entry.revoked
            or (entry.expires_at is not None and entry.expires_at <= now)
            or required_scope not in entry.scopes
            or not hmac.compare_digest(self._digest(raw), entry.digest)
        ):
            raise CredentialAuthenticationError()
        return DataPlaneSubject(
            credential_selector=entry.selector,
            tenant_id=f"client-{entry.selector}",
            scopes=frozenset(entry.scopes),
        )

    def _digest(self, raw: str) -> str:
        payload = f"client_credential\0{raw}".encode()
        return hmac.new(self._pepper, payload, hashlib.sha256).hexdigest()

    @staticmethod
    def _bearer(authorization: str | None) -> str:
        if authorization is None or not authorization.startswith("Bearer "):
            raise CredentialAuthenticationError()
        raw = authorization.removeprefix("Bearer ")
        if not raw or raw.strip() != raw or " " in raw or len(raw) > 160:
            raise CredentialAuthenticationError()
        return raw

    @staticmethod
    def _selector(raw: str) -> str | None:
        if not raw.startswith("mbc_") or "." not in raw:
            return None
        selector, secret = raw.removeprefix("mbc_").split(".", 1)
        if not _SELECTOR.fullmatch(selector) or not secret or len(secret) > 64:
            return None
        return selector
