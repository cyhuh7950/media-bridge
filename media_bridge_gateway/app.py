"""Authenticated product Data Plane app for Responses, MCP, and assets."""

from __future__ import annotations

import contextvars
import json

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

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
    ) -> None:
        self._app = app
        self._runtime = runtime
        self._rate_limiter = rate_limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        required_scope, route_key = self._route_security(path)
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
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
            return
        except CredentialAuthenticationError as error:
            status_code = 403 if error.code == "admin_session_not_allowed" else 401
            await _error(error.code, "Data-plane credential was rejected.", status_code)(
                scope,
                receive,
                send,
            )
            return
        if not self._rate_limiter.allow(subject.credential_selector, route_key):
            await _error("rate_limited", "Data-plane rate limit was exceeded.", 429)(
                scope,
                receive,
                send,
            )
            return
        generation_token = current_generation.set(generation)
        subject_token = current_subject.set(subject)
        try:
            await self._app(scope, receive, send)
        finally:
            current_subject.reset(subject_token)
            current_generation.reset(generation_token)

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
    return DataPlaneAuthMiddleware(app, runtime=runtime, rate_limiter=rate_limiter)


__all__ = ["build_gateway_app", "current_generation", "current_subject"]
