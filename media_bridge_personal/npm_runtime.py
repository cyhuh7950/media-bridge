"""Single-user npm runtime composed from the shared Media Bridge Core."""

from __future__ import annotations

import asyncio
import html
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route
from starlette.types import ASGIApp

from media_bridge.acquisition import MediaAcquirer
from media_bridge.assets import AssetStore
from media_bridge.backends import BackendStatus, OcrBackend, OcrResult, VisionResult
from media_bridge.capabilities import CapabilityRegistry, ModelCapability
from media_bridge.gate import PreRequestGate
from media_bridge.pdf_pipeline import PdfiumPageRenderer
from media_bridge.receipts import GateReceiptSigner
from media_bridge_gateway.contracts import DataPlaneSubject, GatewayResponse, ResponsesDownstream
from media_bridge_gateway.state import GatewayStateStore
from media_bridge_gateway.transaction import GatewayTransaction
from media_bridge_personal.solar_responses import SolarResponsesDownstream


class PersonalRuntimeConfigurationError(RuntimeError):
    """Raised before listening when personal runtime configuration is unsafe."""


class _ClosableDownstream(ResponsesDownstream, Protocol):
    async def close(self) -> None: ...


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _document_text(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    direct = payload.get("text")
    if isinstance(direct, str):
        return direct.strip()
    pages = payload.get("pages")
    if isinstance(pages, list):
        page_text = "\n".join(
            str(page["text"]).strip()
            for page in pages
            if isinstance(page, dict) and isinstance(page.get("text"), str)
        ).strip()
        if page_text:
            return page_text
    content = payload.get("content")
    if not isinstance(content, dict):
        return None
    for key in ("markdown", "text"):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    html = content.get("html")
    if not isinstance(html, str) or not html.strip():
        return None
    parser = _HtmlTextExtractor()
    parser.feed(html)
    return "\n".join(parser.parts).strip()


class UpstageDocumentParseBackend:
    """Upstage Document Parse OCR boundary for the personal runtime."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key_env: str,
        client: httpx.AsyncClient,
    ) -> None:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != "/v1/document-digitization"
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Document Parse endpoint is invalid")
        self._endpoint = endpoint
        self._api_key_env = api_key_env
        self._client = client

    async def extract(
        self,
        *,
        data: bytes,
        mime_type: str,
        filename: str | None,
    ) -> OcrResult:
        secret = os.environ.get(self._api_key_env, "").strip()
        if not secret:
            return OcrResult(BackendStatus.FAILURE, error_code="configuration")
        try:
            response = await self._client.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {secret}"},
                files={"document": (filename or "image", data, mime_type)},
                data={"ocr": "force", "model": "document-parse"},
            )
        except httpx.TimeoutException:
            return OcrResult(BackendStatus.FAILURE, error_code="timeout")
        except httpx.RequestError:
            return OcrResult(BackendStatus.FAILURE, error_code="transport")
        if response.status_code >= 400:
            code = (
                "authentication"
                if response.status_code in {401, 403}
                else "rate_limit"
                if response.status_code == 429
                else "upstream_http"
            )
            return OcrResult(BackendStatus.FAILURE, error_code=code)
        try:
            text = _document_text(response.json())
        except ValueError:
            return OcrResult(BackendStatus.FAILURE, error_code="invalid_response")
        if text is None:
            return OcrResult(BackendStatus.FAILURE, error_code="invalid_response")
        if not text:
            return OcrResult(BackendStatus.NO_TEXT)
        return OcrResult(BackendStatus.SUCCESS, text=text)


class _OcrOnlyDescriptionBackend:
    async def describe(self, **_kwargs: Any) -> VisionResult:
        return VisionResult(
            BackendStatus.SUCCESS,
            description="Document Parse OCR context; no original media is forwarded.",
        )


_ENV_REFERENCE = re.compile(r"[A-Z_][A-Z0-9_]{0,127}")
_SETTINGS_RESPONSE_HEADERS = {
    "cache-control": "no-store",
    "content-security-policy": (
        "default-src 'self'; style-src 'unsafe-inline'; object-src 'none'; "
        "frame-ancestors 'none'"
    ),
}


def _load_npm_config(path: Path) -> dict[str, Any]:
    try:
        status = path.lstat()
        if path.is_symlink() or not path.is_file() or status.st_size > 65_536:
            raise PersonalRuntimeConfigurationError("npm config file is invalid")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise PersonalRuntimeConfigurationError("npm config file is invalid") from error
    if not isinstance(payload, dict):
        raise PersonalRuntimeConfigurationError("npm config file is invalid")
    return payload


def _validated_settings(payload: dict[str, str], current: dict[str, Any]) -> dict[str, Any]:
    try:
        port = int(payload["port"])
        max_bytes = int(payload["max_bytes"])
        opencodex_base_url = payload["opencodex_base_url"].strip()
        solar_model = payload["solar_model"].strip()
        solar_endpoint = payload["solar_endpoint"].strip()
        solar_api_key_env = payload["solar_api_key_env"].strip()
        ocr_endpoint = payload["ocr_endpoint"].strip()
        ocr_api_key_env = payload["ocr_api_key_env"].strip()
    except (KeyError, TypeError, ValueError) as error:
        raise PersonalRuntimeConfigurationError("settings are invalid") from error
    if not 1 <= port <= 65_535 or max_bytes < 1:
        raise PersonalRuntimeConfigurationError("settings are invalid")
    for endpoint, loopback_allowed in (
        (opencodex_base_url, True),
        (solar_endpoint, False),
        (ocr_endpoint, False),
    ):
        parsed = urlsplit(endpoint)
        loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if (
            parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or (
                parsed.scheme != "https"
                and not (loopback_allowed and parsed.scheme == "http" and loopback)
            )
        ):
            raise PersonalRuntimeConfigurationError("settings endpoint is invalid")
    if (
        not solar_model
        or _ENV_REFERENCE.fullmatch(solar_api_key_env) is None
        or _ENV_REFERENCE.fullmatch(ocr_api_key_env) is None
    ):
        raise PersonalRuntimeConfigurationError("settings are invalid")
    result = dict(current)
    result.update({"runtimeMode": "personal", "host": "127.0.0.1", "port": port})
    result["opencodex"] = {"baseUrl": opencodex_base_url}
    result["solar"] = {
        "model": solar_model,
        "endpoint": solar_endpoint,
        "apiKeyEnv": solar_api_key_env,
    }
    result["ocr"] = {
        "model": "document-parse",
        "endpoint": ocr_endpoint,
        "apiKeyEnv": ocr_api_key_env,
    }
    result["conversion"] = {
        "maxBytes": max_bytes,
        "ocrEnabled": payload.get("ocr_enabled") == "true",
        "visionEnabled": payload.get("vision_enabled") == "true",
    }
    result["failurePolicy"] = {
        "blockSolarOnPreparationFailure": payload.get("block_solar_on_failure") == "true"
    }
    return result


def _write_npm_config(path: Path, config: dict[str, Any]) -> None:
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(config, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            path.chmod(0o600)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        finally:
            raise


def _settings_page(config: dict[str, Any], *, saved: bool = False) -> str:
    def section(name: str) -> dict[str, Any]:
        current = config.get(name)
        return current if isinstance(current, dict) else {}

    opencodex = section("opencodex")
    solar = section("solar")
    ocr = section("ocr")
    conversion = section("conversion")
    policy = section("failurePolicy")

    def input_field(label: str, name: str, item: object, attributes: str = "") -> str:
        safe_value = html.escape(str(item), quote=True)
        return (
            f'<label>{label}<input name="{name}" {attributes} '
            f'required value="{safe_value}"></label>'
        )

    def checkbox(label: str, name: str, item: object) -> str:
        selected = " checked" if item is True else ""
        return f'<label><input name="{name}" type="checkbox" value="true"{selected}>{label}</label>'

    notice = ""
    if saved:
        notice = (
            '<p role="status">설정을 저장했습니다. 적용하려면 '
            '<code>mb service restart</code>를 실행하세요.</p>'
        )
    fields = [
        input_field(
            "Media Bridge 포트",
            "port",
            config.get("port", 8642),
            'type="number" min="1" max="65535"',
        ),
        input_field(
            "OpenCodex에 설정할 Media Bridge 주소",
            "opencodex_base_url",
            opencodex.get("baseUrl", "http://127.0.0.1:8642/v1"),
            'type="url"',
        ),
        input_field("Solar 모델", "solar_model", solar.get("model", "solar-pro4")),
        input_field(
            "Solar endpoint",
            "solar_endpoint",
            solar.get("endpoint", "https://api.upstage.ai/v1/chat/completions"),
            'type="url"',
        ),
        input_field(
            "Solar API key 환경변수 이름",
            "solar_api_key_env",
            solar.get("apiKeyEnv", "SOLAR_API_KEY"),
        ),
        input_field(
            "Document Parse endpoint",
            "ocr_endpoint",
            ocr.get("endpoint", "https://api.upstage.ai/v1/document-digitization"),
            'type="url"',
        ),
        input_field(
            "Document Parse API key 환경변수 이름",
            "ocr_api_key_env",
            ocr.get("apiKeyEnv", "SOLAR_API_KEY"),
        ),
        input_field(
            "변환 최대 크기(bytes)",
            "max_bytes",
            conversion.get("maxBytes", 8_388_608),
            'type="number" min="1"',
        ),
        checkbox("OCR 변환 사용", "ocr_enabled", conversion.get("ocrEnabled")),
        checkbox("Vision 보강 사용", "vision_enabled", conversion.get("visionEnabled")),
        checkbox(
            "변환 실패 시 Solar 전송 차단",
            "block_solar_on_failure",
            policy.get("blockSolarOnPreparationFailure"),
        ),
    ]
    return "\n".join(
        [
            '<!doctype html><html lang="ko"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            "<title>Media Bridge 설정</title>",
            "<style>body{font:16px system-ui;max-width:720px;margin:2rem auto;padding:0 1rem}",
            "label{display:block;margin:.8rem 0}",
            "input{display:block;width:100%;padding:.5rem;box-sizing:border-box}</style>",
            f"</head><body><main><h1>Media Bridge 설정</h1>{notice}",
            "<p>API key 원문은 저장하지 않습니다. 실행 환경변수의 이름만 설정합니다.</p>",
            '<form method="post" action="/settings">',
            *fields,
            '<button type="submit">설정 저장</button></form></main></body></html>',
        ]
    )


@dataclass(slots=True)
class PersonalRuntime:
    transaction: GatewayTransaction
    asset_store: AssetStore
    downstream: _ClosableDownstream
    clients: tuple[httpx.AsyncClient, ...] = field(default_factory=tuple)

    async def invoke(self, payload: object) -> GatewayResponse | tuple[int, dict[str, Any]]:
        subject = DataPlaneSubject(
            credential_selector="personal",
            tenant_id="personal",
            scopes=frozenset({"responses:invoke"}),
        )
        result = await self.transaction.invoke(payload, subject=subject)
        if result.status == "completed" and result.response is not None:
            return result.response
        error = result.error
        status = 422 if result.gate_result is not None else result.http_status
        return (
            status,
            {
                "error": {
                    "type": "media_bridge_error",
                    "code": error.code if error is not None else "personal_runtime_failed",
                    "message": (
                        error.message
                        if error is not None
                        else "Media Bridge personal runtime failed safely."
                    ),
                }
            },
        )

    async def close(self) -> None:
        self.transaction.clear_state()
        self.asset_store.clear()
        await self.downstream.close()
        for client in self.clients:
            await client.aclose()


def build_personal_runtime(
    *,
    model: str,
    asset_root: Path,
    receipt_secret: bytes,
    ocr_backend: OcrBackend,
    downstream_factory: Callable[[GateReceiptSigner], _ClosableDownstream],
    clients: tuple[httpx.AsyncClient, ...] = (),
) -> PersonalRuntime:
    if not model.strip():
        raise ValueError("personal model is required")
    signer = GateReceiptSigner(secret=receipt_secret)
    asset_store = AssetStore(asset_root)
    registry = CapabilityRegistry(
        [
            ModelCapability(
                model_id=model,
                input_modalities={"text"},
                expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            )
        ],
        version="npm-personal-1",
    )
    gate = PreRequestGate(
        registry=registry,
        acquirer=MediaAcquirer(asset_store=asset_store),
        ocr_backend=ocr_backend,
        vision_backend=_OcrOnlyDescriptionBackend(),
        receipt_signer=signer,
        pdf_renderer=PdfiumPageRenderer(),
    )
    downstream = downstream_factory(signer)
    transaction = GatewayTransaction(
        gate=gate,
        downstream=downstream,
        receipt_signer=signer,
        state_store=GatewayStateStore(),
    )
    return PersonalRuntime(
        transaction=transaction,
        asset_store=asset_store,
        downstream=downstream,
        clients=clients,
    )


def build_personal_app(
    runtime: PersonalRuntime,
    *,
    max_request_bytes: int = 8 * 1024 * 1024,
    config_file: Path | None = None,
) -> ASGIApp:
    if max_request_bytes < 1:
        raise ValueError("personal request limit must be positive")

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "mode": "personal"})

    async def settings_home(_request: Request) -> HTMLResponse:
        if config_file is None:
            return HTMLResponse("Media Bridge settings are unavailable.", status_code=404)
        return HTMLResponse(
            _settings_page(_load_npm_config(config_file)),
            headers=_SETTINGS_RESPONSE_HEADERS,
        )

    async def save_settings(request: Request) -> HTMLResponse:
        if config_file is None:
            return HTMLResponse("Media Bridge settings are unavailable.", status_code=404)
        expected_origins = {
            f"http://127.0.0.1:{request.url.port or 80}",
            f"http://localhost:{request.url.port or 80}",
        }
        if request.headers.get("origin") not in expected_origins:
            return HTMLResponse("Forbidden", status_code=403)
        content_type = request.headers.get("content-type", "").partition(";")[0]
        if content_type != "application/x-www-form-urlencoded":
            return HTMLResponse("Unsupported Media Type", status_code=415)
        try:
            parsed = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
            payload = {name: values[-1] for name, values in parsed.items() if values}
            config = _validated_settings(payload, _load_npm_config(config_file))
            _write_npm_config(config_file, config)
        except (UnicodeDecodeError, PersonalRuntimeConfigurationError):
            return HTMLResponse("설정값이 올바르지 않습니다.", status_code=400)
        return HTMLResponse(
            _settings_page(config, saved=True),
            headers=_SETTINGS_RESPONSE_HEADERS,
        )

    async def responses(request: Request) -> Response:
        content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
        if content_type != "application/json":
            return JSONResponse(
                {"error": {"type": "media_bridge_error", "code": "unsupported_content_type"}},
                status_code=415,
            )
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > max_request_bytes:
                return JSONResponse(
                    {"error": {"type": "media_bridge_error", "code": "request_too_large"}},
                    status_code=413,
                )
        try:
            payload = json.loads(bytes(body))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JSONResponse(
                {"error": {"type": "media_bridge_error", "code": "invalid_json"}},
                status_code=400,
            )
        result = await runtime.invoke(payload)
        if isinstance(result, tuple):
            status, error = result
            return JSONResponse(error, status_code=status)
        if result.stream is not None:
            return StreamingResponse(
                result.stream,
                status_code=result.status_code,
                media_type=result.content_type,
            )
        return Response(
            result.body,
            status_code=result.status_code,
            media_type=result.content_type,
        )

    return Starlette(
        routes=[
            Route("/", settings_home, methods=["GET"]),
            Route("/settings", save_settings, methods=["POST"]),
            Route("/health", health, methods=["GET"]),
            Route("/v1/responses", responses, methods=["POST"]),
        ]
    )


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise PersonalRuntimeConfigurationError(f"required environment setting {name} is missing")
    return value


def _receipt_secret() -> bytes:
    value = os.environ.get("MEDIA_BRIDGE_RECEIPT_SECRET", "")
    file_value = os.environ.get("MEDIA_BRIDGE_RECEIPT_SECRET_FILE", "")
    if value and file_value:
        raise PersonalRuntimeConfigurationError("receipt secret sources conflict")
    if file_value:
        path = Path(file_value)
        try:
            if path.is_symlink() or not path.is_file():
                raise PersonalRuntimeConfigurationError("receipt secret file is invalid")
            value = path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise PersonalRuntimeConfigurationError("receipt secret file is unavailable") from error
    encoded = value.encode()
    if len(encoded) < 32:
        raise PersonalRuntimeConfigurationError("receipt secret is missing or too short")
    return encoded


def build_personal_runtime_from_environment() -> PersonalRuntime:
    mode = os.environ.get("MEDIA_BRIDGE_RUNTIME_MODE", "personal").strip().lower()
    if mode != "personal":
        raise PersonalRuntimeConfigurationError("npm runtime mode must be personal")
    model = _required("MEDIA_BRIDGE_SOLAR_MODEL")
    credential_env = os.environ.get("MEDIA_BRIDGE_SOLAR_CREDENTIAL_ENV", "SOLAR_API_KEY").strip()
    ocr_credential_env = os.environ.get(
        "MEDIA_BRIDGE_OCR_CREDENTIAL_ENV", credential_env
    ).strip()
    if re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", credential_env) is None or re.fullmatch(
        r"[A-Z_][A-Z0-9_]{0,127}", ocr_credential_env
    ) is None:
        raise PersonalRuntimeConfigurationError("credential environment name is invalid")
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(60),
        follow_redirects=False,
        trust_env=False,
    )
    ocr = UpstageDocumentParseBackend(
        endpoint=_required("MEDIA_BRIDGE_OCR_ENDPOINT"),
        api_key_env=ocr_credential_env,
        client=client,
    )
    return build_personal_runtime(
        model=model,
        asset_root=Path(_required("MEDIA_BRIDGE_ASSET_ROOT")),
        receipt_secret=_receipt_secret(),
        ocr_backend=ocr,
        downstream_factory=lambda signer: SolarResponsesDownstream(
            endpoint=_required("MEDIA_BRIDGE_SOLAR_ENDPOINT"),
            model=model,
            receipt_signer=signer,
            api_key_env=credential_env,
        ),
        clients=(client,),
    )


def run_personal_npm_runtime() -> None:
    host = os.environ.get("MEDIA_BRIDGE_HTTP_HOST", "127.0.0.1")
    if host != "127.0.0.1":
        raise PersonalRuntimeConfigurationError("personal runtime must bind to 127.0.0.1")
    try:
        port = int(os.environ.get("MEDIA_BRIDGE_HTTP_PORT", "8642"))
    except ValueError as error:
        raise PersonalRuntimeConfigurationError(
            "personal runtime port must be an integer"
        ) from error
    if not 1 <= port <= 65_535:
        raise PersonalRuntimeConfigurationError("personal runtime port is invalid")
    try:
        max_request_bytes = int(
            os.environ.get("MEDIA_BRIDGE_MAX_REQUEST_BYTES", str(8 * 1024 * 1024))
        )
    except ValueError as error:
        raise PersonalRuntimeConfigurationError(
            "personal request limit must be an integer"
        ) from error
    if max_request_bytes < 1:
        raise PersonalRuntimeConfigurationError("personal request limit is invalid")
    runtime = build_personal_runtime_from_environment()
    config_file = Path(_required("MEDIA_BRIDGE_CONFIG_FILE"))
    try:
        uvicorn.run(
            build_personal_app(
                runtime,
                max_request_bytes=max_request_bytes,
                config_file=config_file,
            ),
            host=host,
            port=port,
            access_log=False,
            server_header=False,
        )
    finally:
        asyncio.run(runtime.close())


__all__ = [
    "PersonalRuntime",
    "PersonalRuntimeConfigurationError",
    "UpstageDocumentParseBackend",
    "build_personal_app",
    "build_personal_runtime",
    "build_personal_runtime_from_environment",
    "run_personal_npm_runtime",
]
