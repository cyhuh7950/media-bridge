"""One-time client credential issuance and digest-only verification."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from media_bridge_control.db import Database
from media_bridge_control.models import ClientCredential
from media_bridge_control.security import SecurityContext

ALLOWED_SCOPES = frozenset({"assets:write", "mcp:invoke", "responses:invoke"})


class CredentialError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class IssuedCredential:
    credential: str
    selector: str
    name: str
    scopes: tuple[str, ...]
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class CredentialPrincipal:
    selector: str
    name: str
    scopes: frozenset[str]


class CredentialService:
    def __init__(
        self,
        *,
        database: Database,
        security: SecurityContext,
        now: Callable[[], datetime],
    ) -> None:
        self._database = database
        self._security = security
        self._now = now

    def issue(
        self,
        *,
        name: str,
        scopes: set[str],
        expires_at: datetime | None,
        created_by: str,
    ) -> IssuedCredential:
        if not name or len(name) > 128 or not scopes or not scopes <= ALLOWED_SCOPES:
            raise CredentialError("invalid_credential_request")
        if expires_at is not None and expires_at <= self._now():
            raise CredentialError("invalid_credential_request")
        issued = self._security.issue_token(prefix="mbc", purpose="client_credential")
        ordered_scopes = tuple(sorted(scopes))
        with self._database.session() as session:
            session.add(
                ClientCredential(
                    selector=issued.selector,
                    name=name,
                    credential_digest=issued.digest,
                    scopes=list(ordered_scopes),
                    expires_at=expires_at,
                    created_by=UUID(created_by),
                )
            )
        return IssuedCredential(
            credential=issued.raw,
            selector=issued.selector,
            name=name,
            scopes=ordered_scopes,
            expires_at=expires_at,
        )

    def verify(self, raw: str, *, required_scope: str) -> CredentialPrincipal:
        now = self._now()
        selector = self._security.selector(raw, prefix="mbc")
        if selector is None:
            raise CredentialError("credential_invalid")
        with self._database.session() as session:
            stored = session.scalar(
                select(ClientCredential)
                .where(ClientCredential.selector == selector)
                .with_for_update()
            )
            if (
                stored is None
                or stored.revoked_at is not None
                or (stored.expires_at is not None and stored.expires_at <= now)
                or not self._security.matches(
                    raw,
                    stored.credential_digest,
                    purpose="client_credential",
                )
                or required_scope not in stored.scopes
            ):
                raise CredentialError("credential_invalid")
            stored.last_used_at = now
            return CredentialPrincipal(
                selector=stored.selector,
                name=stored.name,
                scopes=frozenset(stored.scopes),
            )

    def revoke(self, selector: str) -> None:
        with self._database.session() as session:
            stored = session.scalar(
                select(ClientCredential)
                .where(ClientCredential.selector == selector)
                .with_for_update()
            )
            if stored is None:
                raise CredentialError("credential_not_found")
            stored.revoked_at = self._now()

    def list(self) -> list[dict[str, Any]]:
        with self._database.session() as session:
            rows = list(
                session.scalars(
                    select(ClientCredential).order_by(ClientCredential.created_at.desc())
                )
            )
            return [
                {
                    "selector": row.selector,
                    "name": row.name,
                    "scopes": row.scopes,
                    "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                    "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
                    "revoked": row.revoked_at is not None,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]
