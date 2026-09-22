"""Verified reasoning-effort capabilities and provider-specific request fields."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ReasoningEffort = Literal[
    "provider_default",
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
]

_Effort = ReasoningEffort


@dataclass(frozen=True, slots=True)
class ReasoningCapability:
    """Efforts and wire mapping verified for one Provider/API/model contract."""

    efforts: tuple[_Effort, ...]
    wire_protocol: str
    wire_values: tuple[tuple[_Effort, str | int], ...]


class UnsupportedReasoningEffortError(ValueError):
    """Raised when a selected effort is not supported by a verified contract."""


UnsupportedReasoningEffort = UnsupportedReasoningEffortError


def _capability(
    wire_protocol: str,
    wire_values: tuple[tuple[_Effort, str | int], ...],
) -> ReasoningCapability:
    return ReasoningCapability(
        efforts=tuple(effort for effort, _ in wire_values),
        wire_protocol=wire_protocol,
        wire_values=wire_values,
    )


def reasoning_capability(
    catalog_id: str | None,
    protocol: str | None,
    model_id: str | None,
) -> ReasoningCapability | None:
    """Return a capability only for an explicitly verified catalog/API/model tuple."""

    if not catalog_id or not protocol or not model_id:
        return None

    model = model_id.strip().casefold()
    provider = catalog_id.strip().casefold()

    if provider == "openai" and protocol in {"openai-responses", "openai-chat-completions"}:
        wire_protocol = (
            "openai-responses" if protocol == "openai-responses" else "openai-chat"
        )
        if model == "gpt-5.1":
            return _capability(
                wire_protocol,
                (("none", "none"), ("low", "low"), ("medium", "medium"), ("high", "high")),
            )
        if model == "gpt-5-pro":
            return _capability(wire_protocol, (("high", "high"),))
        if model in {"o3", "o4-mini"}:
            return _capability(
                wire_protocol,
                (("low", "low"), ("medium", "medium"), ("high", "high")),
            )
        if model == "gpt-5.1-codex-max":
            return _capability(
                wire_protocol,
                (
                    ("none", "none"),
                    ("low", "low"),
                    ("medium", "medium"),
                    ("high", "high"),
                    ("xhigh", "xhigh"),
                ),
            )
        return None

    if provider == "upstage-solar" and protocol == "openai-chat-completions":
        if model in {"solar-pro3", "solar-pro4"}:
            return _capability(
                "openai-chat",
                (("low", "low"), ("medium", "medium"), ("high", "high")),
            )
        return None

    if provider == "gemini" and protocol == "gemini-generate-content":
        gemini_25_budgets = (("low", 1024), ("medium", 8192), ("high", 24576))
        if model == "gemini-2.5-pro":
            return _capability("gemini-budget", gemini_25_budgets)
        if model in {
            "gemini-2.5-flash",
            "gemini-2.5-flash-preview",
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash-lite-preview",
        }:
            return _capability("gemini-budget", (("none", 0), *gemini_25_budgets))

        gemini_3_levels: dict[str, tuple[_Effort, ...]] = {
            "gemini-3.8-flash": ("low", "medium", "high"),
            "gemini-3.7-flash": ("low", "medium", "high"),
            "gemini-3.6-flash": ("minimal", "low", "medium", "high"),
            "gemini-3.5-flash": ("minimal", "low", "medium", "high"),
            "gemini-3.5-flash-lite": ("minimal", "low", "medium", "high"),
            "gemini-3.1-flash-lite": ("minimal", "low", "medium", "high"),
            "gemini-3.1-pro-preview": ("low", "medium", "high"),
            "gemini-3-flash-preview": ("minimal", "low", "medium", "high"),
        }
        efforts = gemini_3_levels.get(model)
        if efforts is not None:
            return _capability("gemini-level", tuple((effort, effort) for effort in efforts))
        return None

    if provider == "anthropic" and protocol == "anthropic-messages":
        if model in {
            "claude-opus-4-6",
            "claude-opus-4-7",
            "claude-opus-4-8",
            "claude-sonnet-4-6",
            "claude-opus-5",
            "claude-sonnet-5",
            "claude-fable-5",
        }:
            return _capability(
                "anthropic-adaptive",
                (("low", "low"), ("medium", "medium"), ("high", "high")),
            )
        return None

    return None


def reasoning_payload_fields(
    capability: ReasoningCapability | None,
    effort: ReasoningEffort | None,
) -> dict[str, object]:
    """Build fresh provider fields, omitting all fields for the provider default."""

    if capability is None or effort is None or effort == "provider_default":
        return {}
    if effort not in capability.efforts:
        raise UnsupportedReasoningEffort("reasoning_effort_unsupported")

    wire_value = dict(capability.wire_values)[effort]
    if capability.wire_protocol == "gemini-level":
        return {"generationConfig": {"thinkingConfig": {"thinkingLevel": wire_value}}}
    if capability.wire_protocol == "gemini-budget":
        return {"generationConfig": {"thinkingConfig": {"thinkingBudget": wire_value}}}
    if capability.wire_protocol == "openai-responses":
        return {"reasoning": {"effort": wire_value}}
    if capability.wire_protocol == "openai-chat":
        return {"reasoning_effort": wire_value}
    if capability.wire_protocol == "anthropic-adaptive":
        return {
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": wire_value},
        }
    raise UnsupportedReasoningEffort("reasoning_protocol_unsupported")
