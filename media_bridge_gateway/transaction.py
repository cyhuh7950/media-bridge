"""Mandatory product-neutral Responses transaction around the Core gate."""

from __future__ import annotations

import copy
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from typing import Any, cast

from media_bridge.capabilities import CapabilityState
from media_bridge.contracts import (
    Base64Source,
    MediaPart,
    PrepareForModelResult,
    SafeError,
    TextPart,
)
from media_bridge.contracts_v2 import (
    InteropV2Result,
    MediaBridgeV2ErrorCode,
    V2Error,
)
from media_bridge.detector import detect_media
from media_bridge.gate import DownstreamPayload, PreRequestGate
from media_bridge.idempotency import IdempotencyStore
from media_bridge.interop_v2 import (
    ReceiptValidationError,
    TransformationReceipt,
    build_transformation_receipt,
)
from media_bridge.receipts import GateReceiptSigner, ReceiptBinding
from media_bridge.receipts import ReceiptValidationError as GateReceiptValidationError
from media_bridge.responses_state import ResponsesStateRecord
from media_bridge_gateway.contracts import (
    DataPlaneSubject,
    DownstreamError,
    DownstreamGuardError,
    GatewayResponse,
    GatewayResult,
    ResponsesDownstream,
    SealedGatewayRequest,
)
from media_bridge_gateway.normalizer import (
    NormalizedResponsesRequest,
    ResponsesNormalizationError,
    digest_gateway_payload,
    normalize_responses_request,
)
from media_bridge_gateway.state import (
    GatewayStateError,
    GatewayStateStore,
    MediaModality,
)


def _blocked(
    code: str,
    message: str,
    *,
    gate_result: PrepareForModelResult | None = None,
    http_status: int = 400,
) -> GatewayResult:
    return GatewayResult(
        status="blocked",
        response=None,
        gate_result=gate_result,
        error=SafeError(code=code, message=message),
        http_status=http_status,
    )


def _media_part_to_response(part: MediaPart) -> dict[str, Any]:
    if not isinstance(part.source, Base64Source):
        raise DownstreamGuardError("gated media was not normalized to bounded base64")
    encoded = part.source.data
    if part.media_type == "image":
        mime_type = part.declared_mime or "image/png"
        return {
            "type": "input_image",
            "image_url": f"data:{mime_type};base64,{encoded}",
        }
    return {
        "type": "input_file",
        "file_data": f"data:application/pdf;base64,{encoded}",
    }


def _rebuilt_input(prepared: DownstreamPayload) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for part in prepared.content:
        if isinstance(part, TextPart):
            content.append({"type": "input_text", "text": part.text})
        elif isinstance(part, MediaPart):
            content.append(_media_part_to_response(part))
    if not content:
        raise DownstreamGuardError("gated payload did not contain downstream input")
    return [{"type": "message", "role": "user", "content": content}]


def _build_downstream_payload(
    raw_payload: dict[str, Any],
    normalized: NormalizedResponsesRequest,
    prepared: DownstreamPayload,
) -> dict[str, Any]:
    if not normalized.input_had_media and normalized.previous_state is None:
        rebuilt = copy.deepcopy(raw_payload)
        rebuilt.pop("previous_response_id", None)
        rebuilt.pop("conversation", None)
        rebuilt["model"] = prepared.target_id
        return rebuilt

    rebuilt = {
        key: copy.deepcopy(value)
        for key, value in raw_payload.items()
        if key not in {"model", "input", "previous_response_id", "conversation"}
    }
    rebuilt["model"] = prepared.target_id
    rebuilt["input"] = _rebuilt_input(prepared)
    if normalized.previous_state is None and isinstance(raw_payload.get("input"), list):
        history = copy.deepcopy(raw_payload["input"])
        user_indices = [index for index, item in enumerate(history)
                        if isinstance(item, dict) and item.get("role") == "user"]
        if not user_indices:
            raise DownstreamGuardError("gated request has no current user message")
        history[user_indices[-1]]["content"] = rebuilt["input"][0]["content"]
        rebuilt["input"] = history
    return rebuilt


