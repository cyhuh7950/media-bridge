"""Small dependency-free RFC 6238 TOTP implementation for the control plane."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import struct
from datetime import datetime, timezone
from urllib.parse import quote


class TotpError(ValueError):
    """Raised when a TOTP secret or code is invalid."""


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def provisioning_uri(*, secret: str, account: str, issuer: str) -> str:
    _decode_secret(secret)
    if not account.strip() or not issuer.strip():
        raise TotpError("invalid_metadata")
    label = f"{issuer}:{account}"
    return (
        f"otpauth://totp/{quote(label, safe='')}?secret={secret}&issuer={quote(issuer)}"
        "&algorithm=SHA1&digits=6&period=30"
    )


def verify_code(secret: str, code: str, *, at: datetime, window: int = 1) -> bool:
    if not code.isdigit() or len(code) != 6 or window < 0:
        raise TotpError("invalid_code")
    key = _decode_secret(secret)
    timestamp = at.astimezone(timezone.utc).timestamp()
    counter = int(timestamp // 30)
    expected = {
        _hotp(key, counter + offset)
        for offset in range(-window, window + 1)
        if counter + offset >= 0
    }
    if not any(hmac.compare_digest(code, candidate) for candidate in expected):
        raise TotpError("invalid_code")
    return True


def _decode_secret(secret: str) -> bytes:
    normalized = secret.strip().upper()
    if not normalized or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for char in normalized):
        raise TotpError("invalid_secret")
    try:
        return base64.b32decode(normalized + "=" * (-len(normalized) % 8), casefold=True)
    except (binascii.Error, ValueError) as error:
        raise TotpError("invalid_secret") from error


def _hotp(key: bytes, counter: int) -> str:
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"
