"""Authenticated ASGI boundary for router pre-upstream hooks."""

from __future__ import annotations

import hashlib
import hmac

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from media_bridge_adapters.contracts import PreUpstreamRequest
from media_bridge_adapters.service import PreUpstreamService


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def build_adapter_app(
    service: PreUpstreamService,
    *,
    credential_digest: str,
    max_request_bytes: int = 4 * 1024 * 1024,
) -> Starlette:
    invalid_digest = len(credential_digest) != 64 or any(
        char not in "0123456789abcdef" for char in credential_digest
    )
    if invalid_digest:
        raise ValueError("Adapter credential digest is invalid")
    if max_request_bytes < 1:
        raise ValueError("Adapter request limit must be positive")

    async def prepare(request: Request) -> Response:
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer ") or "," in authorization:
            return _error("authentication_required", "Adapter credential is required.", 401)
        credential = authorization.removeprefix("Bearer ")
        actual = hashlib.sha256(credential.encode()).hexdigest()
        if not hmac.compare_digest(actual, credential_digest):
            return _error("authentication_failed", "Adapter credential is invalid.", 401)
        if request.headers.get("content-type", "").partition(";")[0] != "application/json":
            return _error(
                "unsupported_content_type",
                "Adapter request must use application/json.",
                415,
            )
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > max_request_bytes:
                return _error("request_too_large", "Adapter request exceeded the limit.", 413)
        try:
            payload = PreUpstreamRequest.model_validate_json(bytes(body))
        except (ValidationError, ValueError):
            return _error("invalid_request", "Adapter request is invalid.", 400)
        result = await service.prepare(payload)
        status = 200 if result.status != "blocked" else 422
        return JSONResponse(result.model_dump(mode="json"), status_code=status)

    app = Starlette(routes=[Route("/adapter/v1/pre-upstream", prepare, methods=["POST"])])
    app.router.redirect_slashes = False
    return app
