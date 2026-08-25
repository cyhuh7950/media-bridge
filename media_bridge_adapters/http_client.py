"""Bounded no-redirect client for the documented Gateway prepare endpoint."""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from media_bridge_adapters.contracts import GatewayPrepareResponse

_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class GatewayPrepareError(RuntimeError):
    def __init__(self, code: str) -> None:
        safe_code = code if _SAFE_CODE.fullmatch(code) else "gateway_unavailable"
        super().__init__(safe_code)
        self.code = safe_code


def _validate_base_url(value: str) -> str:
    if value != value.strip() or value.endswith("/"):
        raise ValueError("Gateway base URL must be canonical")
    parsed = urlsplit(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise ValueError("Gateway base URL is invalid")
    if parsed.scheme == "https" and parsed.hostname:
        return value
    if parsed.scheme != "http" or not parsed.hostname:
        raise ValueError("Gateway base URL must use HTTPS or loopback HTTP")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        if parsed.hostname.lower() != "localhost":
            raise ValueError("Plain HTTP Gateway must use loopback") from None
    else:
        if not address.is_loopback:
            raise ValueError("Plain HTTP Gateway must use loopback")
    return value


class GatewayPrepareClient:
    def __init__(
        self,
        *,
        base_url: str,
        credential: str,
        timeout_seconds: float = 15.0,
        max_response_bytes: int = 512 * 1024,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        invalid_credential = (
            not credential.startswith("mbc_")
            or len(credential) > 160
            or credential.strip() != credential
        )
        if invalid_credential:
            raise ValueError("Gateway credential is invalid")
        if timeout_seconds <= 0 or max_response_bytes < 1:
            raise ValueError("Gateway client limits must be positive")
        self._base_url = _validate_base_url(base_url)
        self._credential = credential
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_response_bytes = max_response_bytes
        self._transport = transport

    async def prepare(self, payload: dict[str, Any]) -> GatewayPrepareResponse:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=False,
                trust_env=False,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    f"{self._base_url}/v1/prepare",
                    headers={
                        "authorization": f"Bearer {self._credential}",
                        "accept": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as error:
            raise GatewayPrepareError("gateway_unavailable") from error
        if response.is_redirect:
            raise GatewayPrepareError("gateway_redirect_rejected")
        if len(response.content) > self._max_response_bytes:
            raise GatewayPrepareError("gateway_response_too_large")
        if response.status_code >= 400:
            raise GatewayPrepareError("gateway_prepare_failed")
        if response.headers.get("content-type", "").partition(";")[0] != "application/json":
            raise GatewayPrepareError("gateway_invalid_response")
        try:
            return GatewayPrepareResponse.model_validate_json(response.content)
        except ValidationError as error:
            raise GatewayPrepareError("gateway_invalid_response") from error
