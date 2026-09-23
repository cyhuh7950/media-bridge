"""Strict Admin API request contracts."""

import re
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from media_bridge.contracts import StrictModel
from media_bridge.reasoning import ReasoningEffort


class AdminStrictModel(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Username = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$"),
]
Password = Annotated[str, StringConstraints(min_length=12, max_length=1_024)]


class BootstrapRequest(AdminStrictModel):
    username: Username
    password: Password


class LoginRequest(AdminStrictModel):
    username: Username
    password: Annotated[str, StringConstraints(min_length=1, max_length=1_024)]


class TotpCodeRequest(AdminStrictModel):
    username: Username
    password: Annotated[str, StringConstraints(min_length=1, max_length=1_024)]
    code: Annotated[str, StringConstraints(min_length=6, max_length=6)]


class TotpEnrollmentRequest(AdminStrictModel):
    username: Username
    password: Annotated[str, StringConstraints(min_length=1, max_length=1_024)]


class TotpConfirmRequest(AdminStrictModel):
    user_id: UUID
    code: Annotated[str, StringConstraints(min_length=6, max_length=6)]


class RecoveryRequest(AdminStrictModel):
    username: Username
    recovery_code: Annotated[str, StringConstraints(min_length=16, max_length=128)]
    new_password: Password


class RecoveryCodeRequest(AdminStrictModel):
    username: Username


class RecoveryLoginRequest(AdminStrictModel):
    username: Username
    password: Annotated[str, StringConstraints(min_length=1, max_length=1_024)]
    recovery_code: Annotated[str, StringConstraints(min_length=16, max_length=128)]


class UserCreate(AdminStrictModel):
    username: Username
    password: Password
    role: Literal["admin", "operator", "viewer"]


class NonEmptyUpdate(AdminStrictModel):
    @model_validator(mode="after")
    def require_non_null_change(self) -> "NonEmptyUpdate":
        if not self.model_fields_set or any(
            getattr(self, field_name) is None for field_name in self.model_fields_set
        ):
            raise ValueError("update must contain non-null fields")
        return self


class UserUpdate(NonEmptyUpdate):
    password: Password | None = None
    role: Literal["admin", "operator", "viewer"] | None = None
    is_active: bool | None = None


class SecretReference(AdminStrictModel):
    kind: Literal["env", "docker_secret", "external", "db"]
    identifier: Annotated[str, StringConstraints(min_length=1, max_length=255)]

    @model_validator(mode="after")
    def validate_identifier(self) -> "SecretReference":
        identifier = self.identifier
        if self.kind == "env" and re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", identifier):
            return self
        if self.kind == "docker_secret" and re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", identifier
        ):
            return self
        if self.kind == "db" and identifier == "provider_api_key":
            return self
        allowed_prefixes = ("vault://", "aws-sm://", "gcp-sm://", "azure-kv://")
        if (
            self.kind == "external"
            and identifier.startswith(allowed_prefixes)
            and ".." not in identifier
            and "?" not in identifier
            and "#" not in identifier
            and re.fullmatch(r"[a-z][a-z0-9-]*://[A-Za-z0-9][A-Za-z0-9._/@:-]*", identifier)
        ):
            return self
        raise ValueError("secret reference identifier is invalid")


class ProviderCreate(AdminStrictModel):
    name: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]
    alias: Annotated[
        str,
        StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,63}$"),
    ] | None = None
    kind: Literal["ocr", "vision", "analysis", "llm"]
    catalog_id: Annotated[
        str,
        StringConstraints(pattern=r"^[a-z0-9][a-z0-9.-]{0,127}$"),
    ] | None = None
    model_id: Annotated[
        str,
        StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$"),
    ] | None = None
    endpoint: Annotated[str, StringConstraints(max_length=2_048, pattern=r"^https://")]
    protocol: Annotated[
        str,
        StringConstraints(pattern=r"^[a-z0-9][a-z0-9.-]{0,63}$"),
    ] | None = None
    capabilities: Annotated[
        set[Literal["text", "image", "pdf", "ocr"]],
        Field(max_length=4),
    ] = Field(default_factory=set)
    secret_ref: SecretReference
    api_key: Annotated[str, StringConstraints(min_length=1, max_length=4_096)] | None = None
    reasoning_effort: ReasoningEffort = "provider_default"
    enabled: bool = True


