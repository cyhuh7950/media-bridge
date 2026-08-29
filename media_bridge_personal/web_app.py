"""Loopback first-run and settings HTTP surface for personal installs."""

from __future__ import annotations

import html
import json
import re
from urllib.parse import parse_qs, urlsplit

from starlette.applications import Starlette
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from media_bridge_personal.local_state import LocalStateError, PersonalStateStore

_DEFAULT_RPM = 2_000
_DEFAULT_TPM = 750_000
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")


def _connection_metadata(payload: object) -> dict[str, str] | None:
    if not isinstance(payload, dict):
        raise ValueError
    names = (
        "opencodex_endpoint",
        "solar_endpoint",
        "solar_model",
        "solar_credential_env",
    )
    if not any(name in payload for name in names):
        return None
    if not all(name in payload for name in names):
        raise ValueError
    opencodex = str(payload["opencodex_endpoint"]).strip()
    solar = str(payload["solar_endpoint"]).strip()
    model = str(payload["solar_model"]).strip()
    credential_env = str(payload["solar_credential_env"]).strip()
    opencodex_url = urlsplit(opencodex)
    solar_url = urlsplit(solar)
    if (
        opencodex_url.scheme not in {"http", "https"}
        or not opencodex_url.hostname
        or opencodex_url.username is not None
        or opencodex_url.password is not None
        or opencodex_url.query
        or opencodex_url.fragment
        or solar_url.scheme != "https"
        or not solar_url.hostname
        or solar_url.username is not None
        or solar_url.password is not None
        or solar_url.query
        or solar_url.fragment
        or not re.fullmatch(r"[a-z0-9][a-z0-9._:/-]{0,127}", model)
        or _ENV_NAME.fullmatch(credential_env) is None
    ):
        raise ValueError
    result = {
        "opencodex_endpoint": opencodex,
        "solar_endpoint": solar,
        "solar_model": model,
        "solar_credential_env": credential_env,
    }
    optional_groups = (
        ("ocr_endpoint", "ocr_credential_env"),
        ("vision_endpoint", "vision_model", "vision_credential_env"),
    )
    for group in optional_groups:
        values = [str(payload.get(name, "")).strip() for name in group]
        if not any(values):
            continue
        if not all(values):
            raise ValueError
        endpoint = values[0]
        endpoint_url = urlsplit(endpoint)
        if (
            endpoint_url.scheme != "https"
            or not endpoint_url.hostname
            or endpoint_url.username is not None
            or endpoint_url.password is not None
            or endpoint_url.query
            or endpoint_url.fragment
            or _ENV_NAME.fullmatch(str(payload[group[-1]]).strip()) is None
        ):
            raise ValueError
        result[group[0]] = endpoint
        if len(group) == 2:
            result[group[1]] = str(payload[group[1]]).strip()
        else:
            vision_model = str(payload["vision_model"]).strip()
            if not re.fullmatch(r"[a-z0-9][a-z0-9._:/-]{0,127}", vision_model):
                raise ValueError
            result["vision_model"] = vision_model
            result["vision_credential_env"] = str(payload["vision_credential_env"]).strip()
    return result


def _page(snapshot: dict[str, object]) -> str:
    rate = snapshot.get("rate")
    rates = rate if isinstance(rate, dict) else {}
    connection = snapshot.get("connection")
    connection_values = connection if isinstance(connection, dict) else {}
    rpm = rates.get("rpm", _DEFAULT_RPM)
    tpm = rates.get("tpm", _DEFAULT_TPM)
    opencodex_endpoint = str(connection_values.get("opencodex_endpoint", ""))
    solar_endpoint = str(
        connection_values.get("solar_endpoint", "https://api.upstage.ai/v1/chat/completions")
    )
    solar_model = str(connection_values.get("solar_model", "solar-pro4"))
    solar_credential_env = str(connection_values.get("solar_credential_env", "SOLAR_API_KEY"))
    ocr_endpoint = str(connection_values.get("ocr_endpoint", ""))
    ocr_credential_env = str(connection_values.get("ocr_credential_env", ""))
    vision_endpoint = str(connection_values.get("vision_endpoint", ""))
    vision_model = str(connection_values.get("vision_model", ""))
    vision_credential_env = str(connection_values.get("vision_credential_env", ""))
    safe_opencodex_endpoint = html.escape(opencodex_endpoint, quote=True)
    safe_solar_endpoint = html.escape(solar_endpoint, quote=True)
    safe_solar_model = html.escape(solar_model, quote=True)
    safe_credential_env = html.escape(solar_credential_env, quote=True)
    safe_ocr_endpoint = html.escape(ocr_endpoint, quote=True)
    safe_ocr_credential_env = html.escape(ocr_credential_env, quote=True)
    safe_vision_endpoint = html.escape(vision_endpoint, quote=True)
    safe_vision_model = html.escape(vision_model, quote=True)
    safe_vision_credential_env = html.escape(vision_credential_env, quote=True)
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>Media Bridge 설정</title></head>
<body><main><h1>Media Bridge 시작하기</h1>
<p>로컬 전용 설정입니다. 별도 계정이나 외부 데이터베이스가 필요하지 않습니다.</p>
<form method="post" action="/settings">
<label>OpenCodex endpoint
<input name="opencodex_endpoint" type="url" value="{safe_opencodex_endpoint}"></label>
<label>Solar endpoint
<input name="solar_endpoint" type="url" value="{safe_solar_endpoint}"></label>
<label>Solar model
<input name="solar_model" type="text" value="{safe_solar_model}"></label>
<label>Solar credential 환경변수 이름
<input name="solar_credential_env" type="text" value="{safe_credential_env}"></label>
<p>API key 원문은 입력하지 않습니다. 지정한 환경변수 또는 OS credential reference를 사용합니다.</p>
<label>OCR endpoint
<input name="ocr_endpoint" type="url" value="{safe_ocr_endpoint}"></label>
<label>OCR credential 환경변수 이름
<input name="ocr_credential_env" type="text" value="{safe_ocr_credential_env}"></label>
<label>Vision endpoint
<input name="vision_endpoint" type="url" value="{safe_vision_endpoint}"></label>
<label>Vision model
<input name="vision_model" type="text" value="{safe_vision_model}"></label>
<label>Vision credential 환경변수 이름
<input name="vision_credential_env" type="text" value="{safe_vision_credential_env}"></label>
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
            connection = _connection_metadata(payload)
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
                **({"connection": connection} if connection is not None else {}),
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
