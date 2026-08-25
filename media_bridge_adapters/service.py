"""Resolved-target preparation without importing Core or database internals."""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import hmac
import json
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import ValidationError

from media_bridge_adapters.contracts import (
    AdapterSafeError,
    GatewayPrepareResponse,
    PreUpstreamRequest,
    PreUpstreamResult,
)
from media_bridge_adapters.http_client import GatewayPrepareError

_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp"}


class GatewayPrepare(Protocol):
    async def prepare(self, payload: dict[str, Any]) -> object: ...


class AdapterNormalizationError(ValueError):
    pass


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _media_reference(value: object) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return lowered.startswith("data:image/") or lowered.startswith("data:application/pdf")
    if isinstance(value, list):
        return any(_media_reference(item) for item in value)
    if not isinstance(value, dict):
        return False
    if value.get("type") in {"input_image", "input_file", "image_url"}:
        return True
    locator_keys = ("image_url", "file_data", "asset_id", "file_id", "file_url")
    if any(isinstance(value.get(key), str) and value[key] for key in locator_keys):
        return True
    return any(_media_reference(item) for item in value.values())


def _base64_source(locator: str, allowed_mimes: set[str]) -> tuple[str, str]:
    if not locator.startswith("data:") or ";base64," not in locator:
        raise AdapterNormalizationError
    header, encoded = locator.split(",", 1)
    mime = header.removeprefix("data:").removesuffix(";base64")
    if header != f"data:{mime};base64" or mime not in allowed_mimes or not encoded:
        raise AdapterNormalizationError
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise AdapterNormalizationError from error
    if not raw or len(raw) > 2 * 1024 * 1024:
        raise AdapterNormalizationError
    return mime, encoded


def _image_part(part: dict[str, Any]) -> dict[str, Any]:
    asset_id = part.get("asset_id")
    locator = part.get("image_url")
    if isinstance(asset_id, str) and locator is None:
        return {
            "type": "media",
            "media_type": "image",
            "source": {"kind": "asset_id", "asset_id": asset_id},
        }
    if not isinstance(locator, str):
        raise AdapterNormalizationError
    if locator.startswith("data:"):
        mime, encoded = _base64_source(locator, _IMAGE_MIMES)
        return {
            "type": "media",
            "media_type": "image",
            "source": {"kind": "base64", "data": encoded},
            "declared_mime": mime,
        }
    parsed = urlsplit(locator)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise AdapterNormalizationError
    return {"type": "media", "media_type": "image", "source": {"kind": "url", "url": locator}}


def _file_part(part: dict[str, Any]) -> dict[str, Any]:
    asset_id = part.get("asset_id")
    locator = part.get("file_data")
    common: dict[str, Any] = {
        "type": "media",
        "media_type": "pdf",
        "declared_mime": "application/pdf",
    }
    if isinstance(part.get("filename"), str):
        common["filename"] = part["filename"]
    if isinstance(asset_id, str) and locator is None:
        return {**common, "source": {"kind": "asset_id", "asset_id": asset_id}}
    if not isinstance(locator, str):
        raise AdapterNormalizationError
    _mime, encoded = _base64_source(locator, {"application/pdf"})
    return {**common, "source": {"kind": "base64", "data": encoded}}


