"""Fail-closed pre-request gate for every downstream model invocation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from media_bridge.acquisition import AcquisitionError, MediaAcquirer
from media_bridge.assets import AssetAccessError
from media_bridge.backends import BackendStatus, OcrBackend, VisionBackend
from media_bridge.capabilities import CapabilityRegistry, CapabilityState
from media_bridge.contracts import (
    ContentPart,
    MediaPart,
    PrepareForModelRequest,
    PrepareForModelResult,
    SafeError,
    TextPart,
)
from media_bridge.detector import detect_media
from media_bridge.receipts import GateReceiptSigner, ReceiptBinding
from media_bridge.sanitizer import SanitizationError, sanitize_model_text
from media_bridge.workspace import CleanupError, TemporaryMediaWorkspace


class Sanitizer(Protocol):
    def __call__(
        self,
        text: str,
        *,
        forbidden_locators: Iterable[str] = (),
        max_length: int = 200_000,
    ) -> str: ...


class GateFailureError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


@dataclass(frozen=True, slots=True)
class DownstreamPayload:
    target_id: str
    capability: str
    action: str
    content: tuple[ContentPart, ...]
    input_digest: str
    output_digest: str
    receipt: str

    @property
    def binding(self) -> ReceiptBinding:
        return ReceiptBinding(
            target_id=self.target_id,
            capability=self.capability,
            input_digest=self.input_digest,
            output_digest=self.output_digest,
            action=self.action,
        )


@dataclass(frozen=True, slots=True)
class GateOutcome:
    public: PrepareForModelResult
    prepared: DownstreamPayload | None


@dataclass(frozen=True, slots=True)
class ConvertedContext:
    ocr_text: str
    visual_description: str
    structured_context: str
    media_modalities: tuple[Literal["image", "pdf"], ...]


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def digest_content(content: tuple[ContentPart, ...]) -> str:
    return _canonical_digest([part.model_dump(mode="json") for part in content])


class PreRequestGate:
    """Resolve capability and prepare one signed downstream payload or block."""

    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        acquirer: MediaAcquirer,
        ocr_backend: OcrBackend,
        vision_backend: VisionBackend,
        receipt_signer: GateReceiptSigner,
        sanitizer: Sanitizer | None = None,
        workspace_factory: Callable[[], TemporaryMediaWorkspace] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._registry = registry
        self._acquirer = acquirer
        self._ocr_backend = ocr_backend
        self._vision_backend = vision_backend
        self._receipt_signer = receipt_signer
        self._sanitizer = sanitizer or sanitize_model_text
        self._workspace_factory = workspace_factory or TemporaryMediaWorkspace
        self._now = now or (lambda: datetime.now(UTC))

    async def prepare_for_model(
        self,
        request: PrepareForModelRequest,
        *,
        tenant_id: str,
    ) -> GateOutcome:
        detection = detect_media(request.content)
        target_id = request.target.registry_id
        resolution = self._registry.resolve(target_id, self._now())
        if resolution.state is CapabilityState.UNKNOWN:
            return self._blocked(request, "capability_unknown", "Target capability is unknown.")
        if resolution.state is CapabilityState.STALE:
            return self._blocked(request, "capability_stale", "Target capability is stale.")
        if resolution.capability is None:
            return self._blocked(request, "capability_unknown", "Target capability is unknown.")

        if resolution.state is CapabilityState.VISION and detection.media_count:
            if not resolution.capability.supports_all(detection.modalities):
                return self._blocked(
                    request,
                    "unsupported_media_modality",
                    "Target does not support every requested media modality.",
                )
            return self._ready(
                request,
                content=tuple(request.content),
                capability=resolution.state,
                action="passthrough",
                sanitized_text=self._join_text(request.content),
                original_image_removed=False,
            )

        if resolution.state is CapabilityState.NON_VISION and detection.media_count:
            try:
                converted = await self.extract_context(
                    request.content,
                    conversion_profile=request.conversion_profile,
                    tenant_id=tenant_id,
                )
            except GateFailureError as failure:
                return self._blocked(request, failure.code, failure.safe_message)
            return self._ready(
                request,
                content=(TextPart(text=converted.structured_context),),
                capability=resolution.state,
                action="converted",
                sanitized_text=converted.structured_context,
                original_image_removed=True,
            )

        text = self._join_text(request.content)
        return self._ready(
            request,
            content=tuple(request.content),
            capability=resolution.state,
            action="passthrough",
            sanitized_text=text,
            original_image_removed=True,
        )

    async def extract_context(
        self,
        content: list[ContentPart],
        *,
        conversion_profile: Literal["generic", "error_screenshot", "document"],
        tenant_id: str,
    ) -> ConvertedContext:
        if detect_media(content).media_count == 0:
            raise GateFailureError("media_required", "At least one media item is required.")
        converted_sections: list[str] = []
        ocr_sections: list[str] = []
        description_sections: list[str] = []
        media_modalities: list[Literal["image", "pdf"]] = []
        forbidden_locators: list[str] = []
        text = self._join_text(content)
        if text:
            converted_sections.append(text)

        media_index = 0
        for part in content:
            if not isinstance(part, MediaPart):
                continue
            media_index += 1
            try:
                acquired = await self._acquirer.acquire(part, tenant_id=tenant_id)
            except (AcquisitionError, AssetAccessError):
                raise GateFailureError(
                    "media_acquisition_failed",
                    "Media could not be acquired safely.",
                ) from None
            forbidden_locators.extend(acquired.forbidden_locators)
            if acquired.filename:
                forbidden_locators.append(acquired.filename)

            workspace = self._workspace_factory()
            processing_failure: GateFailureError | None = None
            ocr_text: str | None = None
            description: str | None = None
            extension = ".pdf" if acquired.media_type == "pdf" else ".img"
            try:
                workspace.write_bytes(f"media-{media_index}{extension}", acquired.data)
                ocr_result = await self._ocr_backend.extract(
                    data=acquired.data,
                    mime_type=acquired.mime_type,
                    filename=None,
                )
                if ocr_result.status is BackendStatus.FAILURE:
                    raise GateFailureError("ocr_failed", "OCR conversion failed.")
                ocr_text = ocr_result.text or "No text detected."

                vision_result = await self._vision_backend.describe(
                    data=acquired.data,
                    mime_type=acquired.mime_type,
                    profile=conversion_profile,
                )
                if (
                    vision_result.status is not BackendStatus.SUCCESS
                    or not vision_result.description
                ):
                    raise GateFailureError("vision_failed", "Vision description failed.")
                description = vision_result.description
            except GateFailureError as failure:
                processing_failure = failure
            except Exception:
                processing_failure = GateFailureError(
                    "conversion_failed",
                    "Media conversion failed safely.",
                )
            try:
                workspace.cleanup()
            except CleanupError:
                raise GateFailureError(
                    "cleanup_failed",
                    "Temporary media cleanup could not be verified.",
                ) from None
            if processing_failure is not None:
                raise processing_failure
            ocr_sections.append(ocr_text or "No text detected.")
            description_sections.append(description or "")
            media_modalities.append(acquired.media_type)  # type: ignore[arg-type]
            converted_sections.append(
                f"[Media {media_index} OCR]\n{ocr_text}\n"
                f"[Media {media_index} visual description]\n{description}"
            )

        try:
            return ConvertedContext(
                ocr_text=self._sanitizer(
                    "\n".join(ocr_sections),
                    forbidden_locators=forbidden_locators,
                    max_length=200_000,
                ),
                visual_description=self._sanitizer(
                    "\n".join(description_sections),
                    forbidden_locators=forbidden_locators,
                    max_length=200_000,
                ),
                structured_context=self._sanitizer(
                    "\n\n".join(converted_sections),
                    forbidden_locators=forbidden_locators,
                    max_length=200_000,
                ),
                media_modalities=tuple(media_modalities),
            )
        except (SanitizationError, ValueError):
            raise GateFailureError(
                "sanitization_failed",
                "Converted text could not be sanitized.",
            ) from None

    def _ready(
        self,
        request: PrepareForModelRequest,
        *,
        content: tuple[ContentPart, ...],
        capability: CapabilityState,
        action: Literal["passthrough", "converted"],
        sanitized_text: str,
        original_image_removed: bool,
    ) -> GateOutcome:
        input_digest = _canonical_digest(request.model_dump(mode="json"))
        output_digest = digest_content(content)
        binding = ReceiptBinding(
            target_id=request.target.registry_id,
            capability=capability.value,
            input_digest=input_digest,
            output_digest=output_digest,
            action=action,
        )
        receipt = self._receipt_signer.sign(binding)
        detection = detect_media(request.content)
        return GateOutcome(
            public=PrepareForModelResult(
                action=action,
                target_model=request.target.registry_id,
                contains_media=detection.media_count > 0,
                contains_image=detection.contains_image,
                contains_pdf=detection.contains_pdf,
                target_supports_vision=capability is CapabilityState.VISION,
                sanitized_text=sanitized_text,
                original_image_removed=original_image_removed,
                error=None,
            ),
            prepared=DownstreamPayload(
                target_id=request.target.registry_id,
                capability=capability.value,
                action=action,
                content=content,
                input_digest=input_digest,
                output_digest=output_digest,
                receipt=receipt,
            ),
        )

    def _blocked(self, request: PrepareForModelRequest, code: str, message: str) -> GateOutcome:
        detection = detect_media(request.content)
        return GateOutcome(
            public=PrepareForModelResult(
                action="blocked",
                target_model=request.target.registry_id,
                contains_media=detection.media_count > 0,
                contains_image=detection.contains_image,
                contains_pdf=detection.contains_pdf,
                target_supports_vision=None,
                sanitized_text=None,
                original_image_removed=False,
                error=SafeError(code=code, message=message),
            ),
            prepared=None,
        )

    @staticmethod
    def _join_text(content: list[ContentPart]) -> str:
        return "\n".join(part.text for part in content if isinstance(part, TextPart)).strip()
