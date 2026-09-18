from __future__ import annotations

from datetime import UTC, datetime

import pytest

from media_bridge_control.totp import TotpError, generate_secret, provisioning_uri, verify_code


def test_totp_code_verifies_for_known_secret_and_timestamp() -> None:
    secret = "JBSWY3DPEHPK3PXP"  # noqa: S105

    assert verify_code(secret, "260025", at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC))


def test_totp_rejects_wrong_code() -> None:
    with pytest.raises(TotpError, match="invalid_code"):
        verify_code("JBSWY3DPEHPK3PXP", "000000", at=datetime(2026, 1, 1, tzinfo=UTC))


def test_provisioning_uri_contains_only_registration_metadata() -> None:
    uri = provisioning_uri(
        secret="JBSWY3DPEHPK3PXP",  # noqa: S106
        account="admin",
        issuer="Media Bridge",
    )

    assert uri.startswith("otpauth://totp/")
    assert "secret=JBSWY3DPEHPK3PXP" in uri
    assert "issuer=Media%20Bridge" in uri


def test_generated_secret_is_base32_and_has_sufficient_entropy() -> None:
    secret = generate_secret()

    assert len(secret) >= 32
    assert set(secret) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