class GatewayTransaction:
    """Normalize, gate, seal, invoke, and persist sanitized state in that order."""

    def __init__(
        self,
        *,
        gate: PreRequestGate,
        downstream: ResponsesDownstream,
        receipt_signer: GateReceiptSigner,
        state_store: GatewayStateStore,
        snapshot_version: int = 0,
    ) -> None:
        if snapshot_version < 0:
            raise ValueError("snapshot version cannot be negative")
        self._gate = gate
        self._downstream = downstream
        self._receipt_signer = receipt_signer
        self._state_store = state_store
        self._snapshot_version = snapshot_version

    def clear_state(self) -> None:
        self._state_store.clear()

    async def invoke(self, payload: object, *, subject: DataPlaneSubject) -> GatewayResult:
        if "responses:invoke" not in subject.scopes:
            return _blocked(
                "credential_scope_denied",
                "Data-plane credential is not authorized for Responses.",
                http_status=403,
            )
        tenant_id = subject.tenant_id
        state = None
        if isinstance(payload, dict):
            previous_id = payload.get("previous_response_id")
            if isinstance(previous_id, str):
                try:
                    state = self._state_store.resolve(
                        previous_id,
                        tenant_id=tenant_id,
                        credential_selector=subject.credential_selector,
                    )
                except GatewayStateError as error:
                    return _blocked(error.code, error.safe_message)

        try:
            normalized = normalize_responses_request(
                payload,
                state=cast(ResponsesStateRecord | None, state),
            )
        except ResponsesNormalizationError as error:
            return _blocked(error.code, error.safe_message)

        state_policy_failure = self._check_state_capability(normalized)
        if state_policy_failure is not None:
            return state_policy_failure

        outcome = await self._gate.prepare_for_model(normalized.request, tenant_id=tenant_id)
        if outcome.prepared is None:
            gate_error = outcome.public.error or SafeError(
                code="pre_request_blocked",
                message="Pre-request gate blocked the request.",
            )
            return _blocked(
                gate_error.code,
                gate_error.message,
                gate_result=outcome.public,
            )

        prepared = outcome.prepared
        try:
            self._receipt_signer.verify(prepared.receipt, expected=prepared.binding)
            if not isinstance(payload, dict):
                raise TypeError
            raw_payload = cast(dict[str, Any], payload)
            downstream_payload = _build_downstream_payload(raw_payload, normalized, prepared)
            input_digest = digest_gateway_payload(raw_payload)
            request_nonce = secrets.token_urlsafe(18)
            output_digest = digest_gateway_payload(
                {
                    "payload": downstream_payload,
                    "request_nonce": request_nonce,
                }
            )
            binding = ReceiptBinding(
                target_id=prepared.target_id,
                capability=prepared.capability,
                input_digest=input_digest,
                output_digest=output_digest,
                action=prepared.action,
            )
            sealed = SealedGatewayRequest(
                target_id=binding.target_id,
                capability=binding.capability,
                action=binding.action,
                payload=downstream_payload,
                input_digest=binding.input_digest,
                output_digest=binding.output_digest,
                receipt=self._receipt_signer.sign(binding),
                request_nonce=request_nonce,
                snapshot_version=self._snapshot_version,
            )
        except (
            GateReceiptValidationError,
            DownstreamGuardError,
            TypeError,
            ValueError,
            OverflowError,
        ):
            return _blocked(
                "gateway_sealing_failed",
                "Responses request could not be sealed safely.",
                gate_result=outcome.public,
                http_status=500,
            )

        try:
            response = await self._downstream.invoke(sealed)
        except DownstreamGuardError:
            return _blocked(
                "gateway_guard_rejected",
                "Responses downstream guard rejected the request.",
                gate_result=outcome.public,
                http_status=500,
            )
        except DownstreamError as downstream_error:
            return GatewayResult(
                status="upstream_error",
                response=None,
                gate_result=outcome.public,
                error=SafeError(
                    code=downstream_error.code,
                    message=downstream_error.safe_message,
                ),
                http_status=downstream_error.http_status,
            )

        if response.stream is not None:
            return GatewayResult(
                status="completed",
                response=self._defer_state_until_stream_complete(
                    response=response,
                    subject=subject,
                    normalized=normalized,
                    prepared=prepared,
                ),
                gate_result=outcome.public,
                error=None,
                http_status=response.status_code,
            )

        try:
            self._record_state(
                response=response,
                subject=subject,
                normalized=normalized,
                prepared=prepared,
            )
        except ValueError:
            return GatewayResult(
                status="completed",
                response=response,
                gate_result=outcome.public,
                error=None,
                warning=SafeError(
                    code="state_persistence_failed",
                    message="Sanitized response state could not be persisted.",
                ),
                http_status=response.status_code,
            )
        return GatewayResult(
            status="completed",
            response=response,
            gate_result=outcome.public,
            error=None,
            http_status=response.status_code,
        )

    def _defer_state_until_stream_complete(
        self,
        *,
        response: GatewayResponse,
        subject: DataPlaneSubject,
        normalized: NormalizedResponsesRequest,
        prepared: DownstreamPayload,
    ) -> GatewayResponse:
        source = response.stream
        if source is None:
            raise ValueError("streaming response has no stream")

        async def state_committing_stream() -> AsyncIterator[bytes]:
            completed = False
            try:
                async for chunk in source:
                    yield chunk
                completed = True
            finally:
                if not completed:
                    close = getattr(source, "aclose", None)
                    if callable(close):
                        with suppress(Exception):
                            await close()
            if completed:
                try:
                    self._record_state(
                        response=response,
                        subject=subject,
                        normalized=normalized,
                        prepared=prepared,
                    )
                except ValueError:
                    # HTTP headers are already committed for a completed stream.
                    # Preserve the provider result and leave follow-up state absent.
                    return

        return GatewayResponse(
            body=response.body,
            content_type=response.content_type,
            response_id=response.response_id,
            status_code=response.status_code,
            stream=state_committing_stream(),
        )

    def _check_state_capability(
        self,
        normalized: NormalizedResponsesRequest,
    ) -> GatewayResult | None:
        state = normalized.previous_state
        if state is None or not state.media_tainted:
            return None
        resolution = self._gate.resolve_capability(normalized.request.target.registry_id)
        if resolution.state is CapabilityState.UNKNOWN or resolution.capability is None:
            return _blocked("capability_unknown", "Target capability is unknown.")
        if resolution.state is CapabilityState.STALE:
            return _blocked("capability_stale", "Target capability is stale.")
        if resolution.state is not CapabilityState.VISION:
            return _blocked(
                "tainted_state_nonvision",
                "Media-tainted state cannot be sent to a Non-Vision target.",
            )
        if not resolution.capability.supports_all(state.media_modalities):
            return _blocked(
                "tainted_state_unsupported",
                "Target does not support all media modalities in prior state.",
            )
        if "pdf" in state.media_modalities and not resolution.capability.pdf_passthrough_verified:
            return _blocked(
                "pdf_passthrough_unverified",
                "Target PDF passthrough capability is not verified.",
            )
        return None

    def _record_state(
        self,
        *,
        response: GatewayResponse,
        subject: DataPlaneSubject,
        normalized: NormalizedResponsesRequest,
        prepared: DownstreamPayload,
    ) -> None:
        sanitized_text = "\n".join(
            part.text for part in prepared.content if isinstance(part, TextPart)
        ).strip()
        current_modalities = detect_media(list(prepared.content)).modalities
        previous_modalities = (
            normalized.previous_state.media_modalities
            if normalized.previous_state is not None
            else frozenset()
        )
        modalities = cast(
            frozenset[MediaModality],
            frozenset(current_modalities.union(previous_modalities)),
        )
        media_tainted = bool(modalities)
        self._state_store.put(
            response_id=response.response_id,
            tenant_id=subject.tenant_id,
            credential_selector=subject.credential_selector,
            sanitized_text=sanitized_text,
            media_tainted=media_tainted,
            media_modalities=modalities if media_tainted else frozenset(),
            target_id=prepared.target_id,
            snapshot_version=self._snapshot_version,
        )


