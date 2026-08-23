from __future__ import annotations

from datetime import UTC, datetime

import pytest

from media_bridge_gateway.auth import CredentialAuthenticationError, SnapshotCredentialVerifier
from tests.gateway.unit.test_auth import PEPPER, RAW, _snapshot


def test_authentication_error_and_object_repr_do_not_expose_raw_credential() -> None:
    verifier = SnapshotCredentialVerifier(
        snapshot=_snapshot(),
        pepper=PEPPER,
        now=lambda: datetime(2026, 8, 24, tzinfo=UTC),
    )

    with pytest.raises(CredentialAuthenticationError) as caught:
        verifier.authenticate(
            authorization=f"Bearer {RAW}tampered",
            required_scope="responses:invoke",
            cookie_header=None,
        )

    assert RAW not in str(caught.value)
    assert RAW not in repr(caught.value)
    assert RAW not in repr(verifier)
    assert "super-secret-value" not in str(caught.value)
