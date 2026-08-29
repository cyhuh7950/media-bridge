"""Loopback first-run and settings HTTP surface for personal installs."""

from __future__ import annotations

import json
from urllib.parse import parse_qs

from starlette.applications import Starlette
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from media_bridge_personal.local_state import LocalStateError, PersonalStateStore

_DEFAULT_RPM = 2_000
_DEFAULT_TPM = 750_000


def _page(snapshot: dict[str, object]) -> str:
    rate = snapshot.get("rate")
    rates = rate if isinstance(rate, dict) else {}
    rpm = rates.get("rpm", _DEFAULT_RPM)
    tpm = rates.get("tpm", _DEFAULT_TPM)
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>Media Bridge 설정</title></head>
<body><main><h1>Media Bridge 시작하기</h1>
<p>로컬 전용 설정입니다. 별도 계정이나 외부 데이터베이스가 필요하지 않습니다.</p>
<form method="post" action="/settings">
<label>Solar RPM <input name="solar_rpm" type="number" min="1" value="{rpm}"></label>
<label>Solar TPM <input name="solar_tpm" type="number" min="1" value="{tpm}"></label>
<button type="submit">설정 저장</button></form>
<p>인식이 충분하지 않은 화면은 Solar로 보내지 않고 호출 0회로 차단합니다.</p>
</main></body></html>"""


def build_personal_web_app(*, state: PersonalStateStore) -> TrustedHostMiddleware:
    async def home(_: Request) -> HTMLResponse:
        try:
            snapshot = state.load_last_known_good()
        except LocalStateError:
            snapshot = {"version": 1, "rate": {"rpm": _DEFAULT_RPM, "tpm": _DEFAULT_TPM}}
        return HTMLResponse(_page(snapshot))

    async def settings(request: Request) -> JSONResponse:
        try:
            content_type = request.headers.get("content-type", "").partition(";")[0]
            if content_type == "application/json":
                payload = await request.json()
            elif content_type == "application/x-www-form-urlencoded":
                raw = (await request.body()).decode("utf-8")
                payload = {key: values[-1] for key, values in parse_qs(raw).items() if values}
            else:
                raise ValueError
            rpm = int(payload["solar_rpm"])
            tpm = int(payload["solar_tpm"])
            if rpm < 1 or tpm < 1:
                raise ValueError
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return JSONResponse({"reason_code": "invalid_rate_profile"}, status_code=400)
        try:
            current = state.load_last_known_good()
        except LocalStateError:
            current = {"version": 0, "mode": "first_run"}
        state.publish(
            {
                **current,
                "version": int(current.get("version", 0)) + 1,
                "mode": "configured",
                "rate": {"rpm": rpm, "tpm": tpm},
            }
        )
        return JSONResponse({"status": "saved", "rate": {"rpm": rpm, "tpm": tpm}})

    return TrustedHostMiddleware(
        Starlette(
            routes=[
                Route("/", home, methods=["GET"]),
                Route("/settings", settings, methods=["POST"]),
            ]
        ),
        allowed_hosts=["127.0.0.1", "localhost"],
    )
