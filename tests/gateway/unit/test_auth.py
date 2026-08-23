from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from uuid import UUID

import pytest

from media_bridge.config_snapshot import SignedSnapshot
from media_bridge_control.snapshots import SnapshotSigner
from media_bridge_gateway.auth import (
    CredentialAuthenticationError,
    SnapshotCredentialVerifier,
)
from tests.control.snapshot_helpers import private_key_pem, snapshot_body

PEPPER = b"p" * 32
RAW = "mbc_selector-a.super-secret-value"


def _digest(raw: str) -> str:
    return hmac.new(
        PEPPER,
        f"client_credential\0{raw}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _snapshot(
    *,
    scopes: list[str] | None = None,
    expires_at: datetime | None = None,
    revoked: bool = False,
) -> SignedSnapshot:
    body = snapshot_body()
    body["data_plane_auth"] = {
        "entries": [
            {
                "selector": "selector-a",
                "digest": _digest(RAW),
                "scopes": scopes or ["responses:invoke"],
                "expires_at": expires_at.isoformat() if expires_at else None,
                "revoked": revoked,
            }
        ]
    }
    signer = SnapshotSigner(key_id="gateway-key", private_key_pem=private_key_pem())
    return signer.sign(
        snapshot_id=UUID("00000000-0000-0000-0000-000000000001"),
        version=1,
        issued_at=datetime(2026, 8, 24, tzinfo=UTC),
        body=body,
    )


def test_valid_digest_only_credential_returns_snapshot_scoped_subject() -> None:
    verifier = SnapshotCredentialVerifier(
        snapshot=_snapshot(),
        pepper=PEPPER,
        now=lambda: datetime(2026, 8, 24, tzinfo=UTC),
    )

    subject = verifier.authenticate(
        authorization=f"Bearer {RAW}",
        required_scope="responses:invoke",
        cookie_header=None,
    )

    assert subject.credential_selector == "selector-a"
    assert subject.tenant_id == "client-selector-a"
    assert subject.scopes == frozenset({"responses:invoke"})


@pytest.mark.parametrize(
    ("kwargs", "required_scope"),
    [
        ({"revoked": True}, "responses:invoke"),
        ({"expires_at": datetime(2026, 8, 23, tzinfo=UTC)}, "responses:invoke"),
        ({"scopes": ["assets:write"]}, "responses:invoke"),
    ],
)
def test_revoked_expired_or_wrong_scope_credential_is_rejected(
    kwargs: dict[str, object],
    required_scope: str,
) -> None:
    verifier = SnapshotCredentialVerifier(
        snapshot=_snapshot(**kwargs),
        pepper=PEPPER,
        now=lambda: datetime(2026, 8, 24, tzinfo=UTC),
    )

    with pytest.raises(CredentialAuthenticationError) as caught:
        verifier.authenticate(
            authorization=f"Bearer {RAW}",
            required_scope=required_scope,
            cookie_header=None,
        )
    assert caught.value.code == "credential_invalid"


def test_admin_cookie_is_rejected_even_with_valid_data_plane_bearer() -> None:
    verifier = SnapshotCredentialVerifier(
        snapshot=_snapshot(),
        pepper=PEPPER,
        now=lambda: datetime(2026, 8, 24, tzinfo=UTC),
    )

    with pytest.raises(CredentialAuthenticationError) as caught:
        verifier.authenticate(
            authorization=f"Bearer {RAW}",
            required_scope="responses:invoke",
            cookie_header="media_bridge_admin=must-not-authorize-data-plane",
        )
    assert caught.value.code == "admin_session_not_allowed"


def test_snapshot_without_data_plane_auth_fails_closed() -> None:
    signer = SnapshotSigner(key_id="gateway-key", private_key_pem=private_key_pem())
    snapshot = signer.sign(
        snapshot_id=UUID("00000000-0000-0000-0000-000000000001"),
        version=1,
        issued_at=datetime(2026, 8, 24, tzinfo=UTC),
        body=snapshot_body(),
    )
    verifier = SnapshotCredentialVerifier(snapshot=snapshot, pepper=PEPPER)

    with pytest.raises(CredentialAuthenticationError):
        verifier.authenticate(
            authorization=f"Bearer {RAW}",
            required_scope="responses:invoke",
            cookie_header=None,
        )
