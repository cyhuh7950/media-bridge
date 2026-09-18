import pytest

from media_bridge_control.provider_catalog import (
    ProviderCatalogError,
    get_provider_catalog,
    get_provider_catalog_entry,
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

