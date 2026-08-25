"""Strict public contracts for resolved-target pre-upstream adapters."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

_IDENTIFIER = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$"),
]
_DIGEST = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
_TOKEN = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{43}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
