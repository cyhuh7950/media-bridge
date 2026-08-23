"""Strict Admin API request contracts."""

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from media_bridge.contracts import StrictModel


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


class SecretReference(AdminStrictModel):
    kind: Literal["env", "docker_secret", "external"]
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
    kind: Literal["ocr", "vision", "analysis"]
    endpoint: Annotated[str, StringConstraints(max_length=2_048, pattern=r"^https://")]
    secret_ref: SecretReference
    enabled: bool = True


class ProviderUpdate(NonEmptyUpdate):
    name: Annotated[
        str,
        StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"),
    ] | None = None
    kind: Literal["ocr", "vision", "analysis"] | None = None
    endpoint: Annotated[
        str,
        StringConstraints(max_length=2_048, pattern=r"^https://"),
    ] | None = None
    secret_ref: SecretReference | None = None
    enabled: bool | None = None


class ModelCapabilityCreate(AdminStrictModel):
    model_id: Annotated[
        str,
        StringConstraints(pattern=r"^[a-z0-9][a-z0-9./:_-]{0,127}$"),
    ]
    aliases: Annotated[list[str], Field(max_length=32)] = Field(default_factory=list)
    input_modalities: Annotated[
        set[Literal["text", "image", "pdf"]],
        Field(min_length=1, max_length=3),
    ]
    evidence: Annotated[str, StringConstraints(min_length=1, max_length=1_024)]
    reviewed_at: datetime
    expires_at: datetime
    pdf_passthrough_verified: bool = False

    @field_validator("reviewed_at", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("capability timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def require_future_expiry(self) -> "ModelCapabilityCreate":
        if self.expires_at <= self.reviewed_at:
            raise ValueError("capability expiry must follow review")
        if self.pdf_passthrough_verified and "pdf" not in self.input_modalities:
            raise ValueError("PDF verification requires PDF input modality")
        return self


class ModelCapabilityUpdate(NonEmptyUpdate):
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

    @field_validator("reviewed_at", "expires_at")
    @classmethod
    def require_optional_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("capability timestamps must be timezone-aware")
        return value


class PolicyCreate(AdminStrictModel):
    name: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]
    max_files: Annotated[int, Field(ge=1, le=32)]
    max_media_bytes: Annotated[int, Field(ge=1, le=50 * 1024 * 1024)]
    max_pdf_pages: Annotated[int, Field(ge=1, le=100)]
    allow_url: bool
    allow_base64: bool
    allow_asset: bool
    allow_local_path: bool
    fail_closed: Literal[True]


class PolicyUpdate(NonEmptyUpdate):
    name: Annotated[
        str,
        StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"),
    ] | None = None
    max_files: Annotated[int, Field(ge=1, le=32)] | None = None
    max_media_bytes: Annotated[int, Field(ge=1, le=50 * 1024 * 1024)] | None = None
    max_pdf_pages: Annotated[int, Field(ge=1, le=100)] | None = None
    allow_url: bool | None = None
    allow_base64: bool | None = None
    allow_asset: bool | None = None
    allow_local_path: bool | None = None
    fail_closed: Literal[True] | None = None


class CredentialCreate(AdminStrictModel):
    name: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]
    scopes: Annotated[
        set[Literal["assets:write", "mcp:invoke", "responses:invoke"]],
        Field(min_length=1, max_length=3),
    ]
    expires_at: datetime | None = None

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
