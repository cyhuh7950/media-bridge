from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from media_bridge_control.schemas import ModelCapabilityCreate, ProviderCreate


def _timestamps() -> tuple[datetime, datetime]:
    reviewed = datetime.now(UTC)
    return reviewed, reviewed + timedelta(days=30)


def test_provider_alias_is_optional_input_but_public_safe() -> None:
    request = ProviderCreate(
        name="openai-production",
        alias="openai-prod",
        kind="llm",
        endpoint="https://api.openai.com/v1",
        protocol="openai-chat-completions",
        capabilities={"text"},
        secret_ref={"kind": "db", "identifier": "provider_api_key"},
    )

    assert request.alias == "openai-prod"


def test_public_model_binds_to_internal_routing_profile() -> None:
    reviewed, expires = _timestamps()
    request = ModelCapabilityCreate(
        routing_profile_id=uuid4(),
        provider_id=None,
        model_id="openai-prod/gpt-5",
        aliases=[],
        input_modalities={"text"},
        evidence="operator verified",
        reviewed_at=reviewed,
        expires_at=expires,
    )

    assert request.routing_profile_id is not None
    assert request.reasoning_effort == "provider_default"


def test_public_model_rejects_non_public_identifier() -> None:
    reviewed, expires = _timestamps()
    with pytest.raises(ValidationError):
        ModelCapabilityCreate(
            routing_profile_id=uuid4(),
            model_id="solar pro4",
            input_modalities={"text"},
            evidence="operator verified",
            reviewed_at=reviewed,
            expires_at=expires,
        )