def _current_message(body: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
    value = body.get("input")
    if isinstance(value, str) and value:
        return [{"type": "text", "text": value}], None
    if not isinstance(value, list) or not value:
        raise AdapterNormalizationError
    user_indices = [
        index
        for index, item in enumerate(value)
        if isinstance(item, dict) and item.get("role") == "user"
    ]
    if not user_indices:
        raise AdapterNormalizationError
    current_index = user_indices[-1]
    if any(_media_reference(item) for index, item in enumerate(value) if index != current_index):
        raise AdapterNormalizationError
    current = value[current_index]
    if not isinstance(current, dict) or not isinstance(current.get("content"), list):
        raise AdapterNormalizationError
    output: list[dict[str, Any]] = []
    for raw in current["content"]:
        if not isinstance(raw, dict):
            raise AdapterNormalizationError
        kind = raw.get("type")
        if kind == "input_text" and isinstance(raw.get("text"), str):
            output.append({"type": "text", "text": raw["text"]})
        elif kind == "input_image":
            output.append(_image_part(raw))
        elif kind == "input_file":
            output.append(_file_part(raw))
        else:
            raise AdapterNormalizationError
    return output, current_index


def _prepare_payload(request: PreUpstreamRequest) -> tuple[dict[str, Any], int | None]:
    for key, value in request.body.items():
        if key != "input" and _media_reference(value):
            raise AdapterNormalizationError
    content, current_index = _current_message(request.body)
    profile = "document" if any(part.get("media_type") == "pdf" for part in content) else "generic"
    return {
        "content": content,
        "target": {"registry_id": request.target_model},
        "conversion_profile": profile,
    }, current_index


def _rewritten_body(
    request: PreUpstreamRequest,
    text: str,
    current_index: int | None,
) -> dict[str, Any]:
    body = copy.deepcopy(request.body)
    body.pop("previous_response_id", None)
    body.pop("conversation", None)
    body["model"] = request.target_model
    if current_index is None:
        body["input"] = text
        return body
    items = body.get("input")
    if not isinstance(items, list) or not isinstance(items[current_index], dict):
        raise AdapterNormalizationError
    items[current_index] = {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": text}],
    }
    return body


class PreUpstreamService:
    def __init__(self, *, gateway: GatewayPrepare, decision_secret: bytes) -> None:
        if len(decision_secret) < 32:
            raise ValueError("Adapter decision secret must be at least 32 bytes")
        self._gateway = gateway
        self._decision_secret = bytes(decision_secret)

    def _blocked(self, request: PreUpstreamRequest, code: str, message: str) -> PreUpstreamResult:
        return PreUpstreamResult(
            status="blocked",
            provider=request.provider,
            target_model=request.target_model,
            capability=None,
            body=None,
            original_media_removed=False,
            input_digest=None,
            output_digest=None,
            decision_token=None,
            error=AdapterSafeError(code=code, message=message),
        )

    async def prepare(self, request: PreUpstreamRequest) -> PreUpstreamResult:
        try:
            payload, current_index = _prepare_payload(request)
            raw_result = await self._gateway.prepare(payload)
            if hasattr(raw_result, "model_dump"):
                raw_result = raw_result.model_dump(mode="json")
            gateway_result = GatewayPrepareResponse.model_validate(raw_result)
        except AdapterNormalizationError:
            return self._blocked(
                request,
                "invalid_request",
                "Request media could not be normalized safely.",
            )
        except GatewayPrepareError as error:
            return self._blocked(
                request,
                error.code,
                "Media Bridge Gateway did not prepare the request.",
            )
        except (ValidationError, TypeError, ValueError):
            return self._blocked(
                request,
                "gateway_invalid_response",
                "Media Bridge Gateway returned an invalid decision.",
            )
        if gateway_result.target_model != request.target_model:
            return self._blocked(
                request,
                "target_mismatch",
                "Prepared target did not match the resolved target.",
            )
        if gateway_result.action == "blocked" or gateway_result.target_supports_vision is None:
            code = gateway_result.error.code if gateway_result.error else "pre_request_blocked"
            return self._blocked(request, code, "Media Bridge Gateway blocked the request.")
        try:
            status: Literal["unchanged", "prepared"]
            if gateway_result.action == "converted":
                if not gateway_result.sanitized_text or not gateway_result.original_image_removed:
                    raise AdapterNormalizationError
                body = _rewritten_body(request, gateway_result.sanitized_text, current_index)
                capability: Literal["vision", "non_vision"] = "non_vision"
                status = "prepared"
                removed = True
            else:
                body = copy.deepcopy(request.body)
                body.pop("previous_response_id", None)
                body.pop("conversation", None)
                body["model"] = request.target_model
                capability = "vision" if gateway_result.target_supports_vision else "non_vision"
                status = "unchanged"
                removed = not gateway_result.contains_media
                if capability == "non_vision" and _media_reference(body):
                    raise AdapterNormalizationError
            input_digest = _digest(request.body)
            output_digest = _digest(body)
            signed = "\0".join(
                [
                    request.provider,
                    request.target_model,
                    capability,
                    status,
                    input_digest,
                    output_digest,
                    "1" if removed else "0",
                ]
            ).encode()
            signature = hmac.new(
                self._decision_secret,
                signed,
                hashlib.sha256,
            ).digest()
            token = base64.urlsafe_b64encode(signature).decode().rstrip("=")
            return PreUpstreamResult(
                status=status,
                provider=request.provider,
                target_model=request.target_model,
                capability=capability,
                body=body,
                original_media_removed=removed,
                input_digest=input_digest,
                output_digest=output_digest,
                decision_token=token,
                error=None,
            )
        except (AdapterNormalizationError, TypeError, ValueError):
            return self._blocked(
                request,
                "sanitization_failed",
                "Prepared request failed safety validation.",
            )
