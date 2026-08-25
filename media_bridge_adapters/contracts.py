"""Strict public contracts for resolved-target pre-upstream adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from media_bridge_adapters.validation import validate_adapter_endpoint

_IDENTIFIER = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$"),
]
_DIGEST = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
_TOKEN = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{43}$")]
_COMMIT = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{40}$")]
_ENV_NAME = Annotated[str, StringConstraints(pattern=r"^[A-Z_][A-Z0-9_]{0,127}$")]
_SEMVER = Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResponsibilityMode(StrictModel):
    """Declare which side owns capability, routing, and provider execution."""

    mode: Literal["standalone", "eoul"]
    capability_owner: Literal["media_bridge", "eoul"]
    routing_owner: Literal["media_bridge", "eoul"]
    provider_execution_owner: Literal["media_bridge", "eoul"]

    @model_validator(mode="after")
    def validate_ownership(self) -> Self:
        if self.mode == "eoul" and (
            self.capability_owner,
            self.routing_owner,
            self.provider_execution_owner,
        ) != ("eoul", "eoul", "eoul"):
            raise ValueError("Eoul mode delegates capability, routing, and execution to Eoul")
        return self


class AdapterManifest(StrictModel):
    adapter_id: Literal["opencodex", "omniroute"]
    adapter_version: _SEMVER
    product_contract: Literal["media-bridge-pre-upstream/v1"]
    supported_external_versions: tuple[_SEMVER, ...]
    external_base_commit: _COMMIT
    extension_commit: _COMMIT
    required_gateway_scopes: tuple[str, ...]


class CompatibilityResult(StrictModel):
    adapter_id: str
    external_version: str
    compatible: bool
    reason: Literal["unknown_adapter", "unsupported_external_build"] | None
    manifest: AdapterManifest | None


class AdapterConfigRequest(StrictModel):
    adapter_id: Literal["opencodex", "omniroute"]
    external_version: _SEMVER
    external_base_commit: _COMMIT
    extension_commit: _COMMIT
    endpoint: str
    credential_env: _ENV_NAME
    decision_hmac_env: _ENV_NAME
    timeout_ms: int = Field(ge=1, le=120_000)
    max_response_bytes: int = Field(ge=1, le=4 * 1024 * 1024)
    output_path: Path

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        return validate_adapter_endpoint(value)

    @field_validator("output_path")
    @classmethod
    def validate_output_path(cls, value: Path) -> Path:
        if not value.is_absolute() or value.name in {"", ".", ".."}:
            raise ValueError("Adapter output path must be an explicit absolute file path")
        return value


class RenderedConfig(StrictModel):
    adapter_id: Literal["opencodex", "omniroute"]
    external_version: _SEMVER
    content: str
    output_path: Path


class AdapterProbeResult(StrictModel):
    reachable: bool
    http_status: int | None
    error: Literal[
        "credential_unavailable",
        "endpoint_invalid",
        "probe_failed",
        "redirect_rejected",
        "response_invalid",
        "response_too_large",
    ] | None


class AdapterSafeError(StrictModel):
    code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    message: Annotated[str, StringConstraints(max_length=200)]


class PreUpstreamRequest(StrictModel):
    contract_version: Literal["media-bridge-pre-upstream/v1"]
    request_id: _IDENTIFIER
    wire_format: Literal["openai-responses"]
    provider: _IDENTIFIER
    target_model: _IDENTIFIER
    body: dict[str, Any]


class PreUpstreamResult(StrictModel):
    status: Literal["unchanged", "prepared", "blocked"]
    provider: _IDENTIFIER
    target_model: _IDENTIFIER
    capability: Literal["vision", "non_vision"] | None
    body: dict[str, Any] | None
    original_media_removed: bool
    input_digest: _DIGEST | None
    output_digest: _DIGEST | None
    decision_token: _TOKEN | None
    error: AdapterSafeError | None

    @model_validator(mode="after")
    def validate_decision_shape(self) -> Self:
        decision_fields = (
            self.capability,
            self.body,
            self.input_digest,
            self.output_digest,
            self.decision_token,
        )
        if self.status == "blocked":
            if any(value is not None for value in decision_fields) or self.error is None:
                raise ValueError("blocked result cannot carry a prepared decision")
            if self.original_media_removed:
                raise ValueError("blocked result cannot claim media removal")
            return self
        if any(value is None for value in decision_fields) or self.error is not None:
            raise ValueError("successful result requires a complete prepared decision")
        if self.capability == "non_vision" and not self.original_media_removed:
            raise ValueError("non-vision result must remove original media")
        return self


class GatewayPrepareResponse(StrictModel):
    action: Literal["passthrough", "converted", "blocked"]
    target_model: str
    contains_media: bool
    contains_image: bool
    contains_pdf: bool
    target_supports_vision: bool | None
    sanitized_text: str | None
    original_image_removed: bool
    error: AdapterSafeError | None
