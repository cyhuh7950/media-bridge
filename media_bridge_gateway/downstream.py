"""Receipt-guarded, bounded product-neutral Responses downstream."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Mapping
from typing import cast
from urllib.parse import urlsplit

import httpx

from media_bridge.backends import (
    AnalysisBackend,
    BackendStatus,
    SecretConfigurationError,
    load_secret,
)
from media_bridge.receipts import GateReceiptSigner, ReceiptValidationError
from media_bridge_gateway.contracts import (
    DownstreamError,
    DownstreamGuardError,
    GatewayResponse,
    SealedGatewayRequest,
)
from media_bridge_gateway.normalizer import digest_gateway_payload
from media_bridge_gateway.provider_selection import (
    ProviderRouteCandidate,
    ProviderSelectionError,
    select_provider,
)

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
        verify: bool | str = True,
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
            verify=verify,
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
        _verify_seal(sealed, self._receipt_signer)


def _verify_seal(sealed: SealedGatewayRequest, signer: GateReceiptSigner) -> None:
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
        signer.verify(sealed.receipt, expected=sealed.binding)
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


def _text_from_responses_payload(payload: dict[str, object]) -> str:
    input_value = payload.get("input")
    if isinstance(input_value, str):
        return input_value.strip()
    texts: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, dict):
            if value.get("type") == "input_text" and isinstance(value.get("text"), str):
                texts.append(value["text"])
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(input_value)
    return "\n\n".join(text.strip() for text in texts if text.strip())


class ProviderResponsesDownstream:
    """Resolve a model through one verified snapshot before text-only execution."""

    def __init__(
        self,
        *,
        receipt_signer: GateReceiptSigner,
        snapshot: Mapping[str, object] | None = None,
        backend_factory: Callable[[dict[str, object]], AnalysisBackend] | None = None,
        backend: AnalysisBackend | None = None,
        model: str | None = None,
    ) -> None:
        if snapshot is None and (backend is None or not model):
            raise ValueError("a snapshot resolver or legacy backend/model pair is required")
        if snapshot is not None and backend_factory is None:
            raise ValueError("snapshot downstream requires a backend factory")
        if snapshot is None and backend is not None and not model:
            raise ValueError("legacy downstream requires a model")
        self._snapshot = snapshot
        self._backend_factory = backend_factory
        self._backend = backend
        self._receipt_signer = receipt_signer
        self._model = model
        self._replay_guard = _ReceiptReplayGuard(
            clock=time.time,
            max_entries=100_000,
        )

    async def close(self) -> None:
        return None

    async def invoke(self, request: SealedGatewayRequest) -> GatewayResponse:
        _verify_seal(request, self._receipt_signer)
        self._replay_guard.consume(request.receipt)
        backend = self._backend
        output_model = self._model or request.target_id
        if self._snapshot is not None:
            provider = self._provider_for_target(request.target_id)
            requested_effort = request.payload.get("reasoning_effort")
            if requested_effort is None:
                defaults = self._snapshot.get("defaults")
                if isinstance(defaults, Mapping):
                    requested_effort = defaults.get("reasoning_effort")
            if requested_effort is not None:
                if requested_effort not in {"low", "medium", "high"}:
                    raise DownstreamError(
                        "reasoning_effort_invalid",
                        "The requested reasoning effort is invalid.",
                        http_status=400,
                    )
                provider = dict(provider)
                provider["reasoning_effort"] = requested_effort
            assert self._backend_factory is not None
            try:
                backend = self._backend_factory(provider)
            except (TypeError, ValueError) as error:
                raise DownstreamError(
                    "model_provider_unavailable",
                    "The configured Provider cannot serve this model.",
                ) from error
            output_model = request.target_id
        prompt = _text_from_responses_payload(request.payload)
        if not prompt:
            raise DownstreamError(
                "downstream_payload_invalid",
                "Downstream request did not contain text input.",
                http_status=400,
            )
        assert backend is not None
        result = await backend.analyze(context=prompt, user_request="")
        if result.status is not BackendStatus.SUCCESS or not result.analysis:
            code = result.error_code or "upstream"
            raise DownstreamError(
                f"downstream_{code}",
                "Configured Provider rejected the downstream request.",
            )
        response_id = f"resp_{secrets.token_urlsafe(18)}"
        body = _canonical_json(
            {
                "id": response_id,
                "object": "response",
                "model": output_model,
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": result.analysis}],
                    }
                ],
            }
        )
        return GatewayResponse(
            body=body,
            content_type="application/json",
            response_id=response_id,
            status_code=200,
        )

    def _provider_for_target(self, target_id: str) -> dict[str, object]:
        assert self._snapshot is not None
        registry = self._snapshot.get("registry")
        models = registry.get("models") if isinstance(registry, Mapping) else None
        providers = self._snapshot.get("providers")
        if not isinstance(models, list) or not isinstance(providers, list):
            raise DownstreamError(
                "model_provider_unavailable",
                "No unique Provider is configured for the target model.",
            )
        model_matches: list[Mapping[str, object]] = []
        for item in models:
            if not isinstance(item, Mapping):
                continue
            aliases = item.get("aliases", [])
            if item.get("id") == target_id or (
                isinstance(aliases, list) and target_id in aliases
            ):
                model_matches.append(item)
        if len(model_matches) != 1:
            raise DownstreamError(
                "model_provider_unavailable",
                "No unique Provider is configured for the target model.",
            )
        model = model_matches[0]
        routing_profile_id = model.get("routing_profile_id")
        routing_profiles = self._snapshot.get("routing_profiles")
        if not isinstance(routing_profile_id, str) and isinstance(routing_profiles, list):
            default_profile = next(
                (
                    item
                    for item in routing_profiles
                    if isinstance(item, Mapping) and item.get("enabled") is not False
                ),
                None,
            )
            if isinstance(default_profile, Mapping):
                routing_profile_id = default_profile.get("id")
        provider_ids = {
            item.get("provider_id")
            for item in model_matches
            if isinstance(item.get("provider_id"), str)
        }
        if isinstance(routing_profile_id, str) and isinstance(routing_profiles, list):
            profile = next(
                (
                    item
                    for item in routing_profiles
                    if isinstance(item, Mapping) and item.get("id") == routing_profile_id
                ),
                None,
            )
            if isinstance(profile, Mapping) and isinstance(profile.get("llm_provider_ids"), list):
                provider_ids = {
                    item for item in profile["llm_provider_ids"] if isinstance(item, str)
                }
        provider_matches = [
            item
            for item in providers
            if isinstance(item, dict)
            and item.get("id") in provider_ids
            and item.get("kind") == "llm"
            and item.get("enabled") is True
        ]
        if not provider_matches:
            raise DownstreamError(
                "model_provider_unavailable",
                "No unique Provider is configured for the target model.",
            )
        strategy = "priority"
        if isinstance(routing_profile_id, str) and isinstance(routing_profiles, list):
            profile = next(
                (
                    item
                    for item in routing_profiles
                    if isinstance(item, Mapping) and item.get("id") == routing_profile_id
                ),
                None,
            )
            if isinstance(profile, Mapping) and profile.get("strategy") in {
                "priority", "fallback", "health", "cost"
            }:
                strategy = cast(str, profile["strategy"])
        try:
            chosen = select_provider(
                [
                    ProviderRouteCandidate(
                        provider_id=str(item["id"]),
                        enabled=bool(item.get("enabled")),
                        capabilities=frozenset(
                            item.get("capabilities", [])
                            or (["text"] if item.get("kind") == "llm" else [])
                        ),
                    )
                    for item in provider_matches
                ],
                required_capability="text",
                strategy=strategy,  # type: ignore[arg-type]
            )
        except ProviderSelectionError as error:
            raise DownstreamError(
                "model_provider_unavailable",
                "No healthy Provider can serve this model.",
            ) from error
        provider = next(item for item in provider_matches if str(item["id"]) == chosen.provider_id)
        if not all(
            isinstance(provider.get(key), str) and provider[key]
            for key in ("catalog_id", "protocol", "endpoint", "model_id")
        ):
            raise DownstreamError(
                "model_provider_unavailable",
                "No unique Provider is configured for the target model.",
            )
        return cast(dict[str, object], provider)
