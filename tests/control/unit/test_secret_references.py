from __future__ import annotations

import pytest
from pydantic import ValidationError

from media_bridge_control.schemas import SecretReference


@pytest.mark.parametrize(
    ("kind", "identifier"),
    [
        ("env", "MEDIA_BRIDGE_UPSTAGE_API_KEY"),
        ("docker_secret", "upstage-api-key"),
        ("external", "vault://media-bridge/providers/upstage"),
        ("external", "aws-sm://media-bridge/upstage"),
    ],
)
def test_secret_reference_accepts_only_external_locators(kind: str, identifier: str) -> None:
    reference = SecretReference(kind=kind, identifier=identifier)
    assert reference.identifier == identifier


@pytest.mark.parametrize(
    ("kind", "identifier"),
    [
        ("env", "MEDIA_BRIDGE_KEY=raw-secret"),
        ("env", "lowercase_key"),
        ("docker_secret", "../secret"),
        ("docker_secret", "/run/secrets/key"),
        ("external", "https://example.test/?token=raw-secret"),
        ("external", "vault://../secret"),
        ("external", "raw-secret"),
    ],
)
def test_secret_reference_rejects_values_paths_and_unapproved_schemes(
    kind: str,
    identifier: str,
) -> None:
    with pytest.raises(ValidationError):
        SecretReference(kind=kind, identifier=identifier)
