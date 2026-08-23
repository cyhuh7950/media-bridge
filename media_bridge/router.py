"""Mandatory router adapter and guarded downstream reference integration."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Protocol

from media_bridge.contracts import (
    ContentPart,
    PrepareForModelRequest,
    PrepareForModelResult,
    TargetModel,
    TextPart,
)
from media_bridge.detector import detect_media
from media_bridge.gate import DownstreamPayload, PreRequestGate, digest_content
from media_bridge.receipts import GateReceiptSigner, ReceiptValidationError


class GuardRejectedError(RuntimeError):
    """Raised before raw downstream invocation when a gate invariant fails."""


@dataclass(frozen=True, slots=True)
class DownstreamRequest:
    target_id: str
    content: tuple[ContentPart, ...]

    @property
    def media_count(self) -> int:
        return detect_media(list(self.content)).media_count


class DownstreamInvoker(Protocol):
    async def invoke(self, request: DownstreamRequest) -> object: ...


class GuardedDownstream:
    """Verify gate evidence immediately before calling a model provider."""

    def __init__(self, downstream: DownstreamInvoker, signer: GateReceiptSigner) -> None:
        self._downstream = downstream
        self._signer = signer

    async def invoke(self, payload: DownstreamPayload) -> object:
        computed_digest = digest_content(payload.content)
        if not secrets.compare_digest(computed_digest, payload.output_digest):
            raise GuardRejectedError("downstream payload digest does not match gate output")
        try:
            self._signer.verify(payload.receipt, expected=payload.binding)
        except ReceiptValidationError as error:
            raise GuardRejectedError("downstream payload has no valid gate receipt") from error

        detection = detect_media(list(payload.content))
        if payload.capability == "non_vision" and detection.media_count:
            raise GuardRejectedError("non-vision downstream payload contains media")
        if payload.capability not in {"non_vision", "vision"}:
            raise GuardRejectedError("downstream capability is not active and exact")
        if payload.action not in {"passthrough", "converted"}:
            raise GuardRejectedError("downstream action is not permitted")
        if payload.action == "converted" and payload.capability != "non_vision":
            raise GuardRejectedError("converted payload has an invalid capability boundary")

        return await self._downstream.invoke(
            DownstreamRequest(target_id=payload.target_id, content=payload.content)
        )


@dataclass(frozen=True, slots=True)
class SafeConversationState:
    """Text-only state suitable for a new Non-Vision follow-up or subagent."""

    text: str


@dataclass(frozen=True, slots=True)
class RouterInvocation:
    gate_result: PrepareForModelResult
    downstream_response: object | None
    safe_state: SafeConversationState | None


class RouterAdapter:
    """Reference integration that makes the pre-request gate non-optional."""

    def __init__(self, *, gate: PreRequestGate, downstream: GuardedDownstream) -> None:
        self._gate = gate
        self._downstream = downstream

    async def invoke(
        self,
        request: PrepareForModelRequest,
        *,
        tenant_id: str,
    ) -> RouterInvocation:
        outcome = await self._gate.prepare_for_model(request, tenant_id=tenant_id)
        if outcome.prepared is None:
            return RouterInvocation(outcome.public, None, None)

        response = await self._downstream.invoke(outcome.prepared)
        safe_state = self._safe_state(outcome.prepared.content)
        return RouterInvocation(outcome.public, response, safe_state)

    def build_followup_request(
        self,
        *,
        state: SafeConversationState,
        user_text: str,
        target: TargetModel,
    ) -> PrepareForModelRequest:
        return self._fresh_text_request(state=state, user_text=user_text, target=target)

    def build_subagent_handoff(
        self,
        *,
        state: SafeConversationState,
        user_text: str,
        target: TargetModel,
    ) -> PrepareForModelRequest:
        return self._fresh_text_request(state=state, user_text=user_text, target=target)

    @staticmethod
    def _fresh_text_request(
        *,
        state: SafeConversationState,
        user_text: str,
        target: TargetModel,
    ) -> PrepareForModelRequest:
        return PrepareForModelRequest(
            content=[TextPart(text=state.text), TextPart(text=user_text)],
            target=target,
        )

    @staticmethod
    def _safe_state(content: tuple[ContentPart, ...]) -> SafeConversationState | None:
        if detect_media(list(content)).media_count:
            return None
        text = "\n".join(part.text for part in content if isinstance(part, TextPart)).strip()
        return SafeConversationState(text=text) if text else None
