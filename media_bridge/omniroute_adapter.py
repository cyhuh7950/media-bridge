"""Receipt-guarded, bounded OmniRoute Responses downstream adapter."""

from __future__ import annotations

import json
import re
import secrets
from typing import cast
from urllib.parse import urlsplit

import httpx

from media_bridge.backends import SecretConfigurationError, load_secret
from media_bridge.receipts import GateReceiptSigner, ReceiptValidationError
from media_bridge_gateway.contracts import (
    DownstreamError,
    DownstreamGuardError,
    GatewayResponse,
    SealedGatewayRequest,
)
from media_bridge_gateway.normalizer import digest_gateway_payload

_RESPONSE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class OmniRouteGuardError(DownstreamGuardError):
    """Raised before a network call when sealed payload evidence is invalid."""


class OmniRouteAdapterError(DownstreamError):
    """Backward-compatible OmniRoute-specific downstream error name."""


SealedResponsesRequest = SealedGatewayRequest
OmniRouteResponse = GatewayResponse


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest_responses_payload(payload: object) -> str:
    return digest_gateway_payload(payload)


def _contains_media_reference(value: object) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return lowered.startswith("data:image/") or lowered.startswith(
            "data:application/pdf"
        )
    if isinstance(value, list):
        return any(_contains_media_reference(item) for item in value)
    if not isinstance(value, dict):
        return False
    item = cast(dict[object, object], value)
    if item.get("type") in {"input_image", "input_file", "image_url"}:
        return True
    for key in ("image_url", "file_data", "file_id", "file_url", "asset_id"):
        locator = item.get(key)
        if isinstance(locator, str) and locator:
            return True
    return any(_contains_media_reference(child) for child in item.values())


def _validate_endpoint(endpoint: str) -> None:
    parsed = urlsplit(endpoint)
    is_https = parsed.scheme == "https"
    is_loopback_http = parsed.scheme == "http" and parsed.hostname in {
        "127.0.0.1",
        "::1",
        "localhost",
    }
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("OmniRoute endpoint is invalid") from error
    if (
        not (is_https or is_loopback_http)
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/v1/responses"
        or parsed.query
        or parsed.fragment
        or port == 0
    ):
        raise ValueError("OmniRoute endpoint is invalid")


def _extract_json_response_id(body: bytes) -> str | None:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    response_id = payload.get("id")
    return response_id if isinstance(response_id, str) else None


def _extract_sse_response_id(body: bytes) -> str | None:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        direct_id = event.get("id")
        if isinstance(direct_id, str):
            return direct_id
        response = event.get("response")
        if isinstance(response, dict) and isinstance(response.get("id"), str):
            return cast(str, response["id"])
    return None


