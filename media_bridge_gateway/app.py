"""Authenticated product Data Plane app for Responses, MCP, and assets."""

from __future__ import annotations

import contextvars
import json
import time
from collections.abc import Callable
from uuid import uuid4

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from media_bridge.assets import AssetAccessError, AssetStore
from media_bridge.config_snapshot import SnapshotVerificationError
from media_bridge.contracts import (
    AnalyzeErrorImageRequest,
    AnalyzeErrorImageResult,
    ExtractImageContextRequest,
    ExtractImageContextResult,
    PrepareForModelRequest,
    PrepareForModelResult,
)
from media_bridge.mcp_server import build_mcp_server
from media_bridge.service import MediaBridgeService
from media_bridge_gateway.auth import CredentialAuthenticationError
from media_bridge_gateway.contracts import DataPlaneSubject
from media_bridge_gateway.events import (
    GatewayEvent,
    GatewayEventSink,
    NullGatewayEventSink,
    emit_safely,
    latency_bucket,
    size_bucket,
)
from media_bridge_gateway.rate_limit import CredentialRouteRateLimiter
from media_bridge_gateway.runtime import GatewayGeneration, VerifiedSnapshotRuntime

current_generation: contextvars.ContextVar[GatewayGeneration | None] = contextvars.ContextVar(
    "media_bridge_gateway_generation",
    default=None,
)
current_subject: contextvars.ContextVar[DataPlaneSubject | None] = contextvars.ContextVar(
    "media_bridge_gateway_subject",
    default=None,
)
current_event_status: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "media_bridge_gateway_event_status",
    default=None,
)
current_event_model: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "media_bridge_gateway_event_model",
    default=None,
)


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "message": message,
                "type": "media_bridge_error",
                "code": code,
            }
        },
        status_code=status_code,
    )


class DataPlaneAuthMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        runtime: VerifiedSnapshotRuntime,
        rate_limiter: CredentialRouteRateLimiter,
        event_sink: GatewayEventSink,
        request_id_factory: Callable[[], str],
        monotonic: Callable[[], float],
    ) -> None:
        self._app = app
        self._runtime = runtime
        self._rate_limiter = rate_limiter
        self._event_sink = event_sink
        self._request_id_factory = request_id_factory
        self._monotonic = monotonic

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        required_scope, route_key = self._route_security(path)
        request_id = self._request_id_factory()
        started_at = self._monotonic()
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        request_size = self._request_size(headers.get("content-length"))
        try:
            generation = self._runtime.current()
            subject = generation.credential_verifier.authenticate(
                authorization=headers.get("authorization"),
                required_scope=required_scope,
                cookie_header=headers.get("cookie"),
            )
        except SnapshotVerificationError:
            await _error(
                "gateway_unavailable",
                "No valid Gateway snapshot is available.",
                503,
            )(scope, receive, send)
            self._emit(
                request_id=request_id,
                route_key=route_key,
                status_code="gateway_unavailable",
                model_id=None,
                policy_version=None,
                started_at=started_at,
                request_size=request_size,
            )
            return
        except CredentialAuthenticationError as error:
            auth_status = 403 if error.code == "admin_session_not_allowed" else 401
            await _error(error.code, "Data-plane credential was rejected.", auth_status)(
                scope,
                receive,
                send,
            )
            self._emit(
                request_id=request_id,
                route_key=route_key,
                status_code=error.code,
                model_id=None,
                policy_version=generation.version,
                started_at=started_at,
                request_size=request_size,
            )
            return
        if not self._rate_limiter.allow(subject.credential_selector, route_key):
            await _error("rate_limited", "Data-plane rate limit was exceeded.", 429)(
                scope,
                receive,
                send,
            )
            self._emit(
                request_id=request_id,
                route_key=route_key,
                status_code="rate_limited",
                model_id=None,
                policy_version=generation.version,
                started_at=started_at,
                request_size=request_size,
            )
            return
        generation_token = current_generation.set(generation)
        subject_token = current_subject.set(subject)
        event_status_token = current_event_status.set(None)
        event_model_token = current_event_model.set(None)
        response_status = 500

        async def capture_status(message: Message) -> None:
            nonlocal response_status
            if message.get("type") == "http.response.start":
                status = message.get("status")
                if isinstance(status, int):
                    response_status = status
            await send(message)

        try:
            await self._app(scope, receive, capture_status)
        finally:
            status_code = current_event_status.get()
            model_id = current_event_model.get()
            self._emit(
                request_id=request_id,
                route_key=route_key,
                status_code=(
                    status_code
                    if isinstance(status_code, str)
                    else f"http_{response_status}"
                ),
                model_id=model_id if isinstance(model_id, str) else None,
                policy_version=generation.version,
                started_at=started_at,
                request_size=request_size,
            )
            current_event_model.reset(event_model_token)
            current_event_status.reset(event_status_token)
            current_subject.reset(subject_token)
            current_generation.reset(generation_token)

    def _emit(
        self,
        *,
        request_id: str,
        route_key: str,
        status_code: str,
        model_id: str | None,
        policy_version: int | None,
        started_at: float,
        request_size: int,
    ) -> None:
        event_type = {
            "/assets": "gateway.assets",
            "/v1/responses": "gateway.responses",
            "/mcp": "gateway.mcp",
        }[route_key]
        emit_safely(
            self._event_sink,
            GatewayEvent(
                request_id=request_id,
                event_type=event_type,
                model_id=model_id,
                policy_version=policy_version,
                status_code=status_code,
                latency_bucket=latency_bucket(max(0.0, self._monotonic() - started_at)),
                size_bucket=size_bucket(request_size),
            ),
        )

    @staticmethod
    def _request_size(content_length: str | None) -> int:
        try:
            return max(0, int(content_length or "0"))
        except ValueError:
            return 0

    @staticmethod
    def _route_security(path: str) -> tuple[str, str]:
        if path == "/assets":
            return "assets:write", "/assets"
        if path == "/v1/responses":
            return "responses:invoke", "/v1/responses"
        return "mcp:invoke", "/mcp"


