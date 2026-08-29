"""Local Data runtime HTTP boundary for the personal installation."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from media_bridge_personal.local_state import LocalStateError, PersonalStateStore


def build_personal_data_app(
    *, state: PersonalStateStore, responses_app: ASGIApp | None = None
) -> ASGIApp:
    async def status(_: Request) -> JSONResponse:
        try:
            snapshot = state.load_last_known_good()
        except LocalStateError:
            return JSONResponse(
                {"status": "blocked", "reason_code": "local_state_unavailable"},
                status_code=503,
            )
        return JSONResponse({"status": "ready", "snapshot_version": snapshot["version"]})

    async def responses(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "type": "media_bridge_error",
                    "code": "gateway_unavailable",
                    "message": "Media Bridge response routing is not configured.",
                }
            },
            status_code=503,
        )

    personal_app = Starlette(
        routes=[
            Route("/status", status, methods=["GET"]),
            Route("/v1/responses", responses, methods=["POST"]),
        ]
    )
    if responses_app is None:
        return personal_app

    async def routed_app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") == "/v1/responses":
            await responses_app(scope, receive, send)
            return
        await personal_app(scope, receive, send)

    return routed_app
