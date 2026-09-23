"""Validated Provider, Model, Policy, and user read models."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from media_bridge.reasoning import reasoning_capability
from media_bridge_control.db import Database
from media_bridge_control.models import (
    ClientCredential,
    ConfigDraft,
    ModelCapability,
    Policy,
    Provider,
    RoutingProfile,
    User,
)
from media_bridge_control.provider_catalog import ProviderCatalogError, get_provider_catalog_entry
from media_bridge_control.schemas import (
    ModelCapabilityCreate,
    ModelCapabilityUpdate,
    PolicyCreate,
    PolicyUpdate,
    ProviderCreate,
    ProviderUpdate,
    RoutingProfileCreate,
    RoutingProfileUpdate,
)
from media_bridge_control.security import SecurityContext


class ConfigurationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _provider_alias(value: str) -> str:
    alias = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (alias or "provider")[:64]


class ConfigurationService:
    def __init__(self, database: Database, security: SecurityContext) -> None:
        self._database = database
        self._security = security

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

    def create_provider(
        self,
        request: ProviderCreate,
        *,
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        try:
            values = self._provider_values(request)
            if request.api_key is not None:
                values["encrypted_api_key"] = self._security.encrypt_secret(request.api_key)
            with self._database.session() as session:
                row = Provider(
                    **values,
                    updated_by=updated_by,
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

    def update_provider(
        self,
        provider_id: UUID,
        request: ProviderUpdate,
        *,
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        try:
            with self._database.session() as session:
                row = session.get(Provider, provider_id)
                if row is None:
                    raise ConfigurationError("configuration_not_found")
                candidate = ProviderCreate.model_validate(
                    {
                        "name": row.name,
                        "alias": row.alias,
                        "kind": row.kind,
                        "catalog_id": row.catalog_id,
                        "model_id": row.model_id,
                        "endpoint": row.endpoint,
                        "protocol": row.protocol,
                        "capabilities": set(row.capabilities or []),
                        "reasoning_effort": row.reasoning_effort or "provider_default",
                        "secret_ref": {
                            "kind": row.secret_ref_kind,
                            "identifier": row.secret_ref_identifier,
                        },
                        "api_key": None,
                        "enabled": row.enabled,
                        **request.model_dump(exclude_unset=True),
                    }
                )
                for field, value in self._provider_values(candidate).items():
                    setattr(row, field, value)
                if request.api_key is not None:
                    row.encrypted_api_key = self._security.encrypt_secret(request.api_key)
                row.updated_by = updated_by
                session.flush()
                return self._provider(row)
        except IntegrityError as error:
            raise ConfigurationError("configuration_conflict") from error
        except ValidationError as error:
            raise ConfigurationError("invalid_configuration") from error

    @staticmethod
    def _provider_values(request: ProviderCreate) -> dict[str, Any]:
        protocol = request.protocol
        capabilities = request.capabilities
        effective_model_id = request.model_id
        if request.catalog_id is not None:
            try:
                entry = get_provider_catalog_entry(request.catalog_id)
            except ProviderCatalogError as error:
                raise ConfigurationError("provider_catalog_entry_unknown") from error
            expected_kind = "llm" if entry.kind == "llm" else "analysis"
            if request.kind not in {expected_kind, entry.kind}:
                raise ConfigurationError("provider_catalog_kind_mismatch")
            protocol = protocol or entry.protocol
            capabilities = capabilities or set(entry.capabilities)
            effective_model_id = effective_model_id or entry.default_model_id
        effort = request.reasoning_effort or "provider_default"
        if effort != "provider_default":
            capability = reasoning_capability(request.catalog_id, protocol, effective_model_id)
            if request.kind != "llm" or capability is None or effort not in capability.efforts:
                raise ConfigurationError("reasoning_effort_unsupported")
        return {
            "name": request.name,
            "alias": request.alias or _provider_alias(request.catalog_id or request.name),
            "kind": request.kind,
            "catalog_id": request.catalog_id,
            "model_id": request.model_id,
            "endpoint": request.endpoint,
            "protocol": protocol,
            "capabilities": sorted(capabilities),
            "reasoning_effort": None if effort == "provider_default" else effort,
            "secret_ref_kind": "db" if request.api_key is not None else request.secret_ref.kind,
            "secret_ref_identifier": (
                "provider_api_key"
                if request.api_key is not None
                else request.secret_ref.identifier
            ),
            "enabled": request.enabled,
        }

    def delete_provider(self, provider_id: UUID) -> None:
        with self._database.session() as session:
            row = session.get(Provider, provider_id)
            if row is None:
                raise ConfigurationError("configuration_not_found")
            session.delete(row)

    @staticmethod
    def _provider(row: Provider) -> dict[str, Any]:
        model_id = row.model_id
        if model_id is None and row.catalog_id is not None:
            try:
                model_id = get_provider_catalog_entry(row.catalog_id).default_model_id
            except ProviderCatalogError:
                model_id = None
        return {
            "id": str(row.id),
            "name": row.name,
            "alias": row.alias or _provider_alias(row.catalog_id or row.name),
            "kind": row.kind,
            "catalog_id": row.catalog_id,
            "model_id": model_id,
            "endpoint": row.endpoint,
            "protocol": row.protocol,
            "capabilities": sorted(row.capabilities or []),
            "secret_ref": {
                "kind": row.secret_ref_kind,
                "identifier": row.secret_ref_identifier,
            },
            "has_api_key": row.encrypted_api_key is not None,
            "reasoning_effort": row.reasoning_effort or "provider_default",
            "enabled": row.enabled,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "updated_by": row.updated_by,
        }

    def create_routing_profile(
        self,
        request: RoutingProfileCreate,
        *,
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        try:
            with self._database.session() as session:
                analysis_ids, llm_ids = self._routing_provider_ids(session, request)
                row = RoutingProfile(
                    name=request.name,
                    analysis_provider_ids=analysis_ids,
                    llm_provider_ids=llm_ids,
                    strategy=request.strategy,
                    enabled=request.enabled,
                    updated_by=updated_by,
                )
                session.add(row)
                session.flush()
                return self._routing_profile(row)
        except IntegrityError as error:
            raise ConfigurationError("configuration_conflict") from error

    def list_routing_profiles(self) -> list[dict[str, Any]]:
        with self._database.session() as session:
            rows = list(session.scalars(select(RoutingProfile).order_by(RoutingProfile.name)))
            return [self._routing_profile(row) for row in rows]

    def update_routing_profile(
        self,
        profile_id: UUID,
        request: RoutingProfileUpdate,
        *,
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        try:
            with self._database.session() as session:
                row = session.get(RoutingProfile, profile_id)
                if row is None:
                    raise ConfigurationError("configuration_not_found")
                values: dict[str, Any] = {
                    "name": row.name,
                    "analysis_provider_ids": [UUID(value) for value in row.analysis_provider_ids],
                    "llm_provider_ids": [UUID(value) for value in row.llm_provider_ids],
                    "strategy": row.strategy,
                    "enabled": row.enabled,
                    **request.model_dump(exclude_unset=True),
                }
                candidate = RoutingProfileCreate.model_validate(values)
                analysis_ids, llm_ids = self._routing_provider_ids(session, candidate)
                row.name = candidate.name
                row.analysis_provider_ids = analysis_ids
                row.llm_provider_ids = llm_ids
                row.strategy = candidate.strategy
                row.enabled = candidate.enabled
                row.updated_by = updated_by
                session.flush()
                return self._routing_profile(row)
        except IntegrityError as error:
            raise ConfigurationError("configuration_conflict") from error
        except (ValidationError, ValueError) as error:
            raise ConfigurationError("invalid_configuration") from error

    def delete_routing_profile(self, profile_id: UUID) -> None:
        with self._database.session() as session:
            row = session.get(RoutingProfile, profile_id)
            if row is None:
                raise ConfigurationError("configuration_not_found")
            session.delete(row)

    @staticmethod
    def _routing_provider_ids(
        session: Session,
        request: RoutingProfileCreate,
    ) -> tuple[list[str], list[str]]:
        provider_ids = set(request.analysis_provider_ids + request.llm_provider_ids)
        rows = list(session.scalars(select(Provider).where(Provider.id.in_(provider_ids))))
        by_id = {row.id: row for row in rows}
        if len(by_id) != len(provider_ids):
            raise ConfigurationError("routing_profile_provider_not_found")
        if any(
            by_id[item].kind not in {"analysis", "vision", "ocr"}
            for item in request.analysis_provider_ids
        ):
            raise ConfigurationError("routing_profile_analysis_provider_invalid")
        if any(by_id[item].kind != "llm" for item in request.llm_provider_ids):
            raise ConfigurationError("routing_profile_llm_provider_invalid")
        return (
            [str(item) for item in request.analysis_provider_ids],
            [str(item) for item in request.llm_provider_ids],
        )

    @staticmethod
    def _routing_profile(row: RoutingProfile) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "name": row.name,
            "analysis_provider_ids": list(row.analysis_provider_ids or []),
            "llm_provider_ids": list(row.llm_provider_ids or []),
            "strategy": row.strategy,
            "enabled": row.enabled,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "updated_by": row.updated_by,
        }

    def create_model(
        self,
        request: ModelCapabilityCreate,
        *,
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        try:
            with self._database.session() as session:
                profile = (
                    session.get(RoutingProfile, request.routing_profile_id)
                    if request.routing_profile_id
                    else None
                )
                if request.routing_profile_id and profile is None:
                    raise ConfigurationError("model_routing_profile_not_found")
                provider = (
                    session.get(Provider, request.provider_id)
                    if request.provider_id
                    else None
                )
                if provider is not None and provider.kind != "llm":
                    raise ConfigurationError("model_provider_invalid")
                if provider is None and profile is None:
                    raise ConfigurationError("model_provider_or_routing_required")
                if profile is not None:
                    llm_ids = [UUID(value) for value in profile.llm_provider_ids]
                    if provider is not None and provider.id not in llm_ids:
                        raise ConfigurationError("model_provider_not_in_routing_profile")
                    if provider is None and llm_ids:
                        provider = session.get(Provider, llm_ids[0])
                    if provider is None or provider.kind != "llm":
                        raise ConfigurationError("model_routing_provider_invalid")
                assert provider is not None
                public_model_id = request.model_id
                if "/" not in public_model_id:
                    public_model_id = (
                        f"{provider.alias or _provider_alias(provider.name)}/{public_model_id}"
                    )
                row = ModelCapability(
                    provider_id=provider.id,
                    routing_profile_id=profile.id if profile else None,
                    model_id=public_model_id,
                    aliases=sorted(request.aliases),
                    input_modalities=sorted(request.input_modalities),
                    evidence=request.evidence,
                    reviewed_at=request.reviewed_at,
                    expires_at=request.expires_at,
                    pdf_passthrough_verified=request.pdf_passthrough_verified,
                    reasoning_effort=(
                        None
                        if request.reasoning_effort == "provider_default"
                        else request.reasoning_effort
                    ),
                    updated_by=updated_by,
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
        *,
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        try:
            with self._database.session() as session:
                row = session.get(ModelCapability, model_id)
                if row is None:
                    raise ConfigurationError("configuration_not_found")
                candidate = ModelCapabilityCreate.model_validate(
                    {
                        "provider_id": row.provider_id,
                        "routing_profile_id": row.routing_profile_id,
                        "model_id": row.model_id,
                        "aliases": row.aliases,
                        "input_modalities": set(row.input_modalities),
                        "evidence": row.evidence,
                        "reviewed_at": row.reviewed_at,
                        "expires_at": row.expires_at,
                        "pdf_passthrough_verified": row.pdf_passthrough_verified,
                        "reasoning_effort": row.reasoning_effort or "provider_default",
                        **request.model_dump(exclude_unset=True),
                    }
                )
                row.model_id = candidate.model_id
                row.routing_profile_id = candidate.routing_profile_id
                if candidate.provider_id is not None:
                    provider = session.get(Provider, candidate.provider_id)
                    if provider is None:
                        raise ConfigurationError("model_provider_not_found")
                    if provider.kind != "llm":
                        raise ConfigurationError("model_provider_invalid")
                    row.provider_id = candidate.provider_id
                row.aliases = sorted(candidate.aliases)
                row.input_modalities = sorted(candidate.input_modalities)
                row.evidence = candidate.evidence
                row.reviewed_at = candidate.reviewed_at
                row.expires_at = None
                row.pdf_passthrough_verified = candidate.pdf_passthrough_verified
                row.reasoning_effort = (
                    None
                    if candidate.reasoning_effort == "provider_default"
                    else candidate.reasoning_effort
                )
                row.updated_by = updated_by
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
            "provider_id": str(row.provider_id) if row.provider_id is not None else None,
            "routing_profile_id": (
                str(row.routing_profile_id) if row.routing_profile_id is not None else None
            ),
            "model_id": row.model_id,
            "aliases": row.aliases,
            "input_modalities": row.input_modalities,
            "evidence": row.evidence,
            "reviewed_at": row.reviewed_at.isoformat(),
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "pdf_passthrough_verified": row.pdf_passthrough_verified,
            "reasoning_effort": row.reasoning_effort or "provider_default",
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "updated_by": row.updated_by,
        }

    def create_policy(
        self,
        request: PolicyCreate,
        *,
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        body = request.model_dump(exclude={"name"})
        try:
            with self._database.session() as session:
                row = Policy(name=request.name, body=body, updated_by=updated_by)
                session.add(row)
                session.flush()
                return self._policy(row)
        except IntegrityError as error:
            raise ConfigurationError("configuration_conflict") from error

    def list_policies(self) -> list[dict[str, Any]]:
        with self._database.session() as session:
            rows = list(session.scalars(select(Policy).order_by(Policy.name)))
            return [self._policy(row) for row in rows]

    def update_policy(
        self,
        policy_id: UUID,
        request: PolicyUpdate,
        *,
        updated_by: str | None = None,
    ) -> dict[str, Any]:
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
                row.updated_by = updated_by
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
        return {
            "id": str(row.id),
            "name": row.name,
            **row.body,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "updated_by": row.updated_by,
        }

    def snapshot_body(self) -> dict[str, Any]:
        with self._database.session() as session:
            self._set_repeatable_read(session)
            return self._snapshot_body(session)

    def _snapshot_body(self, session: Session) -> dict[str, Any]:
        providers = [
            self._provider(row)
            for row in session.scalars(select(Provider).order_by(Provider.name))
        ]
        for provider in providers:
            if provider["reasoning_effort"] == "provider_default":
                provider["reasoning_effort"] = None
        models = [
            self._model(row)
            for row in session.scalars(
                select(ModelCapability).order_by(ModelCapability.model_id)
            )
        ]
        # Registering a Provider does not publish an external model. A public
        # model is created separately and is the only source for the snapshot.
        policies = [
            self._policy(row)
            for row in session.scalars(select(Policy).order_by(Policy.name))
        ]
        if not models or len(policies) != 1:
            raise ConfigurationError("configuration_incomplete")
        return {
            "registry": {
                "version": f"registry-{len(models)}",
                "models": [
                    {
                        "id": item["model_id"],
                        "provider_id": item.get("provider_id"),
                        "aliases": item.get("aliases", []),
                        "input_modalities": item["input_modalities"],
                        "expires_at": item["expires_at"],
                        "pdf_passthrough_verified": item["pdf_passthrough_verified"],
                        "routing_profile_id": item.get("routing_profile_id"),
                        "reasoning_effort": item.get("reasoning_effort"),
                    }
                    for item in models
                ],
            },
            "providers": providers,
            "routing_profiles": [
                self._routing_profile(row)
                for row in session.scalars(select(RoutingProfile).order_by(RoutingProfile.name))
                if row.enabled
            ],
            "defaults": {
                "reasoning_effort": policies[0].get("reasoning_effort", "provider_default")
            },
            "policy": policies[0],
            "data_plane_auth": {"entries": self._data_plane_auth_entries(session)},
        }

    @staticmethod
    def _data_plane_auth_entries(session: Session) -> list[dict[str, Any]]:
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

    @staticmethod
    def _set_repeatable_read(session: Session) -> None:
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})

    def create_validated_draft(self, *, created_by: str) -> dict[str, Any]:
        with self._database.session() as session:
            self._set_repeatable_read(session)
            body = self._snapshot_body(session)
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
