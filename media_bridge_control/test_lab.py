"""Memory-only Control Plane orchestration for preview and opt-in test calls."""

from __future__ import annotations

import base64
import binascii
import logging
import threading
import time
from collections import deque
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from sqlalchemy import select

from media_bridge_control.db import Database
from media_bridge_control.gateway_client import GatewayClient, GatewayClientError
from media_bridge_control.models import Provider, RoutingProfile
from media_bridge_control.schemas import SecretReference, TestLabPreviewRequest, TestLabRunRequest
from media_bridge_control.secrets import GatewaySecretResolver, SecretResolutionError
from media_bridge_control.security import SecurityContext

logger = logging.getLogger(__name__)


class TestLabError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AdminActionRateLimiter:
    def __init__(
        self,
        *,
        capacity: int = 10,
        window_seconds: float = 60.0,
        max_keys: int = 10_000,
        monotonic: Any = time.monotonic,
    ) -> None:
        if min(capacity, window_seconds, max_keys) <= 0:
            raise ValueError("Admin action rate limits must be positive")
        self._capacity = capacity
        self._window = window_seconds
        self._max_keys = max_keys
        self._monotonic = monotonic
        self._entries: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = float(self._monotonic())
        with self._lock:
            if key not in self._entries and len(self._entries) >= self._max_keys:
                oldest = min(self._entries, key=lambda item: self._entries[item][0])
                del self._entries[oldest]
            values = self._entries.setdefault(key, deque())
            while values and values[0] <= now - self._window:
                values.popleft()
            if len(values) >= self._capacity:
                return False
            values.append(now)
            return True


