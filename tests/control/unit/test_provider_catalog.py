import pytest

from media_bridge_control.provider_catalog import (
    ProviderCatalogError,
    get_provider_catalog,
    get_provider_catalog_entry,
    provider_catalog_payload,
)


def test_analysis_catalog_contains_real_media_analysis_contracts() -> None:
    entries = get_provider_catalog("analysis")

    assert [entry.provider_id for entry in entries] == [
        "upstage-document-parse",
        "openai-vision",
        "anthropic-vision",
        "gemini-vision",
        "custom-vision-compatible",
    ]
    assert entries[0].protocol == "upstage-document-digitization"
    assert entries[0].capabilities == ("ocr", "pdf")


def test_non_vision_catalog_contains_omniroute_and_supported_text_targets() -> None:
    entries = get_provider_catalog("llm")

    provider_ids = {entry.provider_id for entry in entries}
    assert {
        "omniroute",
        "openai",
        "anthropic",
        "gemini",
        "upstage-solar",
        "mistral",
        "groq",
        "deepseek",
        "openrouter",
        "ollama",
        "vllm",
        "lm-studio",
        "custom-llm-compatible",
    } <= provider_ids
    assert all(entry.capabilities == ("text",) for entry in entries)


def test_image_generation_provider_is_not_an_analysis_provider() -> None:
    provider_ids = {entry.provider_id for entry in get_provider_catalog("analysis")}

    assert "stability-ai" not in provider_ids
    assert "recraft" not in provider_ids
    assert "black-forest-labs" not in provider_ids


def test_provider_catalog_entry_is_lookupable_and_unknown_id_is_safe() -> None:
    assert get_provider_catalog_entry("omniroute").kind == "llm"

    with pytest.raises(ProviderCatalogError, match="provider_catalog_entry_unknown"):
        get_provider_catalog_entry("does-not-exist")


def test_provider_catalog_payload_is_safe_for_admin_api() -> None:
    payload = provider_catalog_payload("llm")

    omniroute = next(item for item in payload if item["provider_id"] == "omniroute")
    assert omniroute == {
        "provider_id": "omniroute",
        "display_name": "OmniRoute",
        "kind": "llm",
        "protocol": "openai-responses",
        "capabilities": ["text"],
        "default_endpoint": None,
        "secret_env": "MEDIA_BRIDGE_OMNIROUTE_API_KEY",
    }
    assert all("api_key" not in item for item in payload)
