"""Product-neutral Gateway request, response, subject, and downstream contracts."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from media_bridge.assets import AssetAccessError, validate_tenant_id
from media_bridge.contracts import PrepareForModelResult, SafeError
from media_bridge.receipts import ReceiptBinding

_SELECTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SCOPE = re.compile(r"^[a-z][a-z0-9_-]{0,31}:[a-z][a-z0-9_-]{0,31}$")


class DownstreamGuardError(RuntimeError):
    """Raised before a socket call when sealed evidence is invalid."""


class DownstreamError(RuntimeError):
    """Safe bounded downstream failure without provider response content."""

    def __init__(self, code: str, message: str, *, http_status: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class DataPlaneSubject:
    credential_selector: str
    tenant_id: str
    scopes: frozenset[str]

    def __post_init__(self) -> None:
        if not _SELECTOR.fullmatch(self.credential_selector):
            raise ValueError("data-plane credential selector is invalid")
        try:
            validate_tenant_id(self.tenant_id)
        except AssetAccessError as error:
            raise ValueError("data-plane tenant identifier is invalid") from error
        if not self.scopes or any(not _SCOPE.fullmatch(scope) for scope in self.scopes):
            raise ValueError("data-plane credential scopes are invalid")


@dataclass(frozen=True, slots=True)
class SealedGatewayRequest:
    target_id: str
    capability: str
    action: str
    payload: dict[str, Any]
    input_digest: str
    output_digest: str
    receipt: str
    request_nonce: str
    snapshot_version: int = 0

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
class GatewayResponse:
    body: bytes
    content_type: str
    response_id: str
    status_code: int
    stream: AsyncIterator[bytes] | None = None


@dataclass(frozen=True, slots=True)
class GatewayResult:
    status: Literal["completed", "blocked", "upstream_error"]
    response: GatewayResponse | None
    gate_result: PrepareForModelResult | None
    error: SafeError | None
    http_status: int
    warning: SafeError | None = None


@runtime_checkable
class ResponsesDownstream(Protocol):
    async def invoke(self, request: SealedGatewayRequest) -> GatewayResponse: ...
