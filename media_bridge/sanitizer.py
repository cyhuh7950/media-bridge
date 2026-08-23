"""Fail-closed text sanitization for downstream model payloads."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


class SanitizationError(ValueError):
    """Raised when conversion output cannot be made safe for downstream use."""


_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DATA_URL = re.compile(
    r"data:(?:image/[a-z0-9.+-]+|application/pdf);base64,[a-z0-9+/=_-]+",
    re.IGNORECASE,
)
_BASE64_BLOB = re.compile(
    r"(?<![a-z0-9+/_-])[a-z0-9+/_-]{128,}={0,2}(?![a-z0-9+/_-])",
    re.IGNORECASE,
)
_REMOVED_REFERENCE = "[removed-media-reference]"
_REMOVED_BINARY = "[removed-binary-data]"


def sanitize_model_text(
    text: str,
    *,
    forbidden_locators: Iterable[str] = (),
    max_length: int = 200_000,
) -> str:
    """Remove original-media references and reject output without usable safe text."""

    if max_length < 1:
        raise ValueError("max_length must be positive")

    sanitized = unicodedata.normalize("NFKC", text)
    sanitized = _CONTROL_CHARACTERS.sub("", sanitized)

    normalized_locators = {
        unicodedata.normalize("NFKC", locator)
        for locator in forbidden_locators
        if locator
    }
    for locator in sorted(normalized_locators, key=len, reverse=True):
        sanitized = sanitized.replace(locator, _REMOVED_REFERENCE)

    sanitized = _DATA_URL.sub(_REMOVED_BINARY, sanitized)
    sanitized = _BASE64_BLOB.sub(_REMOVED_BINARY, sanitized)
    sanitized = sanitized.strip()

    if len(sanitized) > max_length:
        raise SanitizationError("sanitized text exceeds the configured limit")
    if any(locator in sanitized for locator in normalized_locators):
        raise SanitizationError("original media locator remains after sanitization")
    if _DATA_URL.search(sanitized) or _BASE64_BLOB.search(sanitized):
        raise SanitizationError("binary media reference remains after sanitization")

    semantic_text = sanitized.replace(_REMOVED_REFERENCE, "").replace(_REMOVED_BINARY, "")
    if not any(character.isalnum() for character in semantic_text):
        raise SanitizationError("sanitization produced no safe text")

    return sanitized
