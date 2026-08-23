"""Allowlist-only metadata redaction for Audit and Event persistence."""

from __future__ import annotations

type SafeScalar = str | int | bool | None
ALLOWED_DETAIL_KEYS = frozenset(
    {
        "after_id",
        "before_id",
        "name",
        "reason_code",
        "role",
        "scope_count",
        "status",
        "version",
    }
)


class RedactionError(ValueError):
    pass


def redact_details(details: dict[str, object]) -> dict[str, SafeScalar]:
    redacted: dict[str, SafeScalar] = {}
    for key, value in details.items():
        if key not in ALLOWED_DETAIL_KEYS:
            raise RedactionError("audit detail key is not allowlisted")
        if value is not None and not isinstance(value, str | int | bool):
            raise RedactionError("audit detail value is not a safe scalar")
        if isinstance(value, str) and len(value) > 256:
            raise RedactionError("audit detail value is oversized")
        redacted[key] = value
    return redacted
