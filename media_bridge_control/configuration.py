"""Validated Provider, Model, Policy, and user read models."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from media_bridge_control.db import Database
from media_bridge_control.models import ModelCapability, Policy, Provider, User
from media_bridge_control.schemas import ModelCapabilityCreate, PolicyCreate, ProviderCreate


class ConfigurationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ConfigurationService:
    def __init__(self, database: Database) -> None:
        self._database = database

    def list_users(self) -> list[dict[str, Any]]:
        with self._database.session() as session:
            rows = list(session.scalars(select(User).order_by(User.username)))
            return [
                {
                    "id": str(row.id),
                    "username": row.username,
                    "role": row.role,
                    "is_active": row.is_active,
                }
                for row in rows
            ]

    def create_provider(self, request: ProviderCreate) -> dict[str, Any]:
        try:
            with self._database.session() as session:
                row = Provider(
                    name=request.name,
                    kind=request.kind,
                    endpoint=request.endpoint,
                    secret_ref_kind=request.secret_ref.kind,
                    secret_ref_identifier=request.secret_ref.identifier,
                    enabled=request.enabled,
                )
                session.add(row)
                session.flush()
                return self._provider(row)
        except IntegrityError as error:
            raise ConfigurationError("configuration_conflict") from error

    def list_providers(self) -> list[dict[str, Any]]:
        with self._database.session() as session:
            rows = list(session.scalars(select(Provider).order_by(Provider.name)))
            return [self._provider(row) for row in rows]

    @staticmethod
    def _provider(row: Provider) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "name": row.name,
            "kind": row.kind,
            "endpoint": row.endpoint,
            "secret_ref": {
                "kind": row.secret_ref_kind,
                "identifier": row.secret_ref_identifier,
            },
            "enabled": row.enabled,
        }

    def create_model(self, request: ModelCapabilityCreate) -> dict[str, Any]:
        try:
            with self._database.session() as session:
                row = ModelCapability(
                    model_id=request.model_id,
                    aliases=sorted(request.aliases),
                    input_modalities=sorted(request.input_modalities),
                    evidence=request.evidence,
                    reviewed_at=request.reviewed_at,
                    expires_at=request.expires_at,
                    pdf_passthrough_verified=request.pdf_passthrough_verified,
                )
                session.add(row)
                session.flush()
                return self._model(row)
        except IntegrityError as error:
            raise ConfigurationError("configuration_conflict") from error

    def list_models(self) -> list[dict[str, Any]]:
        with self._database.session() as session:
            rows = list(session.scalars(select(ModelCapability).order_by(ModelCapability.model_id)))
            return [self._model(row) for row in rows]

    @staticmethod
    def _model(row: ModelCapability) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "model_id": row.model_id,
            "aliases": row.aliases,
            "input_modalities": row.input_modalities,
            "evidence": row.evidence,
            "reviewed_at": row.reviewed_at.isoformat(),
            "expires_at": row.expires_at.isoformat(),
            "pdf_passthrough_verified": row.pdf_passthrough_verified,
        }

    def create_policy(self, request: PolicyCreate) -> dict[str, Any]:
        body = request.model_dump(exclude={"name"})
        try:
            with self._database.session() as session:
                row = Policy(name=request.name, body=body)
                session.add(row)
                session.flush()
                return self._policy(row)
        except IntegrityError as error:
            raise ConfigurationError("configuration_conflict") from error

    def list_policies(self) -> list[dict[str, Any]]:
        with self._database.session() as session:
            rows = list(session.scalars(select(Policy).order_by(Policy.name)))
            return [self._policy(row) for row in rows]

    @staticmethod
    def _policy(row: Policy) -> dict[str, Any]:
        return {"id": str(row.id), "name": row.name, **row.body}

    def snapshot_body(self) -> dict[str, Any]:
        providers = self.list_providers()
        models = self.list_models()
        policies = self.list_policies()
        if not models or len(policies) != 1:
            raise ConfigurationError("configuration_incomplete")
        return {
            "registry": {
                "version": f"registry-{len(models)}",
                "models": [
                    {
                        "id": item["model_id"],
                        "input_modalities": item["input_modalities"],
                        "expires_at": item["expires_at"],
                        "pdf_passthrough_verified": item["pdf_passthrough_verified"],
                    }
                    for item in models
                ],
            },
            "providers": providers,
            "policy": policies[0],
        }
