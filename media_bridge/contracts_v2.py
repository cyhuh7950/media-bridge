"""Additive Media Bridge interop v2 request and result contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

from media_bridge.contracts import StrictModel

Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
OpaqueId = Annotated[str, StringConstraints(min_length=1, max_length=256)]


class MediaBridgeV2ErrorCode(StrEnum):
    MEDIA_UNSUPPORTED = "MEDIA_UNSUPPORTED"
    ASSET_NOT_FOUND = "ASSET_NOT_FOUND"
    ASSET_EXPIRED = "ASSET_EXPIRED"
    FETCH_DENIED = "FETCH_DENIED"
    SSRF_BLOCKED = "SSRF_BLOCKED"
    SIZE_LIMIT_EXCEEDED = "SIZE_LIMIT_EXCEEDED"
    OCR_FAILED = "OCR_FAILED"
    VISION_BACKEND_FAILED = "VISION_BACKEND_FAILED"
    SANITIZATION_FAILED = "SANITIZATION_FAILED"
    POLICY_DENIED = "POLICY_DENIED"
    ORIGINAL_MEDIA_REMAINS = "ORIGINAL_MEDIA_REMAINS"
    CONTRACT_VERSION_UNSUPPORTED = "CONTRACT_VERSION_UNSUPPORTED"
    CAPABILITY_UNKNOWN = "CAPABILITY_UNKNOWN"
    CAPABILITY_STALE = "CAPABILITY_STALE"
    GATEWAY_LOOP_DETECTED = "GATEWAY_LOOP_DETECTED"


class V2Error(StrictModel):
    code: MediaBridgeV2ErrorCode
    message: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    retryable: bool = False


class AssetReference(StrictModel):
    asset_id: OpaqueId | None = None
    signed_url: Annotated[
        str, StringConstraints(pattern=r"^https://", max_length=2_048)
    ] | None = None
    inline_base64: Annotated[str, StringConstraints(max_length=2_796_204)] | None = None
    media_type_hint: Literal["image", "pdf", "document", "audio", "video", "unknown"] = "unknown"
    digest: Digest | None = None
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def require_one_source(self) -> AssetReference:
        sources = (self.asset_id, self.signed_url, self.inline_base64)
        if sum(value is not None for value in sources) != 1:
            raise ValueError("exactly one asset source is required")
        return self


class TargetCapabilitySnapshot(StrictModel):
    model_id: OpaqueId
    capability_snapshot_version: OpaqueId
    capability_snapshot_digest: Digest
    capabilities: dict[str, Any]
    observed_at: datetime
    fresh_until: datetime

    def is_fresh(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        return current <= self.fresh_until


class TransformationPolicy(StrictModel):
    profile: OpaqueId = "default"
    allowed_output_modalities: list[str] = Field(default_factory=lambda: ["text"], min_length=1)
    backend_allowlist: list[str] = Field(default_factory=list)
    security_grade: OpaqueId = "standard"
    region: OpaqueId = "self-hosted"
    max_asset_bytes: int = Field(default=10_485_760, ge=1, le=100_000_000)
    max_assets: int = Field(default=4, ge=1, le=64)
    ttl_seconds: int = Field(default=300, ge=1, le=86_400)


class HopMetadata(StrictModel):
    hop_id: OpaqueId
    visited_gateways: list[OpaqueId] = Field(default_factory=list, max_length=16)
    max_hops: int = Field(default=2, ge=1, le=16)


class InteropV2Request(StrictModel):
    contract_version: Literal["media-bridge-interop/v2"]
    request_id: OpaqueId
    trace_id: OpaqueId
    idempotency_key: OpaqueId
    mode: Literal["standalone", "host_managed", "eoul"]
    host_id: OpaqueId | None = None
    canonical_messages: list[dict[str, Any]] = Field(min_length=1, max_length=128)
    assets: list[AssetReference] = Field(default_factory=list, max_length=64)
    target: TargetCapabilitySnapshot
    transformation_policy: TransformationPolicy = Field(default_factory=TransformationPolicy)
    original_retention: Literal["delete_after_transform"] = "delete_after_transform"
    hop: HopMetadata

    @model_validator(mode="after")
    def validate_host_identity(self) -> InteropV2Request:
        if self.mode == "host_managed" and self.host_id is None:
            raise ValueError("host_managed requests require host_id")
        return self

    @property
    def normalized_mode(self) -> Literal["standalone", "host_managed"]:
        return "host_managed" if self.mode == "eoul" else self.mode

    @property
    def normalized_owner(self) -> Literal["media_bridge", "external_host"]:
        return "media_bridge" if self.normalized_mode == "standalone" else "external_host"


class TransformationEvidence(StrictModel):
    kind: OpaqueId
    backend: OpaqueId
    version: OpaqueId
    input_digest: Digest
    output_digest: Digest


class BackendEvidence(StrictModel):
    id: OpaqueId
    version: OpaqueId


class ProvenanceEvidence(StrictModel):
    source: OpaqueId
    stage: OpaqueId
    evidence_digest: Digest


class ConfidenceEvidence(StrictModel):
    overall: float = Field(ge=0, le=1)
    by_stage: dict[str, float] = Field(default_factory=dict)


class InformationLossEvidence(StrictModel):
    present: bool
    categories: list[OpaqueId] = Field(default_factory=list)
    summary: Annotated[str, StringConstraints(max_length=500)] = ""


class TokenEstimate(StrictModel):
    input: int = Field(ge=0)
    method: OpaqueId


class PreparedMarker(StrictModel):
    schema_digest: Digest
    expires_at: datetime


class InteropV2Result(StrictModel):
    contract_version: Literal["media-bridge-interop/v2"]
    status: Literal["UNCHANGED", "PREPARED", "BLOCKED", "FAILED"]
    request_id: OpaqueId
    trace_id: OpaqueId
    idempotency_key: OpaqueId
    sanitized_messages: list[dict[str, Any]] = Field(default_factory=list, max_length=128)
    original_media_removed: bool
    error: V2Error | None = None
    asset_digests: list[Digest] = Field(default_factory=list, max_length=64)
    media_types: list[OpaqueId] = Field(default_factory=list, max_length=64)
    transformations: list[TransformationEvidence] = Field(default_factory=list, max_length=64)
    backend: BackendEvidence | None = None
    provenance: list[ProvenanceEvidence] = Field(default_factory=list, max_length=64)
    confidence: ConfidenceEvidence | None = None
    warnings: list[OpaqueId] = Field(default_factory=list, max_length=64)
    information_loss: InformationLossEvidence | None = None
    required_capabilities_after: dict[str, Any] | None = None
    token_estimate: TokenEstimate | None = None
    prepared_marker: PreparedMarker | None = None

    @model_validator(mode="after")
    def validate_status_invariants(self) -> InteropV2Result:
        if self.status == "PREPARED":
            if not self.original_media_removed or self.error is not None:
                raise ValueError("prepared result must remove media and have no error")
            if not self.asset_digests or not self.media_types or not self.transformations:
                raise ValueError("prepared result requires transformation evidence")
            if not self.backend or not self.provenance or not self.confidence:
                raise ValueError("prepared result requires backend and provenance")
            if self.information_loss is None or self.required_capabilities_after is None:
                raise ValueError(
                    "prepared result requires capability and information-loss evidence"
                )
            if self.token_estimate is None or self.prepared_marker is None:
                raise ValueError("prepared result requires token and marker evidence")
        elif self.status == "UNCHANGED":
            if not self.original_media_removed or self.error is not None:
                raise ValueError("unchanged result must be safe and error-free")
        elif self.error is None:
            raise ValueError("blocked and failed results require a stable error")
        return self


def provider_call_allowed(result: InteropV2Result) -> bool:
    """Return whether a downstream provider may receive this prepared result."""

    return result.status in {"PREPARED", "UNCHANGED"} and result.original_media_removed