class ProviderUpdate(NonEmptyUpdate):
    name: Annotated[
        str,
        StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"),
    ] | None = None
    alias: Annotated[
        str,
        StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,63}$"),
    ] | None = None
    kind: Literal["ocr", "vision", "analysis", "llm"] | None = None
    catalog_id: Annotated[
        str,
        StringConstraints(pattern=r"^[a-z0-9][a-z0-9.-]{0,127}$"),
    ] | None = None
    model_id: Annotated[
        str,
        StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$"),
    ] | None = None
    endpoint: Annotated[
        str,
        StringConstraints(max_length=2_048, pattern=r"^https://"),
    ] | None = None
    protocol: Annotated[
        str,
        StringConstraints(pattern=r"^[a-z0-9][a-z0-9.-]{0,63}$"),
    ] | None = None
    capabilities: Annotated[
        set[Literal["text", "image", "pdf", "ocr"]],
        Field(max_length=4),
    ] | None = None
    secret_ref: SecretReference | None = None
    api_key: Annotated[str, StringConstraints(min_length=1, max_length=4_096)] | None = None
    reasoning_effort: ReasoningEffort | None = None
    enabled: bool | None = None


class RoutingProfileCreate(AdminStrictModel):
    name: Annotated[str, StringConstraints(pattern=r"^\S(?:.{0,126}\S)?$")]
    analysis_provider_ids: Annotated[list[UUID], Field(min_length=1, max_length=32)]
    llm_provider_ids: Annotated[list[UUID], Field(min_length=1, max_length=32)]
    strategy: Literal["priority", "fallback", "health", "cost"] = "priority"
    enabled: bool = True

    @model_validator(mode="after")
    def require_unique_provider_ids(self) -> "RoutingProfileCreate":
        if len(set(self.analysis_provider_ids)) != len(self.analysis_provider_ids):
            raise ValueError("analysis_provider_ids must be unique")
        if len(set(self.llm_provider_ids)) != len(self.llm_provider_ids):
            raise ValueError("llm_provider_ids must be unique")
        return self


class RoutingProfileUpdate(NonEmptyUpdate):
    name: Annotated[
        str,
        StringConstraints(pattern=r"^\S(?:.{0,126}\S)?$"),
    ] | None = None
    analysis_provider_ids: Annotated[list[UUID], Field(min_length=1, max_length=32)] | None = None
    llm_provider_ids: Annotated[list[UUID], Field(min_length=1, max_length=32)] | None = None
    strategy: Literal["priority", "fallback", "health", "cost"] | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def require_unique_provider_ids(self) -> "RoutingProfileUpdate":
        for field_name in ("analysis_provider_ids", "llm_provider_ids"):
            provider_ids = getattr(self, field_name)
            if provider_ids is not None and len(set(provider_ids)) != len(provider_ids):
                raise ValueError(f"{field_name} must be unique")
        return self


class ConnectionCreate(AdminStrictModel):
    name: Annotated[
        str,
        StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"),
    ]
    gateway_url: Annotated[str, StringConstraints(max_length=2_048)]
    credential_secret_ref: SecretReference
    enabled: bool = True

    @field_validator("gateway_url")
    @classmethod
    def validate_gateway_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or ".." in parsed.path.split("/")
        ):
            raise ValueError("Gateway URL must be credential-free HTTPS")
        return value.rstrip("/")


class ConnectionUpdate(NonEmptyUpdate):
    name: Annotated[
        str,
        StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"),
    ] | None = None
    gateway_url: Annotated[str, StringConstraints(max_length=2_048)] | None = None
    credential_secret_ref: SecretReference | None = None
    enabled: bool | None = None

    @field_validator("gateway_url")
    @classmethod
    def validate_optional_gateway_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return ConnectionCreate.validate_gateway_url(value)


class TestLabPreviewRequest(AdminStrictModel):
    routing_profile_id: UUID | None = None
    gateway_url: Annotated[str, StringConstraints(max_length=2_048)] | None = None
    api_key: Annotated[str, StringConstraints(min_length=1, max_length=4_096)] | None = None
    target_model: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None = None
    reasoning_effort: Literal["provider_default", "low", "medium", "high"] = "provider_default"
    conversion_profile: Literal["generic", "error_screenshot", "document"] = "generic"
    user_request: Annotated[str, StringConstraints(min_length=1, max_length=20_000)]
    media_type: Literal["image", "pdf"]
    filename: Annotated[str, StringConstraints(min_length=1, max_length=255)] | None = None
    declared_mime: Literal["image/png", "image/jpeg", "image/webp", "application/pdf"]
    media_base64: Annotated[
        str,
        StringConstraints(min_length=1, max_length=2_796_204),
    ]

    @field_validator("gateway_url")
    @classmethod
    def validate_test_gateway_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return ConnectionCreate.validate_gateway_url(value)

    @model_validator(mode="after")
    def require_downstream_credentials(self) -> "TestLabPreviewRequest":
        if (self.gateway_url is None) != (self.api_key is None):
            raise ValueError("gateway_url and api_key must be provided together")
        return self

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str | None) -> str | None:
        if value is not None and ("/" in value or "\\" in value or value in {".", ".."}):
            raise ValueError("media filename is unsafe")
        return value

    @model_validator(mode="after")
    def validate_media_mime(self) -> "TestLabPreviewRequest":
        if self.media_type == "pdf" and self.declared_mime != "application/pdf":
            raise ValueError("PDF media type and MIME do not match")
        if self.media_type == "image" and not self.declared_mime.startswith("image/"):
            raise ValueError("image media type and MIME do not match")
        return self


