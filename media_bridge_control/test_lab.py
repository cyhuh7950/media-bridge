"""Memory-only Control Plane orchestration for preview and opt-in test calls."""

from __future__ import annotations

import base64
import binascii
import threading
import time
from collections import deque
from typing import Any
from uuid import UUID

import anyio

from media_bridge_control.connections import ConnectionService, ConnectionServiceError
from media_bridge_control.gateway_client import GatewayClient, GatewayClientError
from media_bridge_control.schemas import TestLabPreviewRequest, TestLabRunRequest
from media_bridge_control.secrets import GatewaySecretResolver, SecretResolutionError


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
        connections: ConnectionService,
        gateway_client: GatewayClient,
        secret_resolver: GatewaySecretResolver,
    ) -> None:
        self._connections = connections
        self._gateway = gateway_client
        self._secrets = secret_resolver

    async def preview(self, request: TestLabPreviewRequest) -> dict[str, object]:
        connection, credential = await self._connection(request.connection_id)
        data = self._decode(request.media_base64)
        asset_id: str | None = None
        primary_error: TestLabError | None = None
        result: dict[str, object] | None = None
        try:
            asset_id = await self._gateway.upload(
                base_url=connection.gateway_url,
                credential=credential,
                data=data,
                filename=request.filename,
                declared_mime=request.declared_mime,
            )
            result = await self._gateway.prepare(
                base_url=connection.gateway_url,
                credential=credential,
                payload=self._prepare_payload(request, asset_id),
            )
        except GatewayClientError as error:
            primary_error = TestLabError(error.code)
        finally:
            if asset_id is not None:
                try:
                    await self._gateway.delete(
                        base_url=connection.gateway_url,
                        credential=credential,
                        asset_id=asset_id,
                    )
                except GatewayClientError as error:
                    if primary_error is None:
                        primary_error = TestLabError(error.code)
            credential = ""
        if primary_error is not None:
            raise primary_error
        if result is None:
            raise TestLabError("gateway_unavailable")
        return result

    async def run(self, request: TestLabRunRequest) -> dict[str, object]:
        connection, credential = await self._connection(request.connection_id)
        data = self._decode(request.media_base64)
        asset_id: str | None = None
        primary_error: TestLabError | None = None
        result: dict[str, object] | None = None
        try:
            asset_id = await self._gateway.upload(
                base_url=connection.gateway_url,
                credential=credential,
                data=data,
                filename=request.filename,
                declared_mime=request.declared_mime,
            )
            result = await self._gateway.responses(
                base_url=connection.gateway_url,
                credential=credential,
                payload=self._responses_payload(request, asset_id),
            )
        except GatewayClientError as error:
            primary_error = TestLabError(error.code)
        finally:
            if asset_id is not None:
                try:
                    await self._gateway.delete(
                        base_url=connection.gateway_url,
                        credential=credential,
                        asset_id=asset_id,
                    )
                except GatewayClientError as error:
                    if primary_error is None:
                        primary_error = TestLabError(error.code)
            credential = ""
        if primary_error is not None:
            raise primary_error
        if result is None:
            raise TestLabError("gateway_unavailable")
        return result

    async def _connection(self, connection_id: UUID) -> tuple[Any, str]:
        try:
            connection = await anyio.to_thread.run_sync(
                self._connections.runtime,
                str(connection_id),
            )
        except ConnectionServiceError as error:
            raise TestLabError(error.code) from error
        if not connection.enabled or connection.revoked:
            raise TestLabError("connection_unavailable")
        try:
            credential = self._secrets.resolve(
                self._connections.secret_reference(connection)
            )
        except SecretResolutionError as error:
            raise TestLabError(error.code) from error
        return connection, credential

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
            "model": request.target_model,
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
