"""Local Data runtime HTTP boundary for the personal installation."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from media_bridge_personal.local_state import LocalStateError, PersonalStateStore


def build_personal_data_app(*, state: PersonalStateStore) -> Starlette:
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

    return Starlette(
        routes=[
            Route("/status", status, methods=["GET"]),
            Route("/v1/responses", responses, methods=["POST"]),
        ]
    )
