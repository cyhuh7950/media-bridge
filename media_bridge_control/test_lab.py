"""Control Plane orchestration that executes through the Data Plane Gateway."""

from __future__ import annotations

import base64
import binascii
import logging
import threading
import time
from collections import deque
from typing import Any

from media_bridge_control.db import Database
from media_bridge_control.gateway_client import GatewayClient, GatewayClientError
from media_bridge_control.models import Provider, RoutingProfile
from media_bridge_control.schemas import TestLabPreviewRequest, TestLabRunRequest
from media_bridge_control.secrets import GatewaySecretResolver
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
        gateway_url: str | None = None,
        gateway_credential: str | None = None,
    ) -> None:
        self._gateway = gateway_client
        self._database = database
        self._security = security
        self._secret_resolver = secret_resolver
        self._gateway_url = gateway_url
        self._gateway_credential = gateway_credential

    async def preview(self, request: TestLabPreviewRequest) -> dict[str, object]:
        """Run the admin preview through the same Data Plane Gateway as clients."""
        if not self._gateway_url or not self._gateway_credential:
            raise TestLabError("gateway_configuration_missing")
        target_model = self._run_target_model(request)
        data = self._decode(request.media_base64)
        asset_id: str | None = None
        try:
            asset_id = await self._gateway.upload(
                base_url=self._gateway_url,
                credential=self._gateway_credential,
                data=data,
                filename=request.filename,
                declared_mime=request.declared_mime,
            )
            result = await self._gateway.responses(
                base_url=self._gateway_url,
                credential=self._gateway_credential,
                payload=self._responses_payload(request, asset_id, target_model),
            )
        except GatewayClientError as error:
            raise TestLabError(error.code) from error
        finally:
            if asset_id is not None:
                try:
                    await self._gateway.delete(
                        base_url=self._gateway_url,
                        credential=self._gateway_credential,
                        asset_id=asset_id,
                    )
                except GatewayClientError:
                    logger.exception("test lab preview asset cleanup failed")
        return {
            "ok": True,
            "routingProfile": {"id": str(request.routing_profile_id), "targetModel": target_model},
            "gateway": {"baseUrl": self._gateway_url, "execution": "data-plane"},
            "response": result,
        }
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

    async def run(self, request: TestLabRunRequest) -> dict[str, object]:
        if request.gateway_url is None or request.api_key is None:
            raise TestLabError("downstream_credentials_required")
        target_model = self._run_target_model(request)
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

    def _run_target_model(self, request: TestLabRunRequest) -> str:
        """Resolve the selected route's downstream model for the external hop.

        The UI deliberately sends ``auto`` so the OmniRoute test exercises the
        same routing profile selected in the existing whole-pipeline test.
        """
        if request.target_model != "auto":
            return request.target_model
        if request.routing_profile_id is None:
            raise TestLabError("routing_profile_required")
        _, _, llm = self._providers(request.routing_profile_id)
        if not llm.model_id:
            raise TestLabError("routing_model_unavailable")
        return llm.model_id

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
        target_model: str,
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
            "model": target_model,
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
