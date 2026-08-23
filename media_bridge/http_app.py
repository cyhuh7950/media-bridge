"""Authenticated Streamable HTTP MCP and bounded asset-upload ASGI app."""

from __future__ import annotations

import contextvars
import secrets
from typing import Any

from mcp.server import MCPServer
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from media_bridge.assets import AssetAccessError, AssetStore, validate_tenant_id
from media_bridge.backends import load_secret

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
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        expected = f"Bearer {self._token}"
        if not secrets.compare_digest(headers.get("authorization", ""), expected):
            await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
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
    auth_value_env: str | None = None,
    auth_file_env: str | None = None,
) -> ASGIApp:
    service_token = load_secret(
        auth_value_env or "MEDIA_BRIDGE_SERVICE_TOKEN",
        auth_file_env or "MEDIA_BRIDGE_SERVICE_TOKEN_FILE",
    )

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

    mcp_app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        max_request_body_size=4 * 1024 * 1024,
    )
    app = Starlette(
        routes=[
            Route("/assets", upload_asset, methods=["POST"]),
            Mount("/", app=mcp_app),
        ],
        lifespan=mcp_app.router.lifespan_context,
    )
    return BearerTenantMiddleware(app, token=service_token)
