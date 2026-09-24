from __future__ import annotations

import pytest

from media_bridge.reasoning import (
    UnsupportedReasoningEffort,
    reasoning_capability,
    reasoning_payload_fields,
)


@pytest.mark.parametrize(
    ("protocol", "model", "efforts", "expected_fields"),
    [
        (
            "openai-responses",
            "gpt-5.1",
            ("none", "low", "medium", "high"),
            {"reasoning": {"effort": "high"}},
        ),
        (
            "openai-chat-completions",
            "gpt-5.1",
            ("none", "low", "medium", "high"),
            {"reasoning_effort": "high"},
        ),
        (
            "openai-responses",
            "gpt-5-pro",
            ("high",),
            {"reasoning": {"effort": "high"}},
        ),
        (
            "openai-responses",
            "o3",
            ("low", "medium", "high"),
            {"reasoning": {"effort": "high"}},
        ),
        (
            "openai-chat-completions",
            "o4-mini",
            ("low", "medium", "high"),
            {"reasoning_effort": "high"},
        ),
        (
            "openai-responses",
            "gpt-5.1-codex-max",
            ("none", "low", "medium", "high", "xhigh"),
            {"reasoning": {"effort": "xhigh"}},
        ),
    ],
)
def test_openai_reasoning_is_model_and_protocol_specific(
    protocol: str,
    model: str,
    efforts: tuple[str, ...],
    expected_fields: dict[str, object],
) -> None:
    capability = reasoning_capability("openai", protocol, model)

    assert capability is not None
    assert capability.efforts == efforts
    selected = "xhigh" if model == "gpt-5.1-codex-max" else "high"
    assert reasoning_payload_fields(capability, selected) == expected_fields


@pytest.mark.parametrize("model", ["solar-pro3", "solar-pro4"])
def test_upstage_solar_chat_reasoning_effort(model: str) -> None:
    capability = reasoning_capability("upstage-solar", "openai-chat-completions", model)

    assert capability is not None
    assert capability.efforts == ("low", "medium", "high")
    assert reasoning_payload_fields(capability, "medium") == {"reasoning_effort": "medium"}


@pytest.mark.parametrize(
    ("model", "effort", "budget"),
    [
        ("gemini-2.5-pro", "low", 1024),
        ("gemini-2.5-pro", "medium", 8192),
        ("gemini-2.5-pro", "high", 24576),
        ("gemini-2.5-flash", "none", 0),
        ("gemini-2.5-flash", "low", 1024),
        ("gemini-2.5-flash-lite", "none", 0),
        ("gemini-2.5-flash-lite", "high", 24576),
    ],
)
def test_gemini_25_maps_effort_to_documented_budget(model: str, effort: str, budget: int) -> None:
    capability = reasoning_capability("gemini", "gemini-generate-content", model)

    assert capability is not None
    assert reasoning_payload_fields(capability, effort) == {
        "generationConfig": {"thinkingConfig": {"thinkingBudget": budget}}
    }


def test_gemini_25_pro_cannot_disable_thinking() -> None:
    capability = reasoning_capability("gemini", "gemini-generate-content", "gemini-2.5-pro")

    assert capability is not None
    assert "none" not in capability.efforts
    with pytest.raises(UnsupportedReasoningEffort):
        reasoning_payload_fields(capability, "none")


@pytest.mark.parametrize(
    ("model", "efforts"),
    [
        ("gemini-3.8-flash", ("low", "medium", "high")),
        ("gemini-3.7-flash", ("low", "medium", "high")),
        ("gemini-3.6-flash", ("minimal", "low", "medium", "high")),
        ("gemini-3.5-flash", ("minimal", "low", "medium", "high")),
        ("gemini-3.5-flash-lite", ("minimal", "low", "medium", "high")),
        ("gemini-3.1-flash-lite", ("minimal", "low", "medium", "high")),
        ("gemini-3.1-pro-preview", ("low", "medium", "high")),
        ("gemini-3-flash-preview", ("minimal", "low", "medium", "high")),
    ],
)
def test_gemini_3_uses_thinking_level(model: str, efforts: tuple[str, ...]) -> None:
    capability = reasoning_capability("gemini", "gemini-generate-content", model)

    assert capability is not None
    assert capability.efforts == efforts
    assert reasoning_payload_fields(capability, "high") == {
        "generationConfig": {"thinkingConfig": {"thinkingLevel": "high"}}
    }
    if "none" not in efforts:
        with pytest.raises(UnsupportedReasoningEffort):
            reasoning_payload_fields(capability, "none")


@pytest.mark.parametrize(
    "model",
    [
        "claude-opus-4-6",
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-sonnet-4-6",
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-fable-5",
    ],
)
def test_anthropic_adaptive_thinking_effort(model: str) -> None:
    capability = reasoning_capability("anthropic", "anthropic-messages", model)

    assert capability is not None
    assert capability.efforts == ("low", "medium", "high")
    assert reasoning_payload_fields(capability, "high") == {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
    }


@pytest.mark.parametrize(
    ("catalog_id", "protocol", "model"),
    [
        ("openai", "openai-responses", "gpt-4o-mini"),
        ("openai", "openai-responses", "gpt-5.1-codex-mini"),
        ("omniroute", "openai-responses", "gpt-5.1"),
        ("custom-llm-compatible", "openai-chat-completions", "solar-pro4"),
        ("gemini", "gemini-generate-content", "gemini-2.0-flash"),
        ("gemini", "gemini-generate-content", "gemini-3-pro-preview"),
        ("anthropic", "anthropic-messages", "claude-sonnet-4-5-20250929"),
        ("upstage-solar", "openai-responses", "solar-pro4"),
        ("upstage-solar", "openai-chat-completions", "solar-pro2"),
        ("unknown", "openai-responses", "gpt-5.1"),
    ],
)
def test_unverified_provider_protocol_or_model_has_no_capability(
    catalog_id: str,
    protocol: str,
    model: str,
) -> None:
    assert reasoning_capability(catalog_id, protocol, model) is None


def test_provider_default_omits_reasoning_and_invalid_effort_fails_closed() -> None:
    capability = reasoning_capability("upstage-solar", "openai-chat-completions", "solar-pro4")

    assert capability is not None
    assert reasoning_payload_fields(capability, "provider_default") == {}
    assert reasoning_payload_fields(capability, None) == {}
    with pytest.raises(UnsupportedReasoningEffort):
        reasoning_payload_fields(capability, "xhigh")

    assert reasoning_payload_fields(None, None) == {}


def test_mutating_returned_payload_does_not_change_later_mappings() -> None:
    capability = reasoning_capability("openai", "openai-responses", "gpt-5.1")
    assert capability is not None

    first = reasoning_payload_fields(capability, "high")
    first["reasoning"]["effort"] = "none"  # type: ignore[index]

    assert reasoning_payload_fields(capability, "high") == {"reasoning": {"effort": "high"}}
