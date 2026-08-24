"""Non-sensitive Gateway connection persistence and state transitions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from media_bridge_control.db import Database
from media_bridge_control.models import Connection
from media_bridge_control.schemas import (
    ConnectionCreate,
    ConnectionUpdate,
    SecretReference,
)

_SAFE_ERROR = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ConnectionServiceError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class RuntimeConnection:
    id: str
    gateway_url: str
    secret_ref_kind: Literal["env", "docker_secret", "external"]
    secret_ref_identifier: str = field(repr=False)
    enabled: bool = True
    revoked: bool = False


class ConnectionService:
    def __init__(self, database: Database) -> None:
        self._database = database

    def create(self, request: ConnectionCreate, *, created_by: str) -> dict[str, Any]:
        try:
            creator_id = UUID(created_by)
        except ValueError as error:
            raise ConnectionServiceError("invalid_actor") from error
        try:
            with self._database.session() as session:
                row = Connection(
                    name=request.name,
                    gateway_url=request.gateway_url,
                    credential_secret_ref_kind=request.credential_secret_ref.kind,
                    credential_secret_ref_identifier=(
                        request.credential_secret_ref.identifier
                    ),
                    enabled=request.enabled,
                    status="untested",
                    created_by=creator_id,
                )
                session.add(row)
                session.flush()
                return self._public(row)
        except IntegrityError as error:
            raise ConnectionServiceError("connection_conflict") from error

    def list(self) -> list[dict[str, Any]]:
        with self._database.session() as session:
            rows = list(session.scalars(select(Connection).order_by(Connection.name)))
            return [self._public(row) for row in rows]

    def update(self, connection_id: str, request: ConnectionUpdate) -> dict[str, Any]:
        try:
            item_id = UUID(connection_id)
        except ValueError as error:
            raise ConnectionServiceError("connection_not_found") from error
        try:
            with self._database.session() as session:
                row = session.get(Connection, item_id)
                if row is None or row.revoked_at is not None:
                    raise ConnectionServiceError("connection_not_found")
                candidate = ConnectionCreate.model_validate(
                    {
                        "name": row.name,
                        "gateway_url": row.gateway_url,
                        "credential_secret_ref": {
                            "kind": row.credential_secret_ref_kind,
                            "identifier": row.credential_secret_ref_identifier,
                        },
                        "enabled": row.enabled,
                        **request.model_dump(exclude_unset=True),
                    }
                )
                row.name = candidate.name
                row.gateway_url = candidate.gateway_url
                row.credential_secret_ref_kind = candidate.credential_secret_ref.kind
                row.credential_secret_ref_identifier = (
                    candidate.credential_secret_ref.identifier
                )
                row.enabled = candidate.enabled
                row.status = "untested"
                row.last_error_code = None
                session.flush()
                return self._public(row)
        except IntegrityError as error:
            raise ConnectionServiceError("connection_conflict") from error
        except ValidationError as error:
            raise ConnectionServiceError("invalid_connection") from error

    def revoke(self, connection_id: str, *, revoked_at: datetime) -> dict[str, Any]:
        self._require_aware(revoked_at)
        with self._database.session() as session:
            row = self._get(session, connection_id)
            row.enabled = False
            row.status = "revoked"
            row.revoked_at = revoked_at
            row.last_error_code = None
            session.flush()
            return self._public(row)

    def record_test_result(
        self,
        connection_id: str,
        *,
        succeeded: bool,
        error_code: str | None,
        tested_at: datetime,
    ) -> dict[str, Any]:
        self._require_aware(tested_at)
        if succeeded and error_code is not None:
            raise ConnectionServiceError("invalid_test_result")
        if not succeeded and (
            error_code is None or _SAFE_ERROR.fullmatch(error_code) is None
        ):
            raise ConnectionServiceError("invalid_test_result")
        with self._database.session() as session:
            row = self._get(session, connection_id)
            if row.revoked_at is not None:
                raise ConnectionServiceError("connection_revoked")
            if succeeded:
                row.status = "ready"
                if row.last_success_at is None or tested_at > row.last_success_at:
                    row.last_success_at = tested_at
                row.last_error_code = None
            else:
                row.status = "failed"
                row.last_error_code = error_code
            session.flush()
            return self._public(row)

    def runtime(self, connection_id: str) -> RuntimeConnection:
        with self._database.session() as session:
            row = self._get(session, connection_id)
            return RuntimeConnection(
                id=str(row.id),
                gateway_url=row.gateway_url,
                secret_ref_kind=cast(
                    Literal["env", "docker_secret", "external"],
                    row.credential_secret_ref_kind,
                ),
                secret_ref_identifier=row.credential_secret_ref_identifier,
                enabled=row.enabled,
                revoked=row.revoked_at is not None,
            )

    @staticmethod
    def _get(session: Session, connection_id: str) -> Connection:
        try:
            item_id = UUID(connection_id)
        except ValueError as error:
            raise ConnectionServiceError("connection_not_found") from error
        row = session.get(Connection, item_id)
        if row is None:
            raise ConnectionServiceError("connection_not_found")
        return row

    @staticmethod
    def _require_aware(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ConnectionServiceError("invalid_timestamp")

    @classmethod
    def _public(cls, row: Connection) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "name": row.name,
            "gateway_url": row.gateway_url,
            "credential_secret_ref": {
                "kind": row.credential_secret_ref_kind,
                "identifier": cls._mask(row.credential_secret_ref_identifier),
            },
            "enabled": row.enabled,
            "status": row.status,
            "last_success_at": (
                row.last_success_at.isoformat() if row.last_success_at else None
            ),
            "last_error_code": row.last_error_code,
            "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        }

    @staticmethod
    def _mask(identifier: str) -> str:
        if len(identifier) < 7:
            return "***"
        return f"{identifier[:3]}***{identifier[-3:]}"

    @staticmethod
    def secret_reference(connection: RuntimeConnection) -> SecretReference:
        return SecretReference(
            kind=connection.secret_ref_kind,
            identifier=connection.secret_ref_identifier,
        )
