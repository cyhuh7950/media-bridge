"""Bounded Control Plane client for the authenticated Gateway API."""

from __future__ import annotations

import re
from typing import Any, Protocol, cast

import httpx
from pydantic import ValidationError

from media_bridge.contracts import AssetSource, PrepareForModelResult

_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class GatewayClientError(RuntimeError):
    def __init__(self, code: str) -> None:
        safe_code = code if _SAFE_CODE.fullmatch(code) is not None else "gateway_unavailable"
        super().__init__(safe_code)
        self.code = safe_code


class GatewayClient(Protocol):
    async def status(self, *, base_url: str, credential: str) -> dict[str, object]: ...

    async def upload(
        self,
        *,
        base_url: str,
        credential: str,
        data: bytes,
        filename: str | None,
        declared_mime: str,
    ) -> str: ...

    async def prepare(
        self,
        *,
        base_url: str,
        credential: str,
        payload: dict[str, Any],
    ) -> dict[str, object]: ...

    async def responses(
        self,
        *,
        base_url: str,
        credential: str,
        payload: dict[str, Any],
    ) -> dict[str, object]: ...

    async def delete(
        self,
        *,
        base_url: str,
        credential: str,
        asset_id: str,
    ) -> None: ...


class HttpGatewayClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        max_response_bytes: int = 4 * 1024 * 1024,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0 or max_response_bytes < 1:
            raise ValueError("Gateway client limits must be positive")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_response_bytes = max_response_bytes
        self._transport = transport

    async def status(self, *, base_url: str, credential: str) -> dict[str, object]:
        payload = await self._request(
            "GET",
            f"{base_url}/status",
            credential=credential,
        )
        if payload.get("status") != "ready" or not isinstance(
            payload.get("snapshot_version"), int
        ):
            raise GatewayClientError("gateway_invalid_response")
        return payload

    async def upload(
        self,
        *,
        base_url: str,
        credential: str,
        data: bytes,
        filename: str | None,
        declared_mime: str,
    ) -> str:
        headers = {"content-type": declared_mime}
        if filename is not None:
            headers["x-filename"] = filename
        payload = await self._request(
            "POST",
            f"{base_url}/assets",
            credential=credential,
            headers=headers,
            content=data,
        )
        asset_id = payload.get("asset_id")
        if not isinstance(asset_id, str):
            raise GatewayClientError("gateway_invalid_response")
        try:
            return AssetSource(asset_id=asset_id).asset_id
        except ValidationError as error:
            raise GatewayClientError("gateway_invalid_response") from error

    async def prepare(
        self,
        *,
        base_url: str,
        credential: str,
        payload: dict[str, Any],
    ) -> dict[str, object]:
        response = await self._request(
            "POST",
            f"{base_url}/v1/prepare",
            credential=credential,
            json_body=payload,
        )
        try:
            return cast(
                dict[str, object],
                PrepareForModelResult.model_validate(response).model_dump(mode="json"),
            )
        except ValidationError as error:
            raise GatewayClientError("gateway_invalid_response") from error

    async def responses(
        self,
        *,
        base_url: str,
        credential: str,
        payload: dict[str, Any],
    ) -> dict[str, object]:
        response = await self._request(
            "POST",
            f"{base_url}/v1/responses",
            credential=credential,
            json_body=payload,
        )
        if not isinstance(response.get("id"), str):
            raise GatewayClientError("gateway_invalid_response")
        return response

    async def delete(
        self,
        *,
        base_url: str,
        credential: str,
        asset_id: str,
    ) -> None:
        try:
            safe_asset_id = AssetSource(asset_id=asset_id).asset_id
        except ValidationError as error:
            raise GatewayClientError("gateway_invalid_response") from error
        await self._request(
            "DELETE",
            f"{base_url}/assets/{safe_asset_id}",
            credential=credential,
            expect_empty=True,
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        credential: str,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        json_body: dict[str, Any] | None = None,
        expect_empty: bool = False,
    ) -> dict[str, object]:
        if (
            not credential.startswith("mbc_")
            or credential.strip() != credential
            or " " in credential
            or len(credential) > 160
        ):
            raise GatewayClientError("credential_invalid")
        request_headers = {
            "authorization": f"Bearer {credential}",
            "accept": "application/json",
            **(headers or {}),
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=False,
                trust_env=False,
                transport=self._transport,
            ) as client:
                response = await client.request(
                    method,
                    url,
                    headers=request_headers,
                    content=content,
                    json=json_body,
                )
        except httpx.HTTPError as error:
            raise GatewayClientError("gateway_unavailable") from error
        if response.is_redirect:
            raise GatewayClientError("gateway_redirect_rejected")
        if len(response.content) > self._max_response_bytes:
            raise GatewayClientError("gateway_response_too_large")
        if response.status_code >= 400:
            raise GatewayClientError(self._safe_error_code(response))
        if expect_empty:
            if response.status_code != 204 or response.content:
                raise GatewayClientError("gateway_invalid_response")
            return {}
        if response.headers.get("content-type", "").partition(";")[0] != "application/json":
            raise GatewayClientError("gateway_invalid_response")
        try:
            value = response.json()
        except ValueError as error:
            raise GatewayClientError("gateway_invalid_response") from error
        if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
            raise GatewayClientError("gateway_invalid_response")
        return cast(dict[str, object], value)

    @staticmethod
    def _safe_error_code(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return "gateway_unavailable"
        if not isinstance(body, dict):
            return "gateway_unavailable"
        error = body.get("error")
        if not isinstance(error, dict):
            return "gateway_unavailable"
        code = error.get("code")
        return code if isinstance(code, str) else "gateway_unavailable"
