"""HMAC-signed receipts required by the guarded downstream boundary."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, cast


class ReceiptValidationError(ValueError):
    """Raised when a gate receipt is invalid, expired, or payload-mismatched."""


@dataclass(frozen=True, slots=True)
class ReceiptBinding:
    target_id: str
    capability: str
    input_digest: str
    output_digest: str
    action: str


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.b64decode(data + padding, altchars=b"-_", validate=True)


class GateReceiptSigner:
    """Sign and verify short-lived bindings between gate input and output."""

    def __init__(self, *, secret: bytes, clock: Callable[[], int | float] = time.time) -> None:
        if len(secret) < 32:
            raise ValueError("receipt secret must contain at least 32 bytes")
        self._secret = secret
        self._clock = clock

    def sign(self, binding: ReceiptBinding, *, ttl_seconds: int = 30) -> str:
        if ttl_seconds < 1 or ttl_seconds > 300:
            raise ValueError("receipt ttl must be between 1 and 300 seconds")
        issued_at = int(self._clock())
        payload: dict[str, Any] = {
            **asdict(binding),
            "issued_at": issued_at,
            "expires_at": issued_at + ttl_seconds,
        }
        encoded_payload = _encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        signature = hmac.new(
            self._secret,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"v1.{encoded_payload}.{_encode(signature)}"

    def verify(self, token: str, *, expected: ReceiptBinding) -> ReceiptBinding:
        try:
            version, encoded_payload, encoded_signature = token.split(".")
            supplied_signature = _decode(encoded_signature)
        except (ValueError, UnicodeError) as error:
            raise ReceiptValidationError("malformed gate receipt") from error
        if version != "v1":
            raise ReceiptValidationError("unsupported gate receipt version")

        expected_signature = hmac.new(
            self._secret,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise ReceiptValidationError("invalid gate receipt signature")

        try:
            raw_payload = json.loads(_decode(encoded_payload))
            if not isinstance(raw_payload, dict):
                raise TypeError
            payload = cast(dict[str, Any], raw_payload)
            binding = ReceiptBinding(
                target_id=str(payload["target_id"]),
                capability=str(payload["capability"]),
                input_digest=str(payload["input_digest"]),
                output_digest=str(payload["output_digest"]),
                action=str(payload["action"]),
            )
            issued_at = int(payload["issued_at"])
            expires_at = int(payload["expires_at"])
        except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as error:
            raise ReceiptValidationError("invalid gate receipt payload") from error

        now = int(self._clock())
        if issued_at > now or expires_at < now:
            raise ReceiptValidationError("gate receipt expired or not yet valid")
        if binding != expected:
            raise ReceiptValidationError("gate receipt does not match downstream payload")
        return binding
