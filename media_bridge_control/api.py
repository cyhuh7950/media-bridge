"""HTTPS-only Admin API skeleton with server-side session enforcement."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from media_bridge_control.bootstrap import (
    AuthenticationError,
    BootstrapError,
    ControlPlaneError,
    ControlPlaneService,
)
from media_bridge_control.schemas import BootstrapRequest, LoginRequest

Handler = Callable[[Request], Awaitable[Response]]


def _error(code: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code}}, status_code=status_code)


async def _json(request: Request, schema: type[Any]) -> Any:
    if request.headers.get("content-type", "").partition(";")[0].lower() != "application/json":
        raise ControlPlaneError("unsupported_content_type")
    body = await request.body()
    if len(body) > 64 * 1024:
        raise ControlPlaneError("request_too_large")
    try:
        return schema.model_validate_json(body)
    except (ValidationError, ValueError) as error:
        raise ControlPlaneError("invalid_request") from error


def build_control_app(
    *,
    service: ControlPlaneService,
    allowed_origin: str,
    allowed_host: str,
) -> Starlette:
    def secure_request(request: Request) -> Response | None:
        host = request.headers.get("host", "").partition(":")[0].lower()
        if request.url.scheme != "https":
            return _error("https_required", 400)
        if host != allowed_host.lower() or request.headers.get("origin") != allowed_origin:
            return _error("origin_rejected", 403)
        return None

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def bootstrap(request: Request) -> Response:
        if rejected := secure_request(request):
            return rejected
        raw_token = request.headers.get("x-bootstrap-token", "")
        try:
            body = await _json(request, BootstrapRequest)
            result = await run_in_threadpool(
                service.complete_bootstrap,
                token=raw_token,
                username=body.username,
                password=body.password,
            )
        except (BootstrapError, ControlPlaneError) as error:
            status = 409 if error.code == "already_initialized" else 400
            return _error(error.code, status)
        return JSONResponse(
            {
                "user_id": result.user_id,
                "role": result.role,
                "recovery_codes": result.recovery_codes,
            },
            status_code=201,
        )

    async def login(request: Request) -> Response:
        if rejected := secure_request(request):
            return rejected
        try:
            body = await _json(request, LoginRequest)
            client_host = request.client.host if request.client is not None else "unknown"
            result = await run_in_threadpool(
                service.login,
                username=body.username,
                password=body.password,
                client_key=client_host,
            )
        except AuthenticationError as error:
            status = 429 if error.code == "login_rate_limited" else 401
            return _error(error.code, status)
        except ControlPlaneError as error:
            return _error(error.code, 400)
        response = JSONResponse(
            {
                "username": result.username,
                "role": result.role,
                "csrf_token": result.csrf_token,
            }
        )
        response.set_cookie(
            "mb_admin_session",
            result.session_token,
            max_age=int(service.SESSION_TTL.total_seconds()),
            path="/admin/v1",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return response

    async def me(request: Request) -> Response:
        raw = request.cookies.get("mb_admin_session", "")
        try:
            principal = await run_in_threadpool(service.authenticate, raw)
        except AuthenticationError:
            return _error("unauthorized", 401)
        return JSONResponse({"username": principal.username, "role": principal.role})

    async def logout(request: Request) -> Response:
        if rejected := secure_request(request):
            return rejected
        raw = request.cookies.get("mb_admin_session", "")
        csrf = request.headers.get("x-csrf-token", "")
        if not csrf:
            return _error("csrf_rejected", 403)
        try:
            await run_in_threadpool(
                service.logout,
                session_token=raw,
                csrf_token=csrf,
            )
        except AuthenticationError as error:
            status = 403 if error.code == "csrf_rejected" else 401
            return _error(error.code, status)
        response = Response(status_code=204)
        response.delete_cookie("mb_admin_session", path="/admin/v1")
        return response

    return Starlette(
        routes=[
            Route("/admin/v1/health", health, methods=["GET"]),
            Route("/admin/v1/bootstrap", bootstrap, methods=["POST"]),
            Route("/admin/v1/auth/login", login, methods=["POST"]),
            Route("/admin/v1/auth/logout", logout, methods=["POST"]),
            Route("/admin/v1/me", me, methods=["GET"]),
        ]
    )
