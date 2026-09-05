"""Strict OpenAI Responses request normalization into Media Bridge contracts."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Any, Literal, NoReturn, cast
from urllib.parse import urlsplit

from pydantic import ValidationError

from media_bridge.contracts import (
    AssetSource,
    Base64Source,
    MediaPart,
    PrepareForModelRequest,
    TargetModel,
    TextPart,
    UrlSource,
)
from media_bridge.responses_state import ResponsesStateRecord

_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp"}
_PDF_MIME = "application/pdf"
_MAX_MEDIA_BYTES = 2 * 1024 * 1024


class ResponsesNormalizationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


@dataclass(frozen=True, slots=True)
class NormalizedResponsesRequest:
    request: PrepareForModelRequest
    current_user_text: str
    input_had_media: bool
    previous_state: ResponsesStateRecord | None


def _raise(code: str, message: str) -> NoReturn:
    raise ResponsesNormalizationError(code, message)


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
    item_type = item.get("type")
    if isinstance(item_type, str) and item_type in {"input_image", "input_file", "image_url"}:
        return True
    for key in ("image_url", "file_data", "file_id", "file_url", "asset_id"):
        locator = item.get(key)
        if isinstance(locator, str) and locator:
            return True
    return any(_contains_media_reference(child) for child in item.values())


def _decode_data_uri(value: str, *, allowed_mimes: set[str]) -> tuple[str, str]:
    if not value.startswith("data:") or ";base64," not in value:
        _raise("unsupported_media_locator", "Media locator is not supported.")
    header, encoded = value.split(",", 1)
    mime_type = header.removeprefix("data:").removesuffix(";base64")
    if header != f"data:{mime_type};base64" or mime_type not in allowed_mimes or not encoded:
        _raise("unsupported_media_locator", "Media locator is not supported.")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        _raise("invalid_request", "Media data is not valid base64.")
    if not decoded or len(decoded) > _MAX_MEDIA_BYTES:
        _raise("invalid_request", "Media data is empty or oversized.")
    return mime_type, encoded


def _asset_source(value: str) -> AssetSource:
    try:
        return AssetSource(asset_id=value)
    except ValidationError:
        _raise("unsupported_media_locator", "Asset identifier is not supported.")


def _image_part(item: dict[str, Any]) -> MediaPart:
    if item.get("file_id") is not None or item.get("file_url") is not None:
        _raise("unsupported_media_locator", "Provider media identifiers are not supported.")
    if not set(item).issubset(
        {"type", "image_url", "asset_id", "detail", "file_id", "file_url"}
    ):
        _raise("invalid_request", "Image input contains unsupported fields.")
    detail = item.get("detail")
    if detail is not None and detail not in {"auto", "low", "high"}:
        _raise("invalid_request", "Image detail value is invalid.")
    asset_id = item.get("asset_id")
    locator = item.get("image_url")
    if asset_id is not None:
        if locator is not None or not isinstance(asset_id, str):
            _raise("unsupported_media_locator", "Image locator is not supported.")
        return MediaPart(media_type="image", source=_asset_source(asset_id))
    if not isinstance(locator, str):
        _raise("unsupported_media_locator", "Image locator is not supported.")
    if locator.startswith("data:"):
        mime_type, encoded = _decode_data_uri(locator, allowed_mimes=_IMAGE_MIMES)
        return MediaPart(
            media_type="image",
            source=Base64Source(data=encoded),
            declared_mime=mime_type,
        )
    parsed = urlsplit(locator)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        _raise("unsupported_media_locator", "Image locator is not supported.")
    return MediaPart(media_type="image", source=UrlSource(url=locator))


def _pdf_part(item: dict[str, Any]) -> MediaPart:
    if item.get("file_id") is not None or item.get("file_url") is not None:
        _raise("unsupported_media_locator", "Provider file identifiers are not supported.")
    if not set(item).issubset(
        {"type", "file_data", "asset_id", "filename", "file_id", "file_url"}
    ):
        _raise("invalid_request", "File input contains unsupported fields.")
    asset_id = item.get("asset_id")
    locator = item.get("file_data")
    if asset_id is not None:
        if locator is not None or not isinstance(asset_id, str):
            _raise("unsupported_media_locator", "File locator is not supported.")
        filename = item.get("filename")
        if filename is not None and not isinstance(filename, str):
            _raise("invalid_request", "File name is invalid.")
        return MediaPart(
            media_type="pdf",
            source=_asset_source(asset_id),
            filename=filename,
            declared_mime=_PDF_MIME,
        )
    if not isinstance(locator, str):
        _raise("unsupported_media_locator", "File locator is not supported.")
    mime_type, encoded = _decode_data_uri(locator, allowed_mimes={_PDF_MIME})
    filename = item.get("filename")
    if filename is not None and not isinstance(filename, str):
        _raise("invalid_request", "File name is invalid.")
    return MediaPart(
        media_type="pdf",
        source=Base64Source(data=encoded),
        filename=filename,
        declared_mime=mime_type,
    )


def _current_content(value: object) -> tuple[list[TextPart | MediaPart], str]:
    if isinstance(value, str):
        if not value:
            _raise("current_user_required", "Current user input is required.")
        return [TextPart(text=value)], value
    if not isinstance(value, list) or not value:
        _raise("current_user_required", "Current user input is required.")

    parts: list[TextPart | MediaPart] = []
    text_sections: list[str] = []
    for raw_part in value:
        if not isinstance(raw_part, dict) or not all(isinstance(key, str) for key in raw_part):
            _raise("invalid_request", "Current user content is malformed.")
        part = cast(dict[str, Any], raw_part)
        part_type = part.get("type")
        if part_type == "input_text":
            if set(part) != {"type", "text"} or not isinstance(part.get("text"), str):
                _raise("invalid_request", "Text input is malformed.")
            text = cast(str, part["text"])
            parts.append(TextPart(text=text))
            text_sections.append(text)
        elif part_type == "input_image":
            parts.append(_image_part(part))
        elif part_type == "input_file":
            parts.append(_pdf_part(part))
        else:
            _raise("invalid_request", "Current user content type is not supported.")
    if not parts:
        _raise("current_user_required", "Current user input is required.")
    return parts, "\n".join(text_sections).strip()


def _select_current_input(value: object) -> tuple[object, list[object]]:
    if isinstance(value, str):
        return value, []
    if not isinstance(value, list) or not value:
        _raise("current_user_required", "Current user input is required.")
    user_indices = [
        index
        for index, item in enumerate(value)
        if isinstance(item, dict) and item.get("role") == "user"
    ]
    if not user_indices:
        _raise("current_user_required", "Current user input is required.")
    current_index = user_indices[-1]
    history = [item for index, item in enumerate(value) if index != current_index]
    if any(_contains_media_reference(item) for item in history):
        _raise("unsafe_history_media", "Media in Responses history is not permitted.")
    current = value[current_index]
    if not isinstance(current, dict):  # pragma: no cover - selected above
        _raise("invalid_request", "Current user input is malformed.")
    allowed = {"type", "role", "content", "id"}
    if not set(current).issubset(allowed) or current.get("type") not in {None, "message"}:
        _raise("invalid_request", "Current user message is malformed.")
    message_id = current.get("id")
    if message_id is not None and (not isinstance(message_id, str) or not message_id.strip()):
        _raise("invalid_request", "Current user message ID is malformed.")
    if "content" not in current:
        _raise("current_user_required", "Current user input is required.")
    return current["content"], history


def normalize_responses_request(
    payload: object,
    state: ResponsesStateRecord | None,
) -> NormalizedResponsesRequest:
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        _raise("invalid_request", "Responses request must be a JSON object.")
    request_payload = cast(dict[str, Any], payload)
    if request_payload.get("conversation") is not None:
        _raise("conversation_unsupported", "Server-side conversation state is not supported.")

    previous_id = request_payload.get("previous_response_id")
    if previous_id is not None and not isinstance(previous_id, str):
        _raise("invalid_request", "Previous response identifier is invalid.")
    if previous_id is None and state is not None:
        _raise("state_unavailable", "Responses state is unavailable.")
    if previous_id is not None and (state is None or state.response_id != previous_id):
        _raise("state_unavailable", "Responses state is unavailable.")

    for key, value in request_payload.items():
        if key != "input" and _contains_media_reference(value):
            _raise("unsafe_media_reference", "Media outside current input is not permitted.")

    if "input" not in request_payload:
        _raise("current_user_required", "Current user input is required.")
    selected_input, _history = _select_current_input(request_payload["input"])
    current_parts, current_user_text = _current_content(selected_input)

    try:
        model_id = request_payload.get("model")
        if not isinstance(model_id, str):
            _raise("invalid_request", "Target model identifier is invalid.")
        target = TargetModel(registry_id=model_id)
        content: list[TextPart | MediaPart] = []
        if state is not None and state.sanitized_text:
            content.append(TextPart(text=state.sanitized_text))
        content.extend(current_parts)
        conversion_profile: Literal["generic", "error_screenshot", "document"] = (
            "document"
            if any(
                isinstance(part, MediaPart) and part.media_type == "pdf"
                for part in current_parts
            )
            else "generic"
        )
        request = PrepareForModelRequest(
            content=content,
            target=target,
            conversion_profile=conversion_profile,
        )
    except ValidationError:
        _raise("invalid_request", "Responses request fields are invalid.")

    return NormalizedResponsesRequest(
        request=request,
        current_user_text=current_user_text,
        input_had_media=any(isinstance(part, MediaPart) for part in current_parts),
        previous_state=state,
    )
