import pytest

from media_bridge_control.configuration import ConfigurationError, ConfigurationService
from media_bridge_control.schemas import ProviderCreate


def test_catalog_provider_requires_kind_and_secret_reference_only() -> None:
    request = ProviderCreate(
        name="omniroute",
        kind="llm",
        catalog_id="omniroute",
        endpoint="https://omniroute.example/v1",
        protocol="openai-responses",
        capabilities={"text"},
        secret_ref={"kind": "env", "identifier": "OMNIROUTE_API_KEY"},
    )

    assert request.kind == "llm"
    assert request.catalog_id == "omniroute"
    assert request.protocol == "openai-responses"
    assert request.capabilities == {"text"}


def test_provider_reasoning_effort_accepts_canonical_values_and_default() -> None:
    common = {
        "name": "solar",
        "kind": "llm",
        "catalog_id": "upstage-solar",
        "endpoint": "https://api.upstage.ai/v1/chat/completions",
        "protocol": "openai-chat-completions",
        "secret_ref": {"kind": "db", "identifier": "provider_api_key"},
    }

    assert ProviderCreate(**common).reasoning_effort == "provider_default"
    for effort in ("none", "minimal", "low", "medium", "high", "xhigh"):
        assert ProviderCreate(**common, reasoning_effort=effort).reasoning_effort == effort


def test_provider_reasoning_effort_rejects_unknown_value() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ProviderCreate(
            name="solar",
            kind="llm",
            endpoint="https://api.upstage.ai/v1/chat/completions",
            secret_ref={"kind": "db", "identifier": "provider_api_key"},
            reasoning_effort="extreme",
        )


def test_provider_reasoning_effort_requires_supported_llm_contract() -> None:
    solar = ProviderCreate(
        name="solar",
        kind="llm",
        catalog_id="upstage-solar",
        model_id="solar-pro4",
        endpoint="https://api.upstage.ai/v1/chat/completions",
        protocol="openai-chat-completions",
        secret_ref={"kind": "db", "identifier": "provider_api_key"},
        reasoning_effort="high",
    )
    assert ConfigurationService._provider_values(solar)["reasoning_effort"] == "high"

    for kind, catalog_id, model_id, protocol in (
        ("analysis", "upstage-document-parse", "solar-pro4", "document-digitization"),
        ("llm", "upstage-solar", "solar-mini", "openai-chat-completions"),
    ):
        request = ProviderCreate(
            name=f"provider-{kind}-{model_id}",
            kind=kind,
            catalog_id=catalog_id,
            model_id=model_id,
            endpoint="https://provider.test/v1",
            protocol=protocol,
            secret_ref={"kind": "db", "identifier": "provider_api_key"},
            reasoning_effort="high",
        )
        with pytest.raises(ConfigurationError, match="reasoning_effort_unsupported"):
            ConfigurationService._provider_values(request)

