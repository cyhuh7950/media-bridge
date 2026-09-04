"""Guarded OpenAI Responses to Solar Chat Completions adapter."""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import AsyncIterator
from typing import Any, cast
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


def _contains_media(value: object) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return lowered.startswith("data:image/") or lowered.startswith("data:application/pdf")
    if isinstance(value, list):
        return any(_contains_media(item) for item in value)
    if not isinstance(value, dict):
        return False
    item = cast(dict[object, object], value)
    if item.get("type") in {"input_image", "input_file", "image_url"}:
        return True
    return any(_contains_media(child) for child in item.values())


def _validate_endpoint(endpoint: str) -> None:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/v1/chat/completions"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Solar endpoint must be a credential-free HTTPS chat completions URL")


def _text_content(value: object) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
        raise DownstreamGuardError("Responses message text is empty")
    if not isinstance(value, list):
        raise DownstreamGuardError("Responses message content is unsupported")
    parts: list[str] = []
    for part in value:
        if not isinstance(part, dict) or part.get("type") not in {"input_text", "output_text"}:
            raise DownstreamGuardError("Responses message contains unsupported non-text content")
        part_text = part.get("text")
        if not isinstance(part_text, str) or not part_text.strip():
            raise DownstreamGuardError("Responses message text is empty")
        parts.append(part_text.strip())
    if not parts:
        raise DownstreamGuardError("Responses message content is empty")
    return "\n".join(parts)


def _chat_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    if payload.get("tools"):
        raise DownstreamGuardError("Solar personal runtime does not yet support Responses tools")
    messages: list[dict[str, str]] = []
    instructions = payload.get("instructions")
    if instructions is not None:
        if not isinstance(instructions, str) or not instructions.strip():
            raise DownstreamGuardError("Responses instructions are invalid")
        messages.append({"role": "system", "content": instructions.strip()})
    input_value = payload.get("input")
    if isinstance(input_value, str):
        messages.append({"role": "user", "content": _text_content(input_value)})
    elif isinstance(input_value, list):
        for item in input_value:
            if not isinstance(item, dict) or item.get("type", "message") != "message":
                raise DownstreamGuardError("Responses input item is unsupported")
            role = item.get("role")
            if role not in {"user", "assistant", "system", "developer"}:
                raise DownstreamGuardError("Responses message role is unsupported")
            chat_role = "system" if role == "developer" else cast(str, role)
            messages.append({"role": chat_role, "content": _text_content(item.get("content"))})
    else:
        raise DownstreamGuardError("Responses input is missing or unsupported")
    if not messages:
        raise DownstreamGuardError("Responses input is empty")
    return messages


def _response_payload(
    *,
    response_id: str,
    message_id: str,
    model: str,
    text: str,
    usage: dict[str, int],
    status: str = "completed",
) -> dict[str, Any]:
    return {
        "id": response_id,
        "object": "response",
        "created_at": int(time.time()),
        "status": status,
        "model": model,
        "output": [
            {
                "id": message_id,
                "type": "message",
                "status": status,
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                        "annotations": [],
                    }
                ],
            }
        ],
        "usage": usage,
    }


def _sse_event(event_type: str, payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_type}\ndata: {body}\n\n".encode()