class V2PreparationTransaction:
    """Run transform, verified cleanup, then issue a metadata-only receipt."""

    def __init__(self, *, ttl_seconds: int = 30) -> None:
        self._idempotency = IdempotencyStore(ttl_seconds=ttl_seconds)
        self._ttl_seconds = ttl_seconds

    def execute(
        self,
        *,
        idempotency_key: str,
        fingerprint: str,
        transform: Callable[[], InteropV2Result],
        cleanup: Callable[[], bool],
    ) -> tuple[InteropV2Result, TransformationReceipt | None]:
        def operation() -> tuple[InteropV2Result, TransformationReceipt | None]:
            result = transform()
            if result.status != "PREPARED":
                return result, None
            if not cleanup():
                blocked = result.model_copy(
                    update={
                        "status": "BLOCKED",
                        "sanitized_messages": [],
                        "original_media_removed": False,
                        "error": V2Error(
                            code=MediaBridgeV2ErrorCode.ORIGINAL_MEDIA_REMAINS,
                            message="Original media cleanup was not verified.",
                        ),
                    }
                )
                return blocked, None
            try:
                receipt = build_transformation_receipt(
                    result,
                    ttl_seconds=self._ttl_seconds,
                )
            except ReceiptValidationError as error:
                blocked = result.model_copy(
                    update={
                        "status": "BLOCKED",
                        "sanitized_messages": [],
                        "original_media_removed": False,
                        "error": V2Error(
                            code=MediaBridgeV2ErrorCode.SANITIZATION_FAILED,
                            message=str(error),
                        ),
                    }
                )
                return blocked, None
            return result, receipt

        return self._idempotency.run(idempotency_key, fingerprint, operation)
