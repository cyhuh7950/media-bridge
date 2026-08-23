"""Transport-independent Media Bridge application service."""

from __future__ import annotations

from media_bridge.backends import AnalysisBackend, BackendStatus
from media_bridge.contracts import (
    AnalyzeErrorImageRequest,
    AnalyzeErrorImageResult,
    ExtractImageContextRequest,
    ExtractImageContextResult,
    PrepareForModelRequest,
    PrepareForModelResult,
    SafeError,
)
from media_bridge.gate import GateFailureError, PreRequestGate
from media_bridge.sanitizer import SanitizationError, sanitize_model_text


class MediaBridgeService:
    def __init__(
        self,
        *,
        gate: PreRequestGate,
        analysis_backends: dict[str, AnalysisBackend] | None = None,
    ) -> None:
        self._gate = gate
        self._analysis_backends = analysis_backends or {}

    async def prepare_for_model(
        self,
        request: PrepareForModelRequest,
        *,
        tenant_id: str,
    ) -> PrepareForModelResult:
        outcome = await self._gate.prepare_for_model(request, tenant_id=tenant_id)
        return outcome.public

    async def extract_image_context(
        self,
        request: ExtractImageContextRequest,
        *,
        tenant_id: str,
    ) -> ExtractImageContextResult:
        try:
            context = await self._gate.extract_context(
                request.content,
                conversion_profile=request.conversion_profile,
                tenant_id=tenant_id,
            )
        except GateFailureError as failure:
            return ExtractImageContextResult(
                status="blocked",
                media_type=request.conversion_profile,
                media_modalities=[],
                ocr_text=None,
                visual_description=None,
                structured_context=None,
                original_image_removed=False,
                error=SafeError(code=failure.code, message=failure.safe_message),
            )
        return ExtractImageContextResult(
            status="converted",
            media_type=request.conversion_profile,
            media_modalities=list(context.media_modalities),
            ocr_text=context.ocr_text,
            visual_description=context.visual_description,
            structured_context=context.structured_context,
            original_image_removed=True,
            error=None,
        )

    async def analyze_error_image(
        self,
        request: AnalyzeErrorImageRequest,
        *,
        tenant_id: str,
    ) -> AnalyzeErrorImageResult:
        backend = self._analysis_backends.get(request.analysis_backend)
        if backend is None:
            return self._blocked_analysis(
                request.analysis_backend,
                "analysis_backend_unknown",
                "Requested analysis backend is not configured.",
            )
        extracted = await self.extract_image_context(request, tenant_id=tenant_id)
        if extracted.status == "blocked" or extracted.structured_context is None:
            return AnalyzeErrorImageResult(
                status="blocked",
                analysis_backend=request.analysis_backend,
                analysis=None,
                structured_context=None,
                original_image_removed=False,
                error=extracted.error,
            )
        result = await backend.analyze(
            context=extracted.structured_context,
            user_request=request.user_request,
        )
        if result.status is not BackendStatus.SUCCESS or not result.analysis:
            return self._blocked_analysis(
                request.analysis_backend,
                "analysis_failed",
                "Configured analysis backend failed.",
            )
        try:
            safe_analysis = sanitize_model_text(result.analysis)
        except SanitizationError:
            return self._blocked_analysis(
                request.analysis_backend,
                "analysis_sanitization_failed",
                "Analysis output could not be sanitized.",
            )
        return AnalyzeErrorImageResult(
            status="analyzed",
            analysis_backend=request.analysis_backend,
            analysis=safe_analysis,
            structured_context=extracted.structured_context,
            original_image_removed=True,
            error=None,
        )

    @staticmethod
    def _blocked_analysis(
        backend: str,
        code: str,
        message: str,
    ) -> AnalyzeErrorImageResult:
        return AnalyzeErrorImageResult(
            status="blocked",
            analysis_backend=backend,
            analysis=None,
            structured_context=None,
            original_image_removed=False,
            error=SafeError(code=code, message=message),
        )
