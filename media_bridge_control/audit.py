"""Redacted Audit and operational Event persistence."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from media_bridge_control.db import Database
from media_bridge_control.models import AuditEvent, OperationalEvent
from media_bridge_control.redaction import redact_details


def _safe_code(value: str, *, maximum: int = 64) -> str:
    if len(value) > maximum or re.fullmatch(r"[a-z][a-z0-9_.-]*", value) is None:
        raise ValueError("event identifier is invalid")
    return value


class AuditEventWriter:
    def __init__(self, database: Database) -> None:
        self._database = database

    def write(
        self,
        *,
        actor_id: str | None,
        action: str,
        target_type: str,
        target_id: str | None,
        details: dict[str, object],
    ) -> None:
        safe_action = _safe_code(action)
        safe_target_type = _safe_code(target_type)
        if target_id is not None and len(target_id) > 128:
            raise ValueError("audit target identifier is oversized")
        with self._database.session() as session:
            session.add(
                AuditEvent(
                    id=uuid4(),
                    actor_id=UUID(actor_id) if actor_id is not None else None,
                    action=safe_action,
                    target_type=safe_target_type,
                    target_id=target_id,
                    details=redact_details(details),
                )
            )

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, 500))
        with self._database.session() as session:
            rows = list(
                session.scalars(
                    select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(bounded)
                )
            )
            return [
                {
                    "id": str(row.id),
                    "actor_id": str(row.actor_id) if row.actor_id is not None else None,
                    "action": row.action,
                    "target_type": row.target_type,
                    "target_id": row.target_id,
                    "details": row.details,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]


class OperationalEventWriter:
    def __init__(self, database: Database) -> None:
        self._database = database

    def write(
        self,
        *,
        request_id: str,
        event_type: str,
        model_id: str | None,
        policy_version: int | None,
        status_code: str,
        latency_bucket: str | None,
        size_bucket: str | None,
        created_at: datetime,
    ) -> None:
        if len(request_id) > 64 or not request_id:
            raise ValueError("event request identifier is invalid")
        with self._database.session() as session:
            session.add(
                OperationalEvent(
                    id=uuid4(),
                    request_id=request_id,
                    event_type=_safe_code(event_type),
                    model_id=model_id,
                    policy_version=policy_version,
                    status_code=_safe_code(status_code),
                    latency_bucket=_safe_code(latency_bucket) if latency_bucket else None,
                    size_bucket=_safe_code(size_bucket) if size_bucket else None,
                    created_at=created_at,
                )
            )

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, 500))
        with self._database.session() as session:
            rows = list(
                session.scalars(
                    select(OperationalEvent)
                    .order_by(OperationalEvent.created_at.desc())
                    .limit(bounded)
                )
            )
            return [
                {
                    "request_id": row.request_id,
                    "event_type": row.event_type,
                    "model_id": row.model_id,
                    "policy_version": row.policy_version,
                    "status_code": row.status_code,
                    "latency_bucket": row.latency_bucket,
                    "size_bucket": row.size_bucket,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]