class TestLabRunRequest(TestLabPreviewRequest):
    execute_downstream: Literal[True]

    @model_validator(mode="after")
    def require_gateway_credentials(self) -> "TestLabRunRequest":
        if self.gateway_url is None or self.api_key is None:
            raise ValueError("downstream test requires gateway_url and api_key")
        return self


class ModelCapabilityCreate(AdminStrictModel):
    routing_profile_id: UUID | None = None
    provider_id: UUID | None = None
    model_id: Annotated[
        str,
        StringConstraints(pattern=r"^[a-z0-9][a-z0-9./:_-]{0,127}$"),
    ]
    aliases: Annotated[list[str], Field(max_length=32)] = Field(default_factory=list)
    input_modalities: Annotated[
        set[Literal["text", "image", "pdf"]],
        Field(min_length=1, max_length=3),
    ]
    evidence: Annotated[str, StringConstraints(min_length=1, max_length=1_024)] | None = None
    reviewed_at: datetime
    expires_at: datetime | None = None
    pdf_passthrough_verified: bool = False
    reasoning_effort: Literal["provider_default", "low", "medium", "high"] = "provider_default"

    @field_validator("reviewed_at", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("capability timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def require_future_expiry(self) -> "ModelCapabilityCreate":
        if self.expires_at is not None and self.expires_at <= self.reviewed_at:
            raise ValueError("capability expiry must follow review")
        if self.pdf_passthrough_verified and "pdf" not in self.input_modalities:
            raise ValueError("PDF verification requires PDF input modality")
        return self


class ModelCapabilityUpdate(NonEmptyUpdate):
    routing_profile_id: UUID | None = None
    provider_id: UUID | None = None
    model_id: Annotated[
        str,
        StringConstraints(pattern=r"^[a-z0-9][a-z0-9./:_-]{0,127}$"),
    ] | None = None
    aliases: Annotated[list[str], Field(max_length=32)] | None = None
    input_modalities: Annotated[
        set[Literal["text", "image", "pdf"]],
        Field(min_length=1, max_length=3),
    ] | None = None
    evidence: Annotated[str, StringConstraints(min_length=1, max_length=1_024)] | None = (
        None
    )
    reviewed_at: datetime | None = None
    expires_at: datetime | None = None
    pdf_passthrough_verified: bool | None = None
    reasoning_effort: Literal["provider_default", "low", "medium", "high"] | None = None

    @field_validator("reviewed_at", "expires_at")
    @classmethod
    def require_optional_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("capability timestamps must be timezone-aware")
        return value


class PolicyCreate(AdminStrictModel):
    name: Annotated[str, StringConstraints(pattern=r"^\S(?:.{0,126}\S)?$")]
    max_files: Annotated[int, Field(ge=1, le=32)]
    max_media_bytes: Annotated[int, Field(ge=1, le=50 * 1024 * 1024)]
    max_pdf_pages: Annotated[int, Field(ge=1, le=100)]
    allow_url: bool
    allow_base64: bool
    allow_asset: bool
    allow_local_path: bool
    fail_closed: bool
    reasoning_effort: Literal["provider_default", "low", "medium", "high"] = "provider_default"


class PolicyUpdate(NonEmptyUpdate):
    name: Annotated[
        str,
        StringConstraints(pattern=r"^\S(?:.{0,126}\S)?$"),
    ] | None = None
    max_files: Annotated[int, Field(ge=1, le=32)] | None = None
    max_media_bytes: Annotated[int, Field(ge=1, le=50 * 1024 * 1024)] | None = None
    max_pdf_pages: Annotated[int, Field(ge=1, le=100)] | None = None
    allow_url: bool | None = None
    allow_base64: bool | None = None
    allow_asset: bool | None = None
    allow_local_path: bool | None = None
    fail_closed: bool | None = None
    reasoning_effort: Literal["provider_default", "low", "medium", "high"] | None = None


class CredentialCreate(AdminStrictModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    scopes: Annotated[
        set[Literal["assets:write", "mcp:invoke", "responses:invoke"]],
        Field(min_length=1, max_length=3),
    ]
    expires_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value[0].isalnum() or any(
            not (character.isalnum() or character in "_.-") for character in value
        ):
            raise ValueError("credential name contains invalid characters")
        return value

    @field_validator("expires_at")
    @classmethod
    def require_expiry_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("credential expiry must be timezone-aware")
        return value


class PublishSnapshotRequest(AdminStrictModel):
    draft_id: UUID


class SafeAdminError(AdminStrictModel):
    code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class SafeAdminErrorEnvelope(AdminStrictModel):
    error: SafeAdminError = Field()