class RuntimeBoundMediaBridgeService(MediaBridgeService):
    """Resolve the same request-bound generation for every MCP tool call."""

    def __init__(self, runtime: VerifiedSnapshotRuntime) -> None:
        self._runtime = runtime

    def _current_service(self) -> MediaBridgeService:
        generation = current_generation.get() or self._runtime.current()
        return generation.service

    async def prepare_for_model(
        self,
        request: PrepareForModelRequest,
        *,
        tenant_id: str,
    ) -> PrepareForModelResult:
        return await self._current_service().prepare_for_model(request, tenant_id=tenant_id)

    async def extract_image_context(
        self,
        request: ExtractImageContextRequest,
        *,
        tenant_id: str,
    ) -> ExtractImageContextResult:
        return await self._current_service().extract_image_context(request, tenant_id=tenant_id)

    async def analyze_error_image(
        self,
        request: AnalyzeErrorImageRequest,
        *,
        tenant_id: str,
    ) -> AnalyzeErrorImageResult:
        return await self._current_service().analyze_error_image(request, tenant_id=tenant_id)


def _tenant_provider() -> str:
    subject = current_subject.get()
    if subject is None:
        raise RuntimeError("authenticated Data Plane subject is unavailable")
    return subject.tenant_id


def build_gateway_app(
    *,
    runtime: VerifiedSnapshotRuntime,
    asset_store: AssetStore,
    rate_limiter: CredentialRouteRateLimiter,
    max_upload_bytes: int = 2 * 1024 * 1024,
    max_responses_body_bytes: int = 4 * 1024 * 1024,
    event_sink: GatewayEventSink | None = None,
    request_id_factory: Callable[[], str] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> ASGIApp:
    if min(max_upload_bytes, max_responses_body_bytes) < 1:
        raise ValueError("Gateway body limits must be positive")

    async def upload_asset(request: Request) -> JSONResponse:
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > max_upload_bytes:
                return _error("upload_too_large", "Asset exceeded the upload limit.", 413)
        subject = current_subject.get()
        if subject is None or not body:
            return _error("upload_rejected", "Asset upload was rejected.", 400)
        try:
            asset_id = asset_store.put(
                tenant_id=subject.tenant_id,
                data=bytes(body),
                filename=request.headers.get("x-filename"),
                declared_mime=request.headers.get("content-type"),
            )
        except AssetAccessError:
            return _error("upload_rejected", "Asset upload was rejected.", 400)
        return JSONResponse({"asset_id": asset_id}, status_code=201)

    async def responses(request: Request) -> Response:
        content_type = request.headers.get("content-type", "").partition(";")[0].lower()
        if content_type != "application/json":
            return _error(
                "unsupported_content_type",
                "Responses request must use application/json.",
                415,
            )
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > max_responses_body_bytes:
                return _error(
                    "request_too_large",
                    "Responses request exceeded the configured limit.",
                    413,
                )
        try:
            payload = json.loads(bytes(body))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _error("invalid_json", "Responses request is not valid JSON.", 400)
        generation = current_generation.get()
        subject = current_subject.get()
        if generation is None or subject is None:
            return _error("gateway_unavailable", "Gateway request context is unavailable.", 503)
        result = await generation.transaction.invoke(payload, subject=subject)
        current_event_status.set(
            "completed" if result.status == "completed" else result.error.code
            if result.error is not None
            else "gateway_failed"
        )
        if result.gate_result is not None:
            current_event_model.set(result.gate_result.target_model)
        if result.status == "completed" and result.response is not None:
            return Response(
                content=result.response.body,
                status_code=result.response.status_code,
                media_type=result.response.content_type,
            )
        if result.error is None:
            return _error("gateway_failed", "Gateway failed safely.", 500)
        return _error(result.error.code, result.error.message, result.http_status)

    service = RuntimeBoundMediaBridgeService(runtime)
    server = build_mcp_server(service, tenant_provider=_tenant_provider)
    mcp_app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        max_request_body_size=4 * 1024 * 1024,
    )
    routes: list[Route | Mount] = [
        Route("/assets", upload_asset, methods=["POST"]),
        Route("/v1/responses", responses, methods=["POST"]),
        Mount("/", app=mcp_app),
    ]
    app = Starlette(routes=routes, lifespan=mcp_app.router.lifespan_context)
    app.router.redirect_slashes = False
    return DataPlaneAuthMiddleware(
        app,
        runtime=runtime,
        rate_limiter=rate_limiter,
        event_sink=event_sink or NullGatewayEventSink(),
        request_id_factory=request_id_factory or (lambda: uuid4().hex),
        monotonic=monotonic,
    )


__all__ = ["build_gateway_app", "current_generation", "current_subject"]
