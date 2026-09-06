"""Typed OCR, Vision, and text-analysis backend adapters."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx


class BackendStatus(StrEnum):
    SUCCESS = "success"
    NO_TEXT = "no_text"
    FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class OcrResult:
    status: BackendStatus
    text: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class VisionResult:
    status: BackendStatus
    description: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    status: BackendStatus
    analysis: str | None = None
    error_code: str | None = None


class OcrBackend(Protocol):
    async def extract(
        self,
        *,
        data: bytes,
        mime_type: str,
        filename: str | None,
    ) -> OcrResult: ...


class VisionBackend(Protocol):
    async def describe(
        self,
        *,
        data: bytes,
        mime_type: str,
        profile: str,
    ) -> VisionResult: ...


class AnalysisBackend(Protocol):
    async def analyze(self, *, context: str, user_request: str) -> AnalysisResult: ...


class SecretConfigurationError(RuntimeError):
    """Raised without exposing secret values or arbitrary environment content."""


def load_secret(value_env: str, file_env: str | None = None) -> str:
    """Load exactly one named environment secret or named Secret-file reference."""

    value = os.environ.get(value_env, "").strip()
    if value:
        return value
    secret_file_name = file_env or f"{value_env}_FILE"
    configured_path = os.environ.get(secret_file_name, "").strip()
    if not configured_path:
        raise SecretConfigurationError(f"required secret {value_env} is not configured")
    path = Path(configured_path)
    try:
        if not path.is_file() or path.stat().st_size > 16_384:
            raise SecretConfigurationError(f"secret file for {value_env} is invalid")
        file_value = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise SecretConfigurationError(f"secret file for {value_env} is unavailable") from error
    if not file_value:
        raise SecretConfigurationError(f"secret file for {value_env} is empty")
    return file_value


def _validate_endpoint(endpoint: str) -> None:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("backend endpoint must be a credential-free HTTPS URL")


def _failure_code(response: httpx.Response) -> str:
    if response.status_code in {401, 403}:
        return "authentication"
    if response.status_code == 429:
        return "rate_limit"
    return "upstream_http"


def _chat_content(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if not isinstance(content, str):
        return None
    stripped = content.strip()
    return stripped or None


class UpstageOcrBackend:
    """OCR adapter; Solar is not involved in this conversion stage."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key_env: str = "UPSTAGE_API_KEY",
        api_key_file_env: str | None = None,
        client: httpx.AsyncClient,
    ) -> None:
        _validate_endpoint(endpoint)
        self._endpoint = endpoint
        self._api_key_env = api_key_env
        self._api_key_file_env = api_key_file_env
        self._client = client

    async def extract(
        self,
        *,
        data: bytes,
        mime_type: str,
        filename: str | None,
    ) -> OcrResult:
        try:
            secret = load_secret(self._api_key_env, self._api_key_file_env)
        except SecretConfigurationError:
            return OcrResult(BackendStatus.FAILURE, error_code="configuration")
        try:
            response = await self._client.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {secret}"},
                files={"document": (filename or "media", data, mime_type)},
            )
        except httpx.TimeoutException:
            return OcrResult(BackendStatus.FAILURE, error_code="timeout")
        except httpx.RequestError:
            return OcrResult(BackendStatus.FAILURE, error_code="transport")
        if response.status_code >= 400:
            return OcrResult(BackendStatus.FAILURE, error_code=_failure_code(response))
        try:
            payload = response.json()
        except ValueError:
            return OcrResult(BackendStatus.FAILURE, error_code="invalid_response")
        text = self._ocr_text(payload)
        if text is None:
            if isinstance(payload, dict) and payload.get("text") == "  ":
                return OcrResult(BackendStatus.NO_TEXT)
            return OcrResult(BackendStatus.FAILURE, error_code="invalid_response")
        if not text:
            return OcrResult(BackendStatus.NO_TEXT)
        return OcrResult(BackendStatus.SUCCESS, text=text)

    @staticmethod
    def _ocr_text(payload: object) -> str | None:
        if not isinstance(payload, dict):
            return None
        direct = payload.get("text")
        if isinstance(direct, str):
            return direct.strip()
        pages = payload.get("pages")
        if not isinstance(pages, list):
            return None
        texts = [
            str(page["text"]).strip()
            for page in pages
            if isinstance(page, dict) and isinstance(page.get("text"), str)
        ]
        return "\n".join(text for text in texts if text)


class OpenAICompatibleVisionBackend:
    """Vision-description adapter using an OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        api_key_env: str,
        api_key_file_env: str | None = None,
        client: httpx.AsyncClient,
    ) -> None:
        _validate_endpoint(endpoint)
        self._endpoint = endpoint
        self._model = model
        self._api_key_env = api_key_env
        self._api_key_file_env = api_key_file_env
        self._client = client

    async def describe(
        self,
        *,
        data: bytes,
        mime_type: str,
        profile: str,
    ) -> VisionResult:
        if mime_type not in {"image/png", "image/jpeg", "image/webp"}:
            return VisionResult(BackendStatus.FAILURE, error_code="unsupported_media")
        try:
            secret = load_secret(self._api_key_env, self._api_key_file_env)
        except SecretConfigurationError:
            return VisionResult(BackendStatus.FAILURE, error_code="configuration")
        encoded = base64.b64encode(data).decode("ascii")
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Describe visible information for a text-only model. "
                                f"Use the {profile} profile and do not reproduce binary data."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                        },
                    ],
                }
            ],
        }
        try:
            response = await self._client.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {secret}"},
                json=payload,
            )
        except httpx.TimeoutException:
            return VisionResult(BackendStatus.FAILURE, error_code="timeout")
        except httpx.RequestError:
            return VisionResult(BackendStatus.FAILURE, error_code="transport")
        if response.status_code >= 400:
            return VisionResult(BackendStatus.FAILURE, error_code=_failure_code(response))
        try:
            description = _chat_content(response.json())
        except ValueError:
            description = None
        if description is None:
            return VisionResult(BackendStatus.FAILURE, error_code="invalid_response")
        return VisionResult(BackendStatus.SUCCESS, description=description)


class SolarAnalysisBackend:
    """Solar text analysis, interchangeable with any AnalysisBackend."""

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        api_key_env: str = "SOLAR_API_KEY",
        api_key_file_env: str | None = None,
        client: httpx.AsyncClient,
    ) -> None:
        _validate_endpoint(endpoint)
        self._endpoint = endpoint
        self._model = model
        self._api_key_env = api_key_env
        self._api_key_file_env = api_key_file_env
        self._client = client

    async def analyze(self, *, context: str, user_request: str) -> AnalysisResult:
        try:
            secret = load_secret(self._api_key_env, self._api_key_file_env)
        except SecretConfigurationError:
            return AnalysisResult(BackendStatus.FAILURE, error_code="configuration")
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": "Analyze only the supplied text context."},
                {"role": "user", "content": f"{user_request}\n\n{context}"},
            ],
        }
        try:
            response = await self._client.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {secret}"},
                json=payload,
            )
        except httpx.TimeoutException:
            return AnalysisResult(BackendStatus.FAILURE, error_code="timeout")
        except httpx.RequestError:
            return AnalysisResult(BackendStatus.FAILURE, error_code="transport")
        if response.status_code >= 400:
            return AnalysisResult(BackendStatus.FAILURE, error_code=_failure_code(response))
        try:
            analysis = _chat_content(response.json())
        except ValueError:
            analysis = None
        if analysis is None:
            return AnalysisResult(BackendStatus.FAILURE, error_code="invalid_response")
        return AnalysisResult(BackendStatus.SUCCESS, analysis=analysis)