class TestLabService:
    def __init__(
        self,
        *,
        gateway_client: GatewayClient,
        database: Database,
        security: SecurityContext,
        secret_resolver: GatewaySecretResolver,
    ) -> None:
        self._gateway = gateway_client
        self._database = database
        self._security = security
        self._secret_resolver = secret_resolver

    async def preview(self, request: TestLabPreviewRequest) -> dict[str, object]:
        data = self._decode(request.media_base64)
        profile_id = request.routing_profile_id or self._default_profile_id()
        try:
            profile, analysis, llm = self._providers(profile_id)
            analysis_key = self._provider_key(analysis)
            llm_key = self._provider_key(llm)
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(60), follow_redirects=False, trust_env=False
            ) as client:
                extracted = await self._extract(client, analysis, analysis_key, data, request)
                forwarded = (
                    f"{request.user_request.strip()}\n\n"
                    f"[미디어에서 추출한 텍스트]\n{extracted}"
                ).strip()
                answer = await self._answer(
                    client, llm, llm_key, forwarded, request.reasoning_effort
                )
        except (httpx.HTTPError, ValueError, KeyError, SecretResolutionError) as error:
            logger.exception(
                "test lab routed provider call failed",
                extra={"routing_profile_id": str(request.routing_profile_id)},
            )
            raise TestLabError("upstream_or_downstream_failed") from error
        return {
            "ok": True,
            "routingProfile": {"id": str(profile.id), "name": profile.name},
            "extractedText": extracted,
            "forwardedText": forwarded,
            "originalMediaForwarded": False,
            "answer": answer,
        }

    def _default_profile_id(self) -> Any:
        with self._database.session() as session:
            profile = session.scalar(
                select(RoutingProfile).where(RoutingProfile.enabled.is_(True)).order_by(RoutingProfile.name)
            )
            if profile is None:
                raise TestLabError("routing_profile_unavailable")
            return profile.id

    def _providers(self, profile_id: Any) -> tuple[RoutingProfile, Provider, Provider]:
        with self._database.session() as session:
            profile = session.get(RoutingProfile, profile_id)
            if profile is None or not profile.enabled:
                raise TestLabError("routing_profile_unavailable")
            analysis_id = (profile.analysis_provider_ids or [None])[0]
            llm_id = (profile.llm_provider_ids or [None])[0]
            analysis = session.get(Provider, analysis_id) if analysis_id else None
            llm = session.get(Provider, llm_id) if llm_id else None
            if analysis is None or llm is None or not analysis.enabled or not llm.enabled:
                raise TestLabError("routing_provider_unavailable")
            return profile, analysis, llm

    def _provider_key(self, provider: Provider) -> str:
        if provider.encrypted_api_key:
            return self._security.decrypt_secret(provider.encrypted_api_key)
        return self._secret_resolver.resolve(
            SecretReference(
                kind=provider.secret_ref_kind, identifier=provider.secret_ref_identifier
            )
        )

    async def _extract(
        self,
        client: httpx.AsyncClient,
        provider: Provider,
        key: str,
        data: bytes,
        request: TestLabPreviewRequest,
    ) -> str:
        response = await client.post(
            provider.endpoint,
            headers={"Authorization": f"Bearer {key}"},
            files={"document": (request.filename or "media", data, request.declared_mime)},
            data={
                "ocr": "force",
                "model": provider.model_id or "document-parse",
                "output_formats": '["markdown"]',
            },
        )
        response.raise_for_status()
        body = response.json()
        if isinstance(body, dict) and isinstance(body.get("text"), str):
            return body["text"].strip()
        pages = body.get("pages") if isinstance(body, dict) else None
        if isinstance(pages, list):
            page_text = "\n".join(
                str(page["text"]).strip()
                for page in pages
                if isinstance(page, dict) and isinstance(page.get("text"), str)
            ).strip()
            if page_text:
                return page_text
        content = body.get("content") if isinstance(body, dict) else None
        if isinstance(content, dict):
            for field in ("markdown", "text"):
                value = content.get(field)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        if isinstance(content, str) and content.strip():
            return content.strip()
        raise ValueError("upstream_invalid_response")

    async def _answer(
        self, client: httpx.AsyncClient, provider: Provider, key: str, prompt: str,
        reasoning_effort: str = "provider_default",
    ) -> str:
        protocol = provider.protocol or "openai-chat-completions"
        if protocol == "openai-responses":
            payload: dict[str, Any] = {
                "model": provider.model_id or "auto",
                "input": prompt,
                "stream": False,
            }
        else:
            payload = {
                "model": provider.model_id or "auto",
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            }
        if reasoning_effort != "provider_default":
            payload["reasoning_effort"] = reasoning_effort
        response = await client.post(
            self._llm_endpoint(provider.endpoint, protocol),
            headers={"Authorization": f"Bearer {key}"},
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        if protocol == "openai-responses":
            answer = "\n".join(
                str(part.get("text", "")).strip()
                for item in body.get("output", [])
                if isinstance(item, dict)
                for part in item.get("content", [])
                if isinstance(part, dict) and part.get("type") == "output_text"
            ).strip()
        else:
            answer = str(body["choices"][0]["message"]["content"]).strip()
        if not answer:
            raise ValueError("downstream_empty_response")
        return answer

    @staticmethod
    def _llm_endpoint(endpoint: str, protocol: str) -> str:
        """Accept catalog base URLs as well as fully-qualified API endpoints."""
        suffix = "/responses" if protocol == "openai-responses" else "/chat/completions"
        parsed = urlsplit(endpoint.rstrip("/"))
        if parsed.path.endswith(suffix):
            return endpoint
        return urlunsplit(parsed._replace(path=f"{parsed.path}{suffix}"))

    async def run(self, request: TestLabRunRequest) -> dict[str, object]:
        if request.gateway_url is None or request.api_key is None:
            raise TestLabError("downstream_credentials_required")
        # Use the OpenAI-compatible ``auto`` model for the UI's unspecified
        # choice. The target Gateway resolves it against its own active
        # snapshot; Control must not guess from its local model catalog.
        target_model = request.target_model or "auto"
        data = self._decode(request.media_base64)
        asset_id: str | None = None
        primary_error: TestLabError | None = None
        result: dict[str, object] | None = None
        try:
            asset_id = await self._gateway.upload(
                base_url=request.gateway_url,
                credential=request.api_key,
                data=data,
                filename=request.filename,
                declared_mime=request.declared_mime,
            )
            result = await self._gateway.responses(
                base_url=request.gateway_url,
                credential=request.api_key,
                payload=self._responses_payload(request, asset_id, target_model),
            )
        except GatewayClientError as error:
            primary_error = TestLabError(error.code)
        finally:
            if asset_id is not None:
                try:
                    await self._gateway.delete(
                        base_url=request.gateway_url,
                        credential=request.api_key,
                        asset_id=asset_id,
                    )
                except GatewayClientError as error:
                    if primary_error is None:
                        primary_error = TestLabError(error.code)
        if primary_error is not None:
            raise primary_error
        if result is None:
            raise TestLabError("gateway_unavailable")
        return result

    @staticmethod
    def _decode(value: str) -> bytes:
        try:
            data = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as error:
            raise TestLabError("invalid_media_base64") from error
        if not data or len(data) > 2 * 1024 * 1024:
            raise TestLabError("media_size_invalid")
        return data

    @staticmethod
    def _prepare_payload(
        request: TestLabPreviewRequest,
        asset_id: str,
    ) -> dict[str, Any]:
        return {
            "routing_profile_id": (
                str(request.routing_profile_id) if request.routing_profile_id is not None else None
            ),
            "content": [
                {"type": "text", "text": request.user_request},
                {
                    "type": "media",
                    "media_type": request.media_type,
                    "source": {"kind": "asset_id", "asset_id": asset_id},
                    "filename": request.filename,
                    "declared_mime": request.declared_mime,
                },
            ],
            "target": {"registry_id": request.target_model},
            "conversion_profile": request.conversion_profile,
        }

    @staticmethod
    def _responses_payload(
        request: TestLabRunRequest,
        asset_id: str,
        target_model: str | None,
    ) -> dict[str, Any]:
        media_part: dict[str, object]
        if request.media_type == "image":
            media_part = {"type": "input_image", "asset_id": asset_id}
        else:
            media_part = {
                "type": "input_file",
                "asset_id": asset_id,
                "filename": request.filename,
            }
        return {
            **({"model": target_model} if target_model is not None else {}),
            **(
                {"reasoning_effort": request.reasoning_effort}
                if request.reasoning_effort != "provider_default"
                else {}
            ),
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": request.user_request},
                        media_part,
                    ],
                }
            ],
            "stream": False,
        }