class SolarResponsesDownstream:
    """Translate a sealed text-only Responses request into a Solar chat request."""

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        receipt_signer: GateReceiptSigner,
        api_key_env: str = "SOLAR_API_KEY",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 60.0,
        max_request_bytes: int = 4 * 1024 * 1024,
        max_response_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        _validate_endpoint(endpoint)
        if (
            not model.strip()
            or timeout_seconds <= 0
            or min(max_request_bytes, max_response_bytes) < 1
        ):
            raise ValueError("Solar personal downstream configuration is invalid")
        self._endpoint = endpoint
        self._model = model
        self._receipt_signer = receipt_signer
        self._api_key_env = api_key_env
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

    async def invoke(self, sealed: SealedGatewayRequest) -> GatewayResponse:
        self._verify_seal(sealed)
        messages = _chat_messages(sealed.payload)
        solar_payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
        }
        encoded = json.dumps(
            solar_payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
        if len(encoded) > self._max_request_bytes:
            raise DownstreamGuardError("Solar request exceeded the configured limit")
        try:
            secret = load_secret(self._api_key_env, None)
        except SecretConfigurationError as error:
            raise DownstreamError(
                "solar_configuration",
                "Solar credentials are not configured.",
                http_status=500,
            ) from error
        try:
            response = await self._client.post(
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {secret}",
                    "Content-Type": "application/json",
                },
                content=encoded,
            )
        except httpx.TimeoutException as error:
            raise DownstreamError("solar_timeout", "Solar request timed out.") from error
        except httpx.RequestError as error:
            raise DownstreamError("solar_transport", "Solar request failed.") from error
        if response.status_code >= 400:
            code = (
                "solar_authentication"
                if response.status_code in {401, 403}
                else "solar_rate_limit"
                if response.status_code == 429
                else "solar_upstream_http"
            )
            raise DownstreamError(code, "Solar rejected the request.")
        content_type = response.headers.get("content-type", "").partition(";")[0].strip()
        if content_type != "application/json" or len(response.content) > self._max_response_bytes:
            raise DownstreamError("solar_response_invalid", "Solar returned an invalid response.")
        try:
            solar_response = response.json()
            choice = solar_response["choices"][0]
            text = choice["message"]["content"].strip()
        except (KeyError, IndexError, TypeError, AttributeError, ValueError) as error:
            raise DownstreamError(
                "solar_response_invalid",
                "Solar returned an invalid response.",
            ) from error
        if not text:
            raise DownstreamError("solar_response_invalid", "Solar returned an empty response.")
        usage_source = solar_response.get("usage", {})
        try:
            if not isinstance(usage_source, dict):
                raise TypeError("usage must be an object")
            usage = {
                "input_tokens": int(usage_source.get("prompt_tokens", 0)),
                "output_tokens": int(usage_source.get("completion_tokens", 0)),
                "total_tokens": int(usage_source.get("total_tokens", 0)),
            }
        except (TypeError, ValueError, OverflowError) as error:
            raise DownstreamError(
                "solar_response_invalid",
                "Solar returned an invalid response.",
            ) from error
        response_id = f"resp_mb_{secrets.token_urlsafe(12)}"
        message_id = f"msg_mb_{secrets.token_urlsafe(12)}"
        body_payload = _response_payload(
            response_id=response_id,
            message_id=message_id,
            model=self._model,
            text=text,
            usage=usage,
        )
        if sealed.payload.get("stream") is True:
            return GatewayResponse(
                body=b"",
                content_type="text/event-stream",
                response_id=response_id,
                status_code=200,
                stream=self._stream(
                    response_id=response_id,
                    message_id=message_id,
                    text=text,
                    completed=body_payload,
                ),
            )
        return GatewayResponse(
            body=json.dumps(body_payload, ensure_ascii=False, separators=(",", ":")).encode(),
            content_type="application/json",
            response_id=response_id,
            status_code=200,
        )

    async def _stream(
        self,
        *,
        response_id: str,
        message_id: str,
        text: str,
        completed: dict[str, Any],
    ) -> AsyncIterator[bytes]:
        created = {**completed, "status": "in_progress", "output": []}
        item = {
            "id": message_id,
            "type": "message",
            "status": "in_progress",
            "role": "assistant",
            "content": [],
        }
        part = {"type": "output_text", "text": "", "annotations": []}
        yield _sse_event("response.created", {"type": "response.created", "response": created})
        yield _sse_event(
            "response.output_item.added",
            {"type": "response.output_item.added", "output_index": 0, "item": item},
        )
        yield _sse_event(
            "response.content_part.added",
            {
                "type": "response.content_part.added",
                "item_id": message_id,
                "output_index": 0,
                "content_index": 0,
                "part": part,
            },
        )
        yield _sse_event(
            "response.output_text.delta",
            {
                "type": "response.output_text.delta",
                "item_id": message_id,
                "output_index": 0,
                "content_index": 0,
                "delta": text,
            },
        )
        yield _sse_event(
            "response.output_text.done",
            {
                "type": "response.output_text.done",
                "item_id": message_id,
                "output_index": 0,
                "content_index": 0,
                "text": text,
            },
        )
        completed_part = {"type": "output_text", "text": text, "annotations": []}
        yield _sse_event(
            "response.content_part.done",
            {
                "type": "response.content_part.done",
                "item_id": message_id,
                "output_index": 0,
                "content_index": 0,
                "part": completed_part,
            },
        )
        completed_item = {
            **item,
            "status": "completed",
            "content": [completed_part],
        }
        yield _sse_event(
            "response.output_item.done",
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": completed_item,
            },
        )
        yield _sse_event(
            "response.completed",
            {"type": "response.completed", "response": completed},
        )
        yield b"data: [DONE]\n\n"

    def _verify_seal(self, sealed: SealedGatewayRequest) -> None:
        try:
            computed = digest_gateway_payload(
                {"payload": sealed.payload, "request_nonce": sealed.request_nonce}
            )
        except (TypeError, ValueError, OverflowError) as error:
            raise DownstreamGuardError("Solar payload digest could not be computed") from error
        if not secrets.compare_digest(computed, sealed.output_digest):
            raise DownstreamGuardError("Solar payload digest does not match the receipt")
        try:
            self._receipt_signer.verify(sealed.receipt, expected=sealed.binding)
        except ReceiptValidationError as error:
            raise DownstreamGuardError("Solar payload has no valid receipt") from error
        if sealed.capability != "non_vision" or sealed.action not in {"passthrough", "converted"}:
            raise DownstreamGuardError("Solar payload capability boundary is invalid")
        if sealed.payload.get("model") != sealed.target_id or sealed.target_id != self._model:
            raise DownstreamGuardError("Solar target does not match the sealed target")
        if _contains_media(sealed.payload):
            raise DownstreamGuardError("Solar payload contains media")
