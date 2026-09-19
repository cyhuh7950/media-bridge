"""Approved Provider catalog for the managed Media Bridge console."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ProviderKind = Literal["analysis", "llm"]


class ProviderCatalogError(ValueError):
    """Raised when a caller asks for a Provider that is not in the catalog."""


@dataclass(frozen=True, slots=True)
class ProviderCatalogEntry:
    provider_id: str
    display_name: str
    kind: ProviderKind
    protocol: str
    capabilities: tuple[str, ...]
    default_endpoint: str | None
    secret_env: str | None
    default_model_id: str


_CATALOG: tuple[ProviderCatalogEntry, ...] = (
    ProviderCatalogEntry(
        "upstage-document-parse",
        "Upstage Document Parse",
        "analysis",
        "upstage-document-digitization",
        ("ocr", "pdf"),
        "https://api.upstage.ai/v1/document-digitization",
        "UPSTAGE_API_KEY",
        "document-parse",
    ),
    ProviderCatalogEntry(
        "openai-vision",
        "OpenAI Vision",
        "analysis",
        "openai-chat-completions",
        ("image", "pdf"),
        "https://api.openai.com/v1/chat/completions",
        "OPENAI_API_KEY",
        "gpt-4o",
    ),
    ProviderCatalogEntry(
        "anthropic-vision",
        "Anthropic Vision",
        "analysis",
        "anthropic-messages",
        ("image", "pdf"),
        "https://api.anthropic.com/v1/messages",
        "ANTHROPIC_API_KEY",
        "claude-3-5-sonnet",
    ),
    ProviderCatalogEntry(
        "gemini-vision",
        "Google Gemini Vision",
        "analysis",
        "gemini-generate-content",
        ("image", "pdf"),
        "https://generativelanguage.googleapis.com/v1beta/models",
        "GEMINI_API_KEY",
        "gemini-2.0-flash",
    ),
    ProviderCatalogEntry(
        "custom-vision-compatible",
        "사용자 정의 Vision 호환 endpoint",
        "analysis",
        "custom-vision-compatible",
        ("image", "pdf"),
        None,
        None,
        "vision",
    ),
    ProviderCatalogEntry(
        "omniroute",
        "OmniRoute",
        "llm",
        "openai-responses",
        ("text",),
        None,
        "MEDIA_BRIDGE_OMNIROUTE_API_KEY",
        "auto",
    ),
    ProviderCatalogEntry(
        "openai",
        "OpenAI",
        "llm",
        "openai-responses",
        ("text",),
        "https://api.openai.com/v1",
        "OPENAI_API_KEY",
        "gpt-4o-mini",
    ),
    ProviderCatalogEntry(
        "anthropic",
        "Anthropic",
        "llm",
        "anthropic-messages",
        ("text",),
        "https://api.anthropic.com/v1",
        "ANTHROPIC_API_KEY",
        "claude-3-5-sonnet",
    ),
    ProviderCatalogEntry(
        "gemini",
        "Google Gemini",
        "llm",
        "gemini-generate-content",
        ("text",),
        "https://generativelanguage.googleapis.com/v1beta/models",
        "GEMINI_API_KEY",
        "gemini-2.0-flash",
    ),
    ProviderCatalogEntry(
        "upstage-solar",
        "Upstage Solar",
        "llm",
        "openai-chat-completions",
        ("text",),
        "https://api.upstage.ai/v1",
        "UPSTAGE_API_KEY",
        "solar-pro2",
    ),
    ProviderCatalogEntry(
        "mistral",
        "Mistral",
        "llm",
        "openai-chat-completions",
        ("text",),
        "https://api.mistral.ai/v1",
        "MISTRAL_API_KEY",
        "mistral-large-latest",
    ),
    ProviderCatalogEntry(
        "groq",
        "Groq",
        "llm",
        "openai-chat-completions",
        ("text",),
        "https://api.groq.com/openai/v1",
        "GROQ_API_KEY",
        "llama-3.3-70b-versatile",
    ),
    ProviderCatalogEntry(
        "deepseek",
        "DeepSeek",
        "llm",
        "openai-chat-completions",
        ("text",),
        "https://api.deepseek.com/v1",
        "DEEPSEEK_API_KEY",
        "deepseek-chat",
    ),
    ProviderCatalogEntry(
        "openrouter",
        "OpenRouter",
        "llm",
        "openai-chat-completions",
        ("text",),
        "https://openrouter.ai/api/v1",
        "OPENROUTER_API_KEY",
        "openrouter/auto",
    ),
    ProviderCatalogEntry(
        "ollama",
        "Ollama",
        "llm",
        "openai-chat-completions",
        ("text",),
        "http://127.0.0.1:11434/v1",
        None,
        "default",
    ),
    ProviderCatalogEntry(
        "vllm",
        "vLLM",
        "llm",
        "openai-chat-completions",
        ("text",),
        "http://127.0.0.1:8000/v1",
        None,
        "default",
    ),
    ProviderCatalogEntry(
        "lm-studio",
        "LM Studio",
        "llm",
        "openai-chat-completions",
        ("text",),
        "http://127.0.0.1:1234/v1",
        None,
        "default",
    ),
    ProviderCatalogEntry(
        "custom-llm-compatible",
        "사용자 정의 LLM 호환 endpoint",
        "llm",
        "custom-llm-compatible",
        ("text",),
        None,
        "default",
        None,
    ),
)

_BY_ID = {entry.provider_id: entry for entry in _CATALOG}


def get_provider_catalog(kind: ProviderKind) -> tuple[ProviderCatalogEntry, ...]:
    """Return the immutable approved catalog for one Provider kind."""

    return tuple(entry for entry in _CATALOG if entry.kind == kind)


def get_provider_catalog_entry(provider_id: str) -> ProviderCatalogEntry:
    """Return a catalog entry or a bounded error without exposing secrets."""

    try:
        return _BY_ID[provider_id]
    except KeyError as exc:
        raise ProviderCatalogError("provider_catalog_entry_unknown") from exc


def provider_catalog_payload(kind: ProviderKind) -> list[dict[str, object]]:
    """Serialize catalog metadata without including any credential value."""

    return [
        {
            "provider_id": entry.provider_id,
            "display_name": entry.display_name,
            "kind": entry.kind,
            "protocol": entry.protocol,
            "capabilities": list(entry.capabilities),
            "default_endpoint": entry.default_endpoint,
            "secret_env": entry.secret_env,
            "default_model_id": entry.default_model_id,
        }
        for entry in get_provider_catalog(kind)
    ]
