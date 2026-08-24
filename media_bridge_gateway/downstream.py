"""Receipt-guarded, bounded product-neutral Responses downstream."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
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
_REQUEST_NONCE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


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
        raise ValueError("Responses downstream endpoint is invalid") from error
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
        raise ValueError("Responses downstream endpoint is invalid")


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


class _ReceiptReplayGuard:
    def __init__(
        self,
        *,
        clock: Callable[[], float],
        max_entries: int,
        retention_seconds: float = 300.0,
    ) -> None:
        if max_entries < 1 or retention_seconds <= 0:
            raise ValueError("receipt replay settings must be positive")
        self._clock = clock
        self._max_entries = max_entries
        self._retention_seconds = retention_seconds
        self._lock = threading.Lock()
        self._used: OrderedDict[str, float] = OrderedDict()

    def consume(self, receipt: str) -> None:
        now = self._clock()
        digest = hashlib.sha256(receipt.encode()).hexdigest()
        with self._lock:
            expired = [key for key, expires_at in self._used.items() if expires_at <= now]
            for key in expired:
                self._used.pop(key, None)
            if digest in self._used:
                raise DownstreamGuardError("sealed receipt replay was rejected")
            if len(self._used) >= self._max_entries:
                raise DownstreamGuardError("receipt replay state is at capacity")
            self._used[digest] = now + self._retention_seconds


class GuardedResponsesDownstream:
    """Verify a sealed Responses payload immediately before opening the socket."""

    def __init__(
        self,
        *,
        endpoint: str,
        receipt_signer: GateReceiptSigner,
        api_key_env: str = "MEDIA_BRIDGE_DOWNSTREAM_API_KEY",
        api_key_file_env: str | None = "MEDIA_BRIDGE_DOWNSTREAM_API_KEY_FILE",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 60.0,
        max_request_bytes: int = 4 * 1024 * 1024,
        max_response_bytes: int = 8 * 1024 * 1024,
        error_prefix: str = "downstream",
        replay_clock: Callable[[], float] = time.time,
        max_replay_entries: int = 100_000,
    ) -> None:
        _validate_endpoint(endpoint)
        if timeout_seconds <= 0 or min(max_request_bytes, max_response_bytes) < 1:
            raise ValueError("Responses downstream limits are invalid")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", error_prefix):
            raise ValueError("Responses downstream error prefix is invalid")
        self._endpoint = endpoint
        self._receipt_signer = receipt_signer
        self._api_key_env = api_key_env
        self._api_key_file_env = api_key_file_env
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes
        self._error_prefix = error_prefix
        self._replay_guard = _ReceiptReplayGuard(
            clock=replay_clock,
            max_entries=max_replay_entries,
        )
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def invoke(self, sealed: SealedGatewayRequest) -> GatewayResponse:
        self._verify_seal(sealed)
        try:
            body = _canonical_json(sealed.payload)
        except (TypeError, ValueError, OverflowError) as error:
            raise DownstreamGuardError("downstream payload is not valid JSON") from error
        if len(body) > self._max_request_bytes:
            raise DownstreamGuardError("downstream payload exceeds the request limit")
        try:
            secret = load_secret(self._api_key_env, self._api_key_file_env)
        except SecretConfigurationError as error:
            raise DownstreamError(
                f"{self._error_prefix}_configuration",
                "Downstream credentials are not configured.",
                http_status=500,
            ) from error

        self._replay_guard.consume(sealed.receipt)

        request = self._client.build_request(
            "POST",
            self._endpoint,
            headers={
                "Authorization": f"Bearer {secret}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            content=body,
        )
        try:
            response = await self._client.send(request, stream=True)
        except httpx.TimeoutException as error:
            raise DownstreamError(
                f"{self._error_prefix}_timeout",
                "Downstream request timed out.",
            ) from error
        except httpx.RequestError as error:
            raise DownstreamError(
                f"{self._error_prefix}_transport",
                "Downstream transport failed.",
            ) from error
        try:
            self._validate_response_metadata(response)
            content_type = response.headers.get("content-type", "").partition(";")[0].strip()
            if content_type == "text/event-stream":
                return await self._streaming_response(response)
            response_body = await self._read_bounded(response)
            response_id = _extract_json_response_id(response_body)
            if response_id is None or not _RESPONSE_ID.fullmatch(response_id):
                raise self._invalid_response()
            await response.aclose()
            return GatewayResponse(
                body=response_body,
                content_type=content_type,
                response_id=response_id,
                status_code=response.status_code,
            )
        except httpx.TimeoutException as error:
            await response.aclose()
            raise DownstreamError(
                f"{self._error_prefix}_timeout",
                "Downstream request timed out.",
            ) from error
        except httpx.RequestError as error:
            await response.aclose()
            raise DownstreamError(
                f"{self._error_prefix}_transport",
                "Downstream transport failed.",
            ) from error
        except BaseException:
            await response.aclose()
            raise

    def _validate_response_metadata(self, response: httpx.Response) -> None:
        if 300 <= response.status_code < 400:
            raise DownstreamError(
                f"{self._error_prefix}_redirect",
                "Downstream redirects are not permitted.",
            )
        if response.status_code >= 400:
            code = (
                f"{self._error_prefix}_authentication"
                if response.status_code in {401, 403}
                else f"{self._error_prefix}_rate_limit"
                if response.status_code == 429
                else f"{self._error_prefix}_upstream_http"
            )
            raise DownstreamError(code, "Downstream rejected the request.")
        content_type = response.headers.get("content-type", "").partition(";")[0].strip()
        if content_type not in {"application/json", "text/event-stream"}:
            raise DownstreamError(
                f"{self._error_prefix}_content_type",
                "Downstream returned an unsupported content type.",
            )

    async def _read_bounded(self, response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self._max_response_bytes:
                raise DownstreamError(
                    f"{self._error_prefix}_response_oversized",
                    "Downstream response exceeded the configured limit.",
                )
            chunks.append(chunk)
        return b"".join(chunks)

    async def _streaming_response(self, response: httpx.Response) -> GatewayResponse:
        iterator = response.aiter_bytes()
        buffered: list[bytes] = []
        total = 0
        response_id: str | None = None
        try:
            while response_id is None:
                chunk = await anext(iterator)
                total += len(chunk)
                if total > min(self._max_response_bytes, 64 * 1024):
                    raise self._invalid_response()
                buffered.append(chunk)
                response_id = _extract_sse_response_id(b"".join(buffered))
        except StopAsyncIteration as error:
            raise self._invalid_response() from error
        if not _RESPONSE_ID.fullmatch(response_id):
            raise self._invalid_response()

        async def stream_body() -> AsyncIterator[bytes]:
            nonlocal total
            try:
                for prefix in buffered:
                    yield prefix
                async for chunk in iterator:
                    total += len(chunk)
                    if total > self._max_response_bytes:
                        raise DownstreamError(
                            f"{self._error_prefix}_response_oversized",
                            "Downstream response exceeded the configured limit.",
                        )
                    yield chunk
            except httpx.TimeoutException as error:
                raise DownstreamError(
                    f"{self._error_prefix}_timeout",
                    "Downstream request timed out.",
                ) from error
            except httpx.RequestError as error:
                raise DownstreamError(
                    f"{self._error_prefix}_transport",
                    "Downstream transport failed.",
                ) from error
            finally:
                await response.aclose()

        return GatewayResponse(
            body=b"",
            content_type="text/event-stream",
            response_id=response_id,
            status_code=response.status_code,
            stream=stream_body(),
        )

    def _invalid_response(self) -> DownstreamError:
        return DownstreamError(
            f"{self._error_prefix}_response_invalid",
            "Downstream response did not contain a valid response identifier.",
        )

    def _verify_seal(self, sealed: SealedGatewayRequest) -> None:
        if _REQUEST_NONCE.fullmatch(sealed.request_nonce) is None:
            raise DownstreamGuardError("downstream request nonce is invalid")
        try:
            computed_digest = digest_gateway_payload(
                {
                    "payload": sealed.payload,
                    "request_nonce": sealed.request_nonce,
                }
            )
        except (TypeError, ValueError, OverflowError) as error:
            raise DownstreamGuardError("downstream payload digest could not be computed") from error
        if not secrets.compare_digest(computed_digest, sealed.output_digest):
            raise DownstreamGuardError("downstream payload digest does not match the receipt")
        try:
            self._receipt_signer.verify(sealed.receipt, expected=sealed.binding)
        except ReceiptValidationError as error:
            raise DownstreamGuardError("downstream payload has no valid receipt") from error
        if sealed.capability not in {"non_vision", "vision"}:
            raise DownstreamGuardError("downstream capability is not active and exact")
        if sealed.action not in {"passthrough", "converted"}:
            raise DownstreamGuardError("downstream action is not permitted")
        if sealed.action == "converted" and sealed.capability != "non_vision":
            raise DownstreamGuardError("converted payload has an invalid capability boundary")
        if sealed.payload.get("model") != sealed.target_id:
            raise DownstreamGuardError("downstream target does not match the sealed target")
        if sealed.payload.get("previous_response_id") is not None:
            raise DownstreamGuardError("downstream payload contains server-side state")
        if sealed.payload.get("conversation") is not None:
            raise DownstreamGuardError("downstream payload contains server-side conversation state")
        if sealed.capability == "non_vision" and _contains_media_reference(sealed.payload):
            raise DownstreamGuardError("non-vision downstream payload contains media")
