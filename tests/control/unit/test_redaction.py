from __future__ import annotations

import pytest

from media_bridge_control.redaction import RedactionError, redact_details


def test_audit_details_use_an_explicit_allowlist() -> None:
    assert redact_details({"role": "operator", "status": "created", "version": 3}) == {
        "role": "operator",
        "status": "created",
        "version": 3,
    }


@pytest.mark.parametrize(
    "details",
    [
        {"secret": "hidden"},
        {"password": "hidden"},
        {"credential": "hidden"},
        {"prompt": "hidden"},
        {"ocr_text": "hidden"},
        {"media": "hidden"},
        {"status": "x" * 257},
        {"status": {"nested": "not allowed"}},
    ],
)
def test_audit_details_reject_sensitive_or_unbounded_values(details: dict[str, object]) -> None:
    with pytest.raises(RedactionError):
        redact_details(details)