class GuardedOmniRouteAdapter:
    """Verify a sealed Responses payload immediately before opening the socket."""

    def __init__(
        self,
        *,
        endpoint: str,
        receipt_signer: GateReceiptSigner,
        api_key_env: str = "MEDIA_BRIDGE_OMNIROUTE_API_KEY",
        api_key_file_env: str | None = "MEDIA_BRIDGE_OMNIROUTE_API_KEY_FILE",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 60.0,
        max_request_bytes: int = 4 * 1024 * 1024,
        max_response_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        _validate_endpoint(endpoint)
        if timeout_seconds <= 0 or min(max_request_bytes, max_response_bytes) < 1:
            raise ValueError("OmniRoute adapter limits are invalid")
        self._endpoint = endpoint
        self._receipt_signer = receipt_signer
        self._api_key_env = api_key_env
        self._api_key_file_env = api_key_file_env
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def invoke(self, sealed: SealedResponsesRequest) -> OmniRouteResponse:
        self._verify_seal(sealed)
        try:
            body = _canonical_json(sealed.payload)
        except (TypeError, ValueError, OverflowError) as error:
            raise OmniRouteGuardError("downstream payload is not valid JSON") from error
        if len(body) > self._max_request_bytes:
            raise OmniRouteGuardError("downstream payload exceeds the request limit")
        try:
            secret = load_secret(self._api_key_env, self._api_key_file_env)
        except SecretConfigurationError as error:
            raise OmniRouteAdapterError(
                "omniroute_configuration",
                "OmniRoute credentials are not configured.",
                http_status=500,
            ) from error

        try:
            async with self._client.stream(
                "POST",
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {secret}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                content=body,
            ) as response:
                if 300 <= response.status_code < 400:
                    raise OmniRouteAdapterError(
                        "omniroute_redirect",
                        "OmniRoute redirects are not permitted.",
                    )
                if response.status_code >= 400:
                    code = (
                        "omniroute_authentication"
                        if response.status_code in {401, 403}
                        else "omniroute_rate_limit"
                        if response.status_code == 429
                        else "omniroute_upstream_http"
                    )
                    raise OmniRouteAdapterError(code, "OmniRoute rejected the request.")
                content_type = response.headers.get("content-type", "").partition(";")[0].strip()
                if content_type not in {"application/json", "text/event-stream"}:
                    raise OmniRouteAdapterError(
                        "omniroute_content_type",
                        "OmniRoute returned an unsupported content type.",
                    )
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > self._max_response_bytes:
                        raise OmniRouteAdapterError(
                            "omniroute_response_oversized",
                            "OmniRoute response exceeded the configured limit.",
                        )
                    chunks.append(chunk)
                response_body = b"".join(chunks)
        except OmniRouteAdapterError:
            raise
        except httpx.TimeoutException as error:
            raise OmniRouteAdapterError(
                "omniroute_timeout",
                "OmniRoute request timed out.",
            ) from error
        except httpx.RequestError as error:
            raise OmniRouteAdapterError(
                "omniroute_transport",
                "OmniRoute transport failed.",
            ) from error

        response_id = (
            _extract_json_response_id(response_body)
            if content_type == "application/json"
            else _extract_sse_response_id(response_body)
        )
        if response_id is None or not _RESPONSE_ID.fullmatch(response_id):
            raise OmniRouteAdapterError(
                "omniroute_response_invalid",
                "OmniRoute response did not contain a valid response identifier.",
            )
        return OmniRouteResponse(
            body=response_body,
            content_type=content_type,
            response_id=response_id,
            status_code=response.status_code,
        )

    def _verify_seal(self, sealed: SealedResponsesRequest) -> None:
        try:
            computed_digest = digest_responses_payload(sealed.payload)
        except (TypeError, ValueError, OverflowError) as error:
            raise OmniRouteGuardError("downstream payload digest could not be computed") from error
        if not secrets.compare_digest(computed_digest, sealed.output_digest):
            raise OmniRouteGuardError("downstream payload digest does not match the receipt")
        try:
            self._receipt_signer.verify(sealed.receipt, expected=sealed.binding)
        except ReceiptValidationError as error:
            raise OmniRouteGuardError("downstream payload has no valid receipt") from error
        if sealed.capability not in {"non_vision", "vision"}:
            raise OmniRouteGuardError("downstream capability is not active and exact")
        if sealed.action not in {"passthrough", "converted"}:
            raise OmniRouteGuardError("downstream action is not permitted")
        if sealed.action == "converted" and sealed.capability != "non_vision":
            raise OmniRouteGuardError("converted payload has an invalid capability boundary")
        if sealed.payload.get("model") != sealed.target_id:
            raise OmniRouteGuardError("downstream target does not match the sealed target")
        if sealed.payload.get("previous_response_id") is not None:
            raise OmniRouteGuardError("downstream payload contains server-side state")
        if sealed.payload.get("conversation") is not None:
            raise OmniRouteGuardError("downstream payload contains server-side conversation state")
        if sealed.capability == "non_vision" and _contains_media_reference(sealed.payload):
            raise OmniRouteGuardError("non-vision downstream payload contains media")
