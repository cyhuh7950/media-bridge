"""Validated Provider, Model, Policy, and user read models."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from media_bridge_control.db import Database
from media_bridge_control.models import (
    ClientCredential,
    ConfigDraft,
    ModelCapability,
    Policy,
    Provider,
    User,
)
from media_bridge_control.schemas import (
    ModelCapabilityCreate,
    ModelCapabilityUpdate,
    PolicyCreate,
    PolicyUpdate,
    ProviderCreate,
    ProviderUpdate,
)


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

    def update_provider(self, provider_id: UUID, request: ProviderUpdate) -> dict[str, Any]:
        try:
            with self._database.session() as session:
                row = session.get(Provider, provider_id)
                if row is None:
                    raise ConfigurationError("configuration_not_found")
                candidate = ProviderCreate.model_validate(
                    {
                        "name": row.name,
                        "kind": row.kind,
                        "endpoint": row.endpoint,
                        "secret_ref": {
                            "kind": row.secret_ref_kind,
                            "identifier": row.secret_ref_identifier,
                        },
                        "enabled": row.enabled,
                        **request.model_dump(exclude_unset=True),
                    }
                )
                row.name = candidate.name
                row.kind = candidate.kind
                row.endpoint = candidate.endpoint
                row.secret_ref_kind = candidate.secret_ref.kind
                row.secret_ref_identifier = candidate.secret_ref.identifier
                row.enabled = candidate.enabled
                session.flush()
                return self._provider(row)
        except IntegrityError as error:
            raise ConfigurationError("configuration_conflict") from error
        except ValidationError as error:
            raise ConfigurationError("invalid_configuration") from error

    def delete_provider(self, provider_id: UUID) -> None:
        with self._database.session() as session:
            row = session.get(Provider, provider_id)
            if row is None:
                raise ConfigurationError("configuration_not_found")
            session.delete(row)

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

    def update_model(
        self,
        model_id: UUID,
        request: ModelCapabilityUpdate,
    ) -> dict[str, Any]:
        try:
            with self._database.session() as session:
                row = session.get(ModelCapability, model_id)
                if row is None:
                    raise ConfigurationError("configuration_not_found")
                candidate = ModelCapabilityCreate.model_validate(
                    {
                        "model_id": row.model_id,
                        "aliases": row.aliases,
                        "input_modalities": set(row.input_modalities),
                        "evidence": row.evidence,
                        "reviewed_at": row.reviewed_at,
                        "expires_at": row.expires_at,
                        "pdf_passthrough_verified": row.pdf_passthrough_verified,
                        **request.model_dump(exclude_unset=True),
                    }
                )
                row.model_id = candidate.model_id
                row.aliases = sorted(candidate.aliases)
                row.input_modalities = sorted(candidate.input_modalities)
                row.evidence = candidate.evidence
                row.reviewed_at = candidate.reviewed_at
                row.expires_at = candidate.expires_at
                row.pdf_passthrough_verified = candidate.pdf_passthrough_verified
                session.flush()
                return self._model(row)
        except IntegrityError as error:
            raise ConfigurationError("configuration_conflict") from error
        except ValidationError as error:
            raise ConfigurationError("invalid_configuration") from error

    def delete_model(self, model_id: UUID) -> None:
        with self._database.session() as session:
            row = session.get(ModelCapability, model_id)
            if row is None:
                raise ConfigurationError("configuration_not_found")
            session.delete(row)

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

    def update_policy(self, policy_id: UUID, request: PolicyUpdate) -> dict[str, Any]:
        try:
            with self._database.session() as session:
                row = session.get(Policy, policy_id)
                if row is None:
                    raise ConfigurationError("configuration_not_found")
                candidate = PolicyCreate.model_validate(
                    {
                        "name": row.name,
                        **row.body,
                        **request.model_dump(exclude_unset=True),
                    }
                )
                row.name = candidate.name
                row.body = candidate.model_dump(exclude={"name"})
                session.flush()
                return self._policy(row)
        except IntegrityError as error:
            raise ConfigurationError("configuration_conflict") from error
        except ValidationError as error:
            raise ConfigurationError("invalid_configuration") from error

    def delete_policy(self, policy_id: UUID) -> None:
        with self._database.session() as session:
            row = session.get(Policy, policy_id)
            if row is None:
                raise ConfigurationError("configuration_not_found")
            session.delete(row)

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
            "data_plane_auth": {"entries": self._data_plane_auth_entries()},
        }

    def _data_plane_auth_entries(self) -> list[dict[str, Any]]:
        with self._database.session() as session:
            rows = list(
                session.scalars(
                    select(ClientCredential).order_by(ClientCredential.selector)
                )
            )
            return [
                {
                    "selector": row.selector,
                    "digest": row.credential_digest,
                    "scopes": sorted(row.scopes),
                    "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                    "revoked": row.revoked_at is not None,
                }
                for row in rows
            ]

    def create_validated_draft(self, *, created_by: str) -> dict[str, Any]:
        body = self.snapshot_body()
        with self._database.session() as session:
            current_revision = session.scalar(
                select(func.coalesce(func.max(ConfigDraft.revision), 0))
            )
            draft = ConfigDraft(
                revision=int(current_revision or 0) + 1,
                body=body,
                created_by=UUID(created_by),
            )
            session.add(draft)
            session.flush()
            return {
                "draft_id": str(draft.id),
                "revision": draft.revision,
                "status": "validated",
            }

    def get_draft_body(self, draft_id: UUID) -> dict[str, Any]:
        with self._database.session() as session:
            draft = session.get(ConfigDraft, draft_id)
            if draft is None:
                raise ConfigurationError("draft_not_found")
            return dict(draft.body)
