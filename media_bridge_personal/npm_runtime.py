"""Single-user npm runtime composed from the shared Media Bridge Core."""

# The settings console embeds audited HTML/CSS/JavaScript assets as multiline literals.
# ruff: noqa: E501

from __future__ import annotations

import asyncio
import base64
import binascii
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
from media_bridge_personal.credential_store import CredentialStore, CredentialStoreError
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
        secret_loader: Callable[[], str] | None = None,
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
        self._secret_loader = secret_loader

    async def extract(
        self,
        *,
        data: bytes,
        mime_type: str,
        filename: str | None,
    ) -> OcrResult:
        try:
            secret = (
                self._secret_loader().strip()
                if self._secret_loader is not None
                else os.environ.get(self._api_key_env, "").strip()
            )
        except CredentialStoreError:
            secret = ""
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
_CREDENTIAL_REFERENCE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_CODING_AGENT_PRESETS = {"opencodex", "eoul-gateway", "custom"}
_TEXT_PROTOCOLS = {"openai-chat-completions", "openai-responses"}
_SETTINGS_RESPONSE_HEADERS = {
    "cache-control": "no-store",
    "content-security-policy": (
        "default-src 'self'; style-src 'unsafe-inline'; script-src 'self'; object-src 'none'; "
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


def _section(config: dict[str, Any], name: str) -> dict[str, Any]:
    value = config.get(name)
    return value if isinstance(value, dict) else {}


def _normalize_npm_config(config: dict[str, Any]) -> dict[str, Any]:
    """Read both the 0.1.10 schema and the role-based provider schema."""
    result = dict(config)
    host = str(result.get("host", "127.0.0.1"))
    port = int(result.get("port", 8642))
    legacy_agent = _section(result, "opencodex")
    legacy_llm = _section(result, "solar")
    legacy_media = _section(result, "ocr")
    result["codingAgent"] = {
        "preset": "opencodex",
        "protocol": "openai-responses",
        "baseUrl": legacy_agent.get("baseUrl", f"http://{host}:{port}/v1"),
        **_section(result, "codingAgent"),
    }
    result["textLlm"] = {
        "preset": "upstage-solar",
        "protocol": "openai-chat-completions",
        "endpoint": legacy_llm.get(
            "endpoint", "https://api.upstage.ai/v1/chat/completions"
        ),
        "model": legacy_llm.get("model", "solar-pro4"),
        "credentialRef": "text-llm",
        "credentialEnv": legacy_llm.get("apiKeyEnv", "SOLAR_API_KEY"),
        **_section(result, "textLlm"),
    }
    result["mediaProcessor"] = {
        "preset": "upstage-document-parse",
        "protocol": "upstage-document-parse",
        "endpoint": legacy_media.get(
            "endpoint", "https://api.upstage.ai/v1/document-digitization"
        ),
        "model": legacy_media.get("model", "document-parse"),
        "credentialRef": "media-processor",
        "credentialEnv": legacy_media.get("apiKeyEnv", "SOLAR_API_KEY"),
        **_section(result, "mediaProcessor"),
    }
    return result


def _validate_endpoint(endpoint: str, *, loopback_allowed: bool) -> str:
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
    return endpoint


def _validated_generic_settings(payload: object, current: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PersonalRuntimeConfigurationError("settings are invalid")
    try:
        port = int(payload["port"])
        coding_agent = dict(payload["codingAgent"])
        text_llm = dict(payload["textLlm"])
        media_processor = dict(payload["mediaProcessor"])
        conversion = dict(payload["conversion"])
        failure_policy = dict(payload["failurePolicy"])
        max_bytes = int(conversion["maxBytes"])
    except (KeyError, TypeError, ValueError) as error:
        raise PersonalRuntimeConfigurationError("settings are invalid") from error
    if not 1 <= port <= 65_535 or max_bytes < 1:
        raise PersonalRuntimeConfigurationError("settings are invalid")
    agent_preset = str(coding_agent.get("preset", "")).strip()
    agent_protocol = str(coding_agent.get("protocol", "")).strip()
    agent_base_url = _validate_endpoint(
        str(coding_agent.get("baseUrl", "")).strip(), loopback_allowed=True
    )
    llm_preset = str(text_llm.get("preset", "")).strip()
    llm_protocol = str(text_llm.get("protocol", "")).strip()
    llm_endpoint = _validate_endpoint(
        str(text_llm.get("endpoint", "")).strip(), loopback_allowed=True
    )
    llm_model = str(text_llm.get("model", "")).strip()
    llm_reference = str(text_llm.get("credentialRef", "")).strip()
    llm_environment = str(text_llm.get("credentialEnv", "")).strip()
    media_preset = str(media_processor.get("preset", "")).strip()
    media_protocol = str(media_processor.get("protocol", "")).strip()
    media_endpoint = _validate_endpoint(
        str(media_processor.get("endpoint", "")).strip(), loopback_allowed=True
    )
    media_model = str(media_processor.get("model", "")).strip()
    media_reference = str(media_processor.get("credentialRef", "")).strip()
    media_environment = str(media_processor.get("credentialEnv", "")).strip()
    if (
        agent_preset not in _CODING_AGENT_PRESETS
        or agent_protocol != "openai-responses"
        or llm_preset not in {"upstage-solar", "custom"}
        or llm_protocol not in _TEXT_PROTOCOLS
        or not llm_model
        or _CREDENTIAL_REFERENCE.fullmatch(llm_reference) is None
        or _ENV_REFERENCE.fullmatch(llm_environment) is None
        or media_preset != "upstage-document-parse"
        or media_protocol != "upstage-document-parse"
        or media_model != "document-parse"
        or _CREDENTIAL_REFERENCE.fullmatch(media_reference) is None
        or _ENV_REFERENCE.fullmatch(media_environment) is None
    ):
        raise PersonalRuntimeConfigurationError("settings are invalid")
    result = _normalize_npm_config(current)
    result.update({"runtimeMode": "personal", "host": "127.0.0.1", "port": port})
    result["codingAgent"] = {
        "preset": agent_preset,
        "protocol": agent_protocol,
        "baseUrl": agent_base_url,
    }
    result["textLlm"] = {
        "preset": llm_preset,
        "protocol": llm_protocol,
        "endpoint": llm_endpoint,
        "model": llm_model,
        "credentialRef": llm_reference,
        "credentialEnv": llm_environment,
    }
    result["mediaProcessor"] = {
        "preset": media_preset,
        "protocol": media_protocol,
        "endpoint": media_endpoint,
        "model": media_model,
        "credentialRef": media_reference,
        "credentialEnv": media_environment,
    }
    result["conversion"] = {
        "maxBytes": max_bytes,
        "ocrEnabled": conversion.get("ocrEnabled") is True,
        "visionEnabled": conversion.get("visionEnabled") is True,
    }
    result["failurePolicy"] = {
        "blockSolarOnPreparationFailure": failure_policy.get(
            "blockSolarOnPreparationFailure"
        )
        is True
    }
    # 0.1.10 readers keep working while the role-based schema becomes canonical.
    result["opencodex"] = {"baseUrl": agent_base_url}
    result["solar"] = {
        "model": llm_model,
        "endpoint": llm_endpoint,
        "apiKeyEnv": llm_environment,
    }
    result["ocr"] = {
        "model": media_model,
        "endpoint": media_endpoint,
        "apiKeyEnv": media_environment,
    }
    return result


def _public_settings(config: dict[str, Any], store: CredentialStore) -> dict[str, Any]:
    normalized = _normalize_npm_config(config)
    return {
        key: value
        for key, value in normalized.items()
        if key not in {"solar", "ocr", "opencodex"}
    } | {"credentials": store.status()}


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
    normalized = _normalize_npm_config(result)
    normalized["codingAgent"] = {
        "preset": "opencodex",
        "protocol": "openai-responses",
        "baseUrl": opencodex_base_url,
    }
    normalized["textLlm"] = {
        "preset": "upstage-solar",
        "protocol": "openai-chat-completions",
        "endpoint": solar_endpoint,
        "model": solar_model,
        "credentialRef": "text-llm",
        "credentialEnv": solar_api_key_env,
    }
    normalized["mediaProcessor"] = {
        "preset": "upstage-document-parse",
        "protocol": "upstage-document-parse",
        "endpoint": ocr_endpoint,
        "model": "document-parse",
        "credentialRef": "media-processor",
        "credentialEnv": ocr_api_key_env,
    }
    return normalized


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
    normalized = _normalize_npm_config(config)
    coding_agent = _section(normalized, "codingAgent")
    text_llm = _section(normalized, "textLlm")
    media = _section(normalized, "mediaProcessor")
    conversion = _section(normalized, "conversion")
    policy = _section(normalized, "failurePolicy")

    def value(item: object) -> str:
        return html.escape(str(item), quote=True)

    def selected(actual: object, expected: str) -> str:
        return " selected" if actual == expected else ""

    checked_ocr = " checked" if conversion.get("ocrEnabled") is not False else ""
    checked_vision = " checked" if conversion.get("visionEnabled") is not False else ""
    checked_block = (
        " checked" if policy.get("blockSolarOnPreparationFailure") is not False else ""
    )
    notice = (
        '<p class="notice" role="status">설정을 저장했습니다. 현재 시험 화면에는 즉시 반영되며 '
        '일반 요청에는 <code>mb service restart</code> 후 적용됩니다.</p>'
        if saved
        else ""
    )
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Media Bridge 설정 및 시험</title>
<style>
:root{{color-scheme:dark;--bg:#0b1020;--panel:#151c31;--line:#2a3555;--text:#edf2ff;--muted:#a8b3cf;--accent:#65d6b5;--danger:#ff8b8b}}
*{{box-sizing:border-box}} body{{margin:0;background:linear-gradient(145deg,#080d19,#111a30);color:var(--text);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:1120px;margin:auto;padding:32px 20px 64px}} header{{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:24px}}
h1{{margin:0;font-size:clamp(28px,5vw,44px)}} h2{{margin-top:0;font-size:20px}} p{{color:var(--muted)}}
.badge{{padding:7px 12px;border:1px solid #315e58;border-radius:999px;color:var(--accent);white-space:nowrap}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:16px}} section{{background:rgba(21,28,49,.96);border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:0 14px 36px #0005}}
label{{display:block;margin:12px 0;color:var(--muted)}} input,select,textarea{{display:block;width:100%;margin-top:5px;padding:10px 12px;border:1px solid #3a486e;border-radius:9px;background:#0c1326;color:var(--text)}}
input[type=checkbox]{{display:inline;width:auto;margin-right:8px}} button{{border:0;border-radius:9px;padding:10px 15px;background:var(--accent);color:#06251d;font-weight:700;cursor:pointer;margin:5px 6px 5px 0}} button.secondary{{background:#283553;color:var(--text)}}
.wide{{grid-column:1/-1}} .result{{min-height:72px;white-space:pre-wrap;background:#080d19;border:1px solid var(--line);border-radius:10px;padding:12px;color:#cfe3ff}} .notice{{color:var(--accent)}} .secret-state{{font-size:13px;color:var(--muted)}} code{{color:#9debd5}} @media(max-width:620px){{header{{display:block}}.badge{{display:inline-block;margin-top:12px}}}}
</style></head><body><main>
<header><div><h1>Media Bridge</h1><p>미디어를 텍스트로 변환해 Non-Vision LLM과 코딩 에이전트를 연결합니다.</p></div><span class="badge">127.0.0.1 로컬 전용</span></header>
{notice}<form id="settings-form" method="post" action="/settings">
<div class="grid">
<section><h2>Media Bridge</h2>
<label>포트<input name="port" type="number" min="1" max="65535" required value="{value(normalized.get('port', 8642))}"></label>
<label>변환 최대 크기(bytes)<input name="max_bytes" type="number" min="1" required value="{value(conversion.get('maxBytes', 8_388_608))}"></label>
<label><input name="ocr_enabled" type="checkbox" value="true"{checked_ocr}>OCR 변환 사용</label>
<label><input name="vision_enabled" type="checkbox" value="true"{checked_vision}>Vision 보강 사용</label>
<label><input name="block_solar_on_failure" type="checkbox" value="true"{checked_block}>미디어 처리 실패 시 LLM 전송 차단</label></section>
<section><h2>코딩 에이전트</h2>
<label>연결 대상<select name="coding_agent_preset"><option value="opencodex"{selected(coding_agent.get('preset'),'opencodex')}>OpenCodex</option><option value="eoul-gateway"{selected(coding_agent.get('preset'),'eoul-gateway')}>Eoul Gateway</option><option value="custom"{selected(coding_agent.get('preset'),'custom')}>OpenAI Responses 호환</option></select></label>
<label>프로토콜<select name="coding_agent_protocol"><option value="openai-responses">OpenAI Responses</option></select></label>
<label>에이전트에 설정할 주소<input name="opencodex_base_url" type="url" required value="{value(coding_agent.get('baseUrl','http://127.0.0.1:8642/v1'))}"></label>
<button class="secondary" type="button" data-action="agent">연결 정보 확인</button><div id="agent-result" class="result" aria-live="polite"></div></section>
<section><h2>Non-Vision LLM</h2>
<label>Provider<select name="text_llm_preset"><option value="upstage-solar"{selected(text_llm.get('preset'),'upstage-solar')}>Upstage Solar</option><option value="custom"{selected(text_llm.get('preset'),'custom')}>사용자 정의</option></select></label>
<label>API 방식<select name="text_llm_protocol"><option value="openai-chat-completions"{selected(text_llm.get('protocol'),'openai-chat-completions')}>Chat Completions</option><option value="openai-responses"{selected(text_llm.get('protocol'),'openai-responses')}>Responses</option></select></label>
<label>Endpoint<input name="solar_endpoint" type="url" required value="{value(text_llm.get('endpoint','https://api.upstage.ai/v1/chat/completions'))}"></label>
<label>모델<input name="solar_model" required value="{value(text_llm.get('model','solar-pro4'))}"></label>
<label>API Key<input name="text_llm_api_key" type="password" autocomplete="new-password" placeholder="저장된 키는 다시 표시하지 않습니다"></label>
<label>환경변수 대체 입력<input name="solar_api_key_env" required value="{value(text_llm.get('credentialEnv','SOLAR_API_KEY'))}"></label>
<p class="secret-state" data-secret="text-llm">저장 상태를 확인하는 중…</p><button class="secondary" type="button" data-action="text-llm">LLM 연결 시험</button><div id="text-llm-result" class="result" aria-live="polite"></div></section>
<section><h2>Vision / OCR 처리 엔진</h2>
<label>엔진<select name="media_processor_preset"><option value="upstage-document-parse">Upstage Document Parse</option></select></label>
<label>Endpoint<input name="ocr_endpoint" type="url" required value="{value(media.get('endpoint','https://api.upstage.ai/v1/document-digitization'))}"></label>
<label>모델<input name="media_processor_model" required value="{value(media.get('model','document-parse'))}"></label>
<label>API Key<input name="media_processor_api_key" type="password" autocomplete="new-password" placeholder="Solar와 같은 키라면 동일하게 입력"></label>
<label>환경변수 대체 입력<input name="ocr_api_key_env" required value="{value(media.get('credentialEnv','SOLAR_API_KEY'))}"></label>
<label>시험 이미지/PDF<input name="media_test_file" type="file" accept="image/*,application/pdf"></label>
<p class="secret-state" data-secret="media-processor">저장 상태를 확인하는 중…</p><button class="secondary" type="button" data-action="media-processor">OCR 연결 시험</button><div id="media-processor-result" class="result" aria-live="polite"></div></section>
<section class="wide"><h2>전체 흐름 시험</h2><p>선택한 파일을 OCR 처리하고 원본 미디어를 제거한 텍스트만 Non-Vision LLM에 보냅니다.</p>
<label>질문<textarea name="pipeline_question" rows="3">이 이미지 또는 문서의 내용을 한국어로 설명해 주세요.</textarea></label>
<button class="secondary" type="button" data-action="pipeline">전체 파이프라인 시험</button><div id="pipeline-result" class="result" aria-live="polite"></div></section>
</div><p><button type="submit">설정 저장</button></p></form>
<script src="/assets/settings.js" defer></script></main></body></html>"""


def _settings_script() -> str:
    return """'use strict';
const form=document.querySelector('#settings-form');
const field=(name)=>form.elements.namedItem(name);
const show=(id,value)=>{document.querySelector(`#${id}`).textContent=typeof value==='string'?value:JSON.stringify(value,null,2)};
const payload=()=>({
 port:Number(field('port').value),
 codingAgent:{preset:field('coding_agent_preset').value,protocol:field('coding_agent_protocol').value,baseUrl:field('opencodex_base_url').value},
 textLlm:{preset:field('text_llm_preset').value,protocol:field('text_llm_protocol').value,endpoint:field('solar_endpoint').value,model:field('solar_model').value,credentialRef:'text-llm',credentialEnv:field('solar_api_key_env').value,apiKey:field('text_llm_api_key').value},
 mediaProcessor:{preset:field('media_processor_preset').value,protocol:'upstage-document-parse',endpoint:field('ocr_endpoint').value,model:field('media_processor_model').value,credentialRef:'media-processor',credentialEnv:field('ocr_api_key_env').value,apiKey:field('media_processor_api_key').value},
 conversion:{maxBytes:Number(field('max_bytes').value),ocrEnabled:field('ocr_enabled').checked,visionEnabled:field('vision_enabled').checked},
 failurePolicy:{blockSolarOnPreparationFailure:field('block_solar_on_failure').checked}
});
async function call(url,body){const response=await fetch(url,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw new Error(data.message||data.error||`HTTP ${response.status}`);return data}
async function filePayload(){const file=field('media_test_file').files[0];if(!file)throw new Error('시험 이미지 또는 PDF를 선택하세요.');const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=0x8000)binary+=String.fromCharCode(...bytes.subarray(i,i+0x8000));return {filename:file.name,mimeType:file.type||'application/octet-stream',dataBase64:btoa(binary)}}
form.addEventListener('submit',async(event)=>{event.preventDefault();try{await call('/api/settings',payload());field('text_llm_api_key').value='';field('media_processor_api_key').value='';show('agent-result','설정을 저장했습니다. Provider 연결 시험을 실행할 수 있습니다.');await load()}catch(error){show('agent-result',`저장 실패: ${error.message}`)}});
document.querySelectorAll('[data-action]').forEach(button=>button.addEventListener('click',async()=>{const action=button.dataset.action;const id=`${action}-result`;try{if(action==='agent'){const response=await fetch('/api/coding-agent');show(id,await response.json());return}if(action==='text-llm'){show(id,await call('/api/test/text-llm',{prompt:'Media Bridge 연결 시험입니다. 한국어로 짧게 응답해 주세요.'}));return}const file=await filePayload();if(action==='media-processor'){show(id,await call('/api/test/media-processor',file));return}show(id,await call('/api/test/pipeline',{...file,question:field('pipeline_question').value}))}catch(error){show(id,`시험 실패: ${error.message}`)}}));
async function load(){const response=await fetch('/api/settings');const data=await response.json();document.querySelectorAll('[data-secret]').forEach(node=>{node.textContent=data.credentials[node.dataset.secret]?'API Key 저장됨':'API Key 미저장 (환경변수 대체 가능)'})}load();
"""


class ProviderTester:
    """Run bounded provider probes without exposing credential material."""

    def __init__(
        self,
        credential_store: CredentialStore,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._credential_store = credential_store
        self._transport = transport

    def _secret(self, profile: dict[str, Any]) -> str:
        try:
            return self._credential_store.resolve(
                str(profile["credentialRef"]), str(profile.get("credentialEnv", ""))
            )
        except (KeyError, CredentialStoreError) as error:
            raise PersonalRuntimeConfigurationError("provider credential is not configured") from error

    async def test_text_llm(self, config: dict[str, Any], prompt: str) -> dict[str, Any]:
        profile = _section(_normalize_npm_config(config), "textLlm")
        text = prompt.strip()
        if not text or len(text) > 8_192:
            raise PersonalRuntimeConfigurationError("test prompt is invalid")
        protocol = str(profile.get("protocol", ""))
        model = str(profile.get("model", ""))
        endpoint = str(profile.get("endpoint", ""))
        if protocol == "openai-chat-completions":
            request_payload: dict[str, Any] = {
                "model": model,
                "messages": [{"role": "user", "content": text}],
                "stream": False,
            }
        elif protocol == "openai-responses":
            request_payload = {"model": model, "input": text, "stream": False}
        else:
            raise PersonalRuntimeConfigurationError("text LLM protocol is unsupported")
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=httpx.Timeout(60),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            try:
                response = await client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {self._secret(profile)}",
                        "Content-Type": "application/json",
                    },
                    json=request_payload,
                )
            except httpx.TimeoutException as error:
                raise PersonalRuntimeConfigurationError("text LLM connection timed out") from error
            except httpx.RequestError as error:
                raise PersonalRuntimeConfigurationError("text LLM connection failed") from error
        if response.status_code >= 400:
            raise PersonalRuntimeConfigurationError(
                f"text LLM rejected the test with HTTP {response.status_code}"
            )
        try:
            body = response.json()
            if protocol == "openai-chat-completions":
                answer = str(body["choices"][0]["message"]["content"]).strip()
            else:
                answer = "\n".join(
                    str(part.get("text", "")).strip()
                    for item in body.get("output", [])
                    if isinstance(item, dict)
                    for part in item.get("content", [])
                    if isinstance(part, dict) and part.get("type") == "output_text"
                ).strip()
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise PersonalRuntimeConfigurationError("text LLM returned an invalid response") from error
        if not answer:
            raise PersonalRuntimeConfigurationError("text LLM returned an empty response")
        return {"ok": True, "protocol": protocol, "model": model, "text": answer}

    async def test_media_processor(
        self,
        config: dict[str, Any],
        *,
        data: bytes,
        mime_type: str,
        filename: str,
    ) -> dict[str, Any]:
        profile = _section(_normalize_npm_config(config), "mediaProcessor")
        if profile.get("protocol") != "upstage-document-parse":
            raise PersonalRuntimeConfigurationError("media processor protocol is unsupported")
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=httpx.Timeout(60),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            backend = UpstageDocumentParseBackend(
                endpoint=str(profile.get("endpoint", "")),
                api_key_env=str(profile.get("credentialEnv", "")),
                client=client,
                secret_loader=lambda: self._secret(profile),
            )
            result = await backend.extract(data=data, mime_type=mime_type, filename=filename)
        if result.status is not BackendStatus.SUCCESS or result.text is None:
            raise PersonalRuntimeConfigurationError(
                f"media processor test failed: {result.error_code or result.status.value}"
            )
        return {
            "ok": True,
            "protocol": profile.get("protocol"),
            "model": profile.get("model"),
            "text": result.text,
        }

    async def test_pipeline(
        self,
        config: dict[str, Any],
        *,
        data: bytes,
        mime_type: str,
        filename: str,
        question: str,
    ) -> dict[str, Any]:
        media_result = await self.test_media_processor(
            config, data=data, mime_type=mime_type, filename=filename
        )
        extracted = str(media_result["text"])
        forwarded = f"{question.strip()}\n\n[미디어에서 추출한 텍스트]\n{extracted}".strip()
        llm_result = await self.test_text_llm(config, forwarded)
        return {
            "ok": True,
            "extractedText": extracted,
            "forwardedText": forwarded,
            "originalMediaForwarded": False,
            "answer": llm_result["text"],
        }


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
    credential_store: CredentialStore | None = None,
    provider_tester: ProviderTester | None = None,
) -> ASGIApp:
    if max_request_bytes < 1:
        raise ValueError("personal request limit must be positive")

    if config_file is not None and credential_store is None:
        credential_store = CredentialStore(config_file.parent / "secrets" / "providers.json")
    if credential_store is not None and provider_tester is None:
        provider_tester = ProviderTester(credential_store)

    def same_origin(request: Request) -> bool:
        expected_origins = {
            f"http://127.0.0.1:{request.url.port or 80}",
            f"http://localhost:{request.url.port or 80}",
        }
        return request.headers.get("origin") in expected_origins

    async def json_payload(request: Request) -> object:
        content_type = request.headers.get("content-type", "").partition(";")[0]
        if content_type != "application/json":
            raise PersonalRuntimeConfigurationError("JSON content type is required")
        body = await request.body()
        if len(body) > max_request_bytes:
            raise PersonalRuntimeConfigurationError("request is too large")
        try:
            return json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PersonalRuntimeConfigurationError("request JSON is invalid") from error

    def media_payload(payload: object) -> tuple[bytes, str, str]:
        if not isinstance(payload, dict):
            raise PersonalRuntimeConfigurationError("media test payload is invalid")
        try:
            filename = str(payload["filename"]).strip()
            mime_type = str(payload["mimeType"]).strip().lower()
            encoded = str(payload["dataBase64"])
            data = base64.b64decode(encoded, validate=True)
        except (KeyError, TypeError, ValueError, binascii.Error) as error:
            raise PersonalRuntimeConfigurationError("media test payload is invalid") from error
        if (
            not filename
            or len(filename) > 255
            or not (mime_type.startswith("image/") or mime_type == "application/pdf")
            or not data
            or len(data) > max_request_bytes
        ):
            raise PersonalRuntimeConfigurationError("media test payload is invalid")
        return data, mime_type, filename

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "mode": "personal"})

    async def settings_home(_request: Request) -> HTMLResponse:
        if config_file is None:
            return HTMLResponse("Media Bridge settings are unavailable.", status_code=404)
        return HTMLResponse(
            _settings_page(_load_npm_config(config_file)),
            headers=_SETTINGS_RESPONSE_HEADERS,
        )

    async def settings_script(_request: Request) -> Response:
        return Response(
            _settings_script(),
            media_type="application/javascript",
            headers={"cache-control": "no-store"},
        )

    async def get_settings(_request: Request) -> JSONResponse:
        if config_file is None or credential_store is None:
            return JSONResponse({"message": "settings are unavailable"}, status_code=404)
        try:
            return JSONResponse(_public_settings(_load_npm_config(config_file), credential_store))
        except (PersonalRuntimeConfigurationError, CredentialStoreError) as error:
            return JSONResponse({"message": str(error)}, status_code=400)

    async def save_api_settings(request: Request) -> JSONResponse:
        if config_file is None or credential_store is None:
            return JSONResponse({"message": "settings are unavailable"}, status_code=404)
        if not same_origin(request):
            return JSONResponse({"message": "forbidden"}, status_code=403)
        try:
            payload = await json_payload(request)
            config = _validated_generic_settings(payload, _load_npm_config(config_file))
            assert isinstance(payload, dict)
            for profile_name in ("textLlm", "mediaProcessor"):
                profile = payload.get(profile_name)
                if not isinstance(profile, dict):
                    raise PersonalRuntimeConfigurationError("settings are invalid")
                secret = profile.get("apiKey")
                if secret is not None and str(secret).strip():
                    credential_store.set(str(profile["credentialRef"]), str(secret))
            _write_npm_config(config_file, config)
            return JSONResponse({"status": "saved", **_public_settings(config, credential_store)})
        except (PersonalRuntimeConfigurationError, CredentialStoreError) as error:
            return JSONResponse({"message": str(error)}, status_code=400)

    async def coding_agent(_request: Request) -> JSONResponse:
        if config_file is None:
            return JSONResponse({"message": "settings are unavailable"}, status_code=404)
        config = _normalize_npm_config(_load_npm_config(config_file))
        profile = _section(config, "codingAgent")
        base_url = str(profile.get("baseUrl", "")).rstrip("/")
        return JSONResponse(
            {
                "preset": profile.get("preset"),
                "protocol": profile.get("protocol"),
                "baseUrl": base_url,
                "responsesUrl": f"{base_url}/responses",
                "healthUrl": f"http://127.0.0.1:{config.get('port', 8642)}/health",
            }
        )

    async def run_provider_test(request: Request) -> JSONResponse:
        if config_file is None or provider_tester is None:
            return JSONResponse({"message": "provider tests are unavailable"}, status_code=404)
        if not same_origin(request):
            return JSONResponse({"message": "forbidden"}, status_code=403)
        try:
            payload = await json_payload(request)
            config = _normalize_npm_config(_load_npm_config(config_file))
            if request.url.path.endswith("/text-llm"):
                if not isinstance(payload, dict):
                    raise PersonalRuntimeConfigurationError("test payload is invalid")
                result = await provider_tester.test_text_llm(
                    config, str(payload.get("prompt", ""))
                )
            elif request.url.path.endswith("/media-processor"):
                data, mime_type, filename = media_payload(payload)
                result = await provider_tester.test_media_processor(
                    config,
                    data=data,
                    mime_type=mime_type,
                    filename=filename,
                )
            else:
                data, mime_type, filename = media_payload(payload)
                assert isinstance(payload, dict)
                question = str(payload.get("question", "")).strip()
                if not question or len(question) > 8_192:
                    raise PersonalRuntimeConfigurationError("pipeline question is invalid")
                result = await provider_tester.test_pipeline(
                    config,
                    data=data,
                    mime_type=mime_type,
                    filename=filename,
                    question=question,
                )
            return JSONResponse(result)
        except (PersonalRuntimeConfigurationError, CredentialStoreError) as error:
            return JSONResponse({"message": str(error)}, status_code=502)

    async def save_settings(request: Request) -> HTMLResponse:
        if config_file is None:
            return HTMLResponse("Media Bridge settings are unavailable.", status_code=404)
        if not same_origin(request):
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
            Route("/assets/settings.js", settings_script, methods=["GET"]),
            Route("/settings", save_settings, methods=["POST"]),
            Route("/api/settings", get_settings, methods=["GET"]),
            Route("/api/settings", save_api_settings, methods=["POST"]),
            Route("/api/coding-agent", coding_agent, methods=["GET"]),
            Route("/api/test/text-llm", run_provider_test, methods=["POST"]),
            Route("/api/test/media-processor", run_provider_test, methods=["POST"]),
            Route("/api/test/pipeline", run_provider_test, methods=["POST"]),
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
    text_protocol = os.environ.get(
        "MEDIA_BRIDGE_TEXT_LLM_PROTOCOL", "openai-chat-completions"
    ).strip()
    text_credential_ref = os.environ.get(
        "MEDIA_BRIDGE_TEXT_LLM_CREDENTIAL_REF", "text-llm"
    ).strip()
    media_protocol = os.environ.get(
        "MEDIA_BRIDGE_MEDIA_PROCESSOR_PROTOCOL", "upstage-document-parse"
    ).strip()
    media_credential_ref = os.environ.get(
        "MEDIA_BRIDGE_MEDIA_PROCESSOR_CREDENTIAL_REF", "media-processor"
    ).strip()
    if re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", credential_env) is None or re.fullmatch(
        r"[A-Z_][A-Z0-9_]{0,127}", ocr_credential_env
    ) is None:
        raise PersonalRuntimeConfigurationError("credential environment name is invalid")
    if (
        text_protocol not in _TEXT_PROTOCOLS
        or media_protocol != "upstage-document-parse"
        or _CREDENTIAL_REFERENCE.fullmatch(text_credential_ref) is None
        or _CREDENTIAL_REFERENCE.fullmatch(media_credential_ref) is None
    ):
        raise PersonalRuntimeConfigurationError("provider protocol or credential reference is invalid")
    credential_file = Path(
        os.environ.get(
            "MEDIA_BRIDGE_CREDENTIAL_STORE_FILE",
            str(Path.home() / ".media-bridge" / "secrets" / "providers.json"),
        )
    )
    credential_store = CredentialStore(credential_file)
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(60),
        follow_redirects=False,
        trust_env=False,
    )
    ocr = UpstageDocumentParseBackend(
        endpoint=_required("MEDIA_BRIDGE_OCR_ENDPOINT"),
        api_key_env=ocr_credential_env,
        client=client,
        secret_loader=lambda: credential_store.resolve(
            media_credential_ref, ocr_credential_env
        ),
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
            credential_loader=lambda: credential_store.resolve(
                text_credential_ref, credential_env
            ),
            protocol=text_protocol,
            provider_name="Text LLM",
            error_prefix="text_llm",
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
