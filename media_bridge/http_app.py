"""Authenticated Streamable HTTP MCP and bounded asset-upload ASGI app."""

from __future__ import annotations

import contextvars
import json
import secrets
from datetime import UTC, datetime
from typing import Any

from mcp.server import MCPServer
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from media_bridge.assets import AssetAccessError, AssetStore, validate_tenant_id
from media_bridge.backends import load_secret
from media_bridge.capabilities import CapabilityRegistry
from media_bridge.openai_chat import (
    ChatNormalizationError,
    chat_request_to_responses,
    chat_response_from_responses,
    chat_stream_from_responses,
)
from media_bridge.responses_gateway import ResponsesIngressGateway

current_tenant: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "media_bridge_tenant",
    default=None,
)


class BearerTenantMiddleware:
    def __init__(self, app: ASGIApp, *, token: str) -> None:
        self._app = app
        self._token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        if scope.get("path") == "/health":
            await self._app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        expected = f"Bearer {self._token}"
        if not secrets.compare_digest(headers.get("authorization", ""), expected):
            await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
            return
        if scope.get("method") == "GET" and scope.get("path") == "/v1/models":
            await self._app(scope, receive, send)
            return
        tenant_id = headers.get("x-media-bridge-tenant", "")
        try:
            validate_tenant_id(tenant_id)
        except AssetAccessError:
            await JSONResponse({"error": "invalid_tenant"}, status_code=400)(scope, receive, send)
            return
        token = current_tenant.set(tenant_id)
        try:
            await self._app(scope, receive, send)
        finally:
            current_tenant.reset(token)


def build_http_app(
    *,
    server: MCPServer[Any],
    asset_store: AssetStore,
    max_upload_bytes: int = 2 * 1024 * 1024,
    responses_gateway: ResponsesIngressGateway | None = None,
    model_registry: CapabilityRegistry | None = None,
    max_responses_body_bytes: int = 4 * 1024 * 1024,
    auth_value_env: str | None = None,
    auth_file_env: str | None = None,
) -> ASGIApp:
    service_token = load_secret(
        auth_value_env or "MEDIA_BRIDGE_SERVICE_TOKEN",
        auth_file_env or "MEDIA_BRIDGE_SERVICE_TOKEN_FILE",
    )
    if min(max_upload_bytes, max_responses_body_bytes) < 1:
        raise ValueError("HTTP body limits must be positive")

    def response_error(code: str, message: str, status_code: int) -> JSONResponse:
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

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def upload_asset(request: Request) -> JSONResponse:
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > max_upload_bytes:
                return JSONResponse({"error": "upload_too_large"}, status_code=413)
        tenant_id = current_tenant.get()
        if tenant_id is None:
            return JSONResponse({"error": "invalid_tenant"}, status_code=400)
        try:
            asset_id = asset_store.put(
                tenant_id=tenant_id,
                data=bytes(body),
                filename=request.headers.get("x-filename"),
                declared_mime=request.headers.get("content-type"),
            )
        except AssetAccessError:
            return JSONResponse({"error": "upload_rejected"}, status_code=400)
        return JSONResponse({"asset_id": asset_id}, status_code=201)

    async def responses(request: Request) -> Response:
        content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
        if content_type != "application/json":
            return response_error(
                "unsupported_content_type",
                "Responses request must use application/json.",
                415,
            )
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > max_responses_body_bytes:
                return response_error(
                    "request_too_large",
                    "Responses request exceeded the configured limit.",
                    413,
                )
        try:
            payload = json.loads(bytes(body))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return response_error("invalid_json", "Responses request is not valid JSON.", 400)
        tenant_id = current_tenant.get()
        if tenant_id is None or responses_gateway is None:
            return response_error("gateway_unavailable", "Responses gateway is unavailable.", 503)
        result = await responses_gateway.invoke(payload, tenant_id=tenant_id)
        if result.response is not None and result.status == "completed":
            return Response(
                content=result.response.body,
                status_code=result.response.status_code,
                media_type=result.response.content_type,
            )
        error = result.error
        if error is None:
            return response_error(
                "gateway_failed",
                "Responses gateway failed safely.",
                500,
            )
        return response_error(error.code, error.message, result.http_status)

    async def chat_completions(request: Request) -> Response:
        content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
        if content_type != "application/json":
            return response_error(
                "unsupported_content_type",
                "Chat Completions request must use application/json.",
                415,
            )
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > max_responses_body_bytes:
                return response_error(
                    "request_too_large",
                    "Chat Completions request exceeded the configured limit.",
                    413,
                )
        try:
            chat_payload = json.loads(bytes(body))
            responses_payload = chat_request_to_responses(chat_payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return response_error(
                "invalid_json",
                "Chat Completions request is not valid JSON.",
                400,
            )
        except ChatNormalizationError as normalization_error:
            return response_error(
                normalization_error.code,
                normalization_error.safe_message,
                400,
            )
        tenant_id = current_tenant.get()
        if tenant_id is None or responses_gateway is None:
            return response_error("gateway_unavailable", "Responses gateway is unavailable.", 503)
        result = await responses_gateway.invoke(responses_payload, tenant_id=tenant_id)
        if result.response is not None and result.status == "completed":
            model = responses_payload["model"]
            if result.response.stream is not None:
                return StreamingResponse(
                    chat_stream_from_responses(
                        result.response.stream,
                        response_id=result.response.response_id,
                        request_model=model,
                    ),
                    status_code=result.response.status_code,
                    media_type="text/event-stream",
                )
            try:
                converted = chat_response_from_responses(
                    result.response.body,
                    request_model=model,
                )
            except ValueError:
                return response_error(
                    "invalid_downstream_response",
                    "Responses gateway returned an invalid response.",
                    502,
                )
            return Response(
                content=converted,
                status_code=result.response.status_code,
                media_type="application/json",
            )
        gateway_error = result.error
        if gateway_error is None:
            return response_error("gateway_failed", "Responses gateway failed safely.", 500)
        return response_error(gateway_error.code, gateway_error.message, result.http_status)

    async def models(_request: Request) -> JSONResponse:
        if model_registry is None:
            return response_error(
                "model_catalog_unavailable",
                "Model catalog is unavailable.",
                503,
            )
        data = [
            {
                "id": capability.model_id,
                "object": "model",
                "created": int(datetime.now(UTC).timestamp()),
                "owned_by": "media-bridge",
            }
            for capability in model_registry.available()
        ]
        return JSONResponse({"object": "list", "data": data})

    mcp_app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        max_request_body_size=4 * 1024 * 1024,
    )
    routes: list[Route | Mount] = [
        Route("/health", health, methods=["GET"]),
        Route("/assets", upload_asset, methods=["POST"]),
    ]
    if model_registry is not None:
        routes.append(Route("/v1/models", models, methods=["GET"]))
    if responses_gateway is not None:
        routes.append(Route("/v1/responses", responses, methods=["POST"]))
        routes.append(Route("/v1/chat/completions", chat_completions, methods=["POST"]))
    routes.append(Mount("/", app=mcp_app))
    app = Starlette(
        routes=routes,
        lifespan=mcp_app.router.lifespan_context,
    )
    return BearerTenantMiddleware(app, token=service_token)
