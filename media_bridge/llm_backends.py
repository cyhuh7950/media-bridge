"""DB-configured text-only LLM adapters used by the product Gateway."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from media_bridge.backends import (
    AnalysisBackend,
    AnalysisResult,
    BackendStatus,
    SecretConfigurationError,
    _chat_content,
    _failure_code,
)
from media_bridge.reasoning import (
    ReasoningCapability,
    ReasoningEffort,
    reasoning_capability,
    reasoning_payload_fields,
)


class _ProviderTextBackend:
    def __init__(
        self,
        *,
        endpoint: str,
        protocol: str,
        model: str,
        effort: ReasoningEffort,
        capability: ReasoningCapability | None,
        credential_loader: Callable[[], str],
        client: httpx.AsyncClient,
    ) -> None:
        self._endpoint = endpoint
        self._protocol = protocol
        self._model = model
        self._effort = effort
        self._capability = capability
        self._credential_loader = credential_loader
        self._client = client

    async def analyze(self, *, context: str, user_request: str) -> AnalysisResult:
        try:
            secret = self._credential_loader().strip()
            if not secret:
                raise SecretConfigurationError("provider credential is empty")
        except (SecretConfigurationError, ValueError):
            return AnalysisResult(BackendStatus.FAILURE, error_code="configuration")

        prompt = f"{user_request}\n\n{context}".strip()
        if self._protocol == "openai-chat-completions":
            payload: dict[str, Any] = {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": "Analyze only the supplied text context."},
                    {"role": "user", "content": prompt},
                ],
            }
        elif self._protocol == "openai-responses":
            payload = {"model": self._model, "input": prompt}
        elif self._protocol == "gemini-generate-content":
            payload = {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}]
            }
        else:
            payload = {
                "model": self._model,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": prompt}],
            }
        try:
            payload.update(reasoning_payload_fields(self._capability, self._effort))
        except ValueError:
            return AnalysisResult(BackendStatus.FAILURE, error_code="configuration")

        try:
            response = await self._client.post(
                self._endpoint,
                headers=self._headers(secret),
                json=payload,
            )
        except httpx.TimeoutException:
            return AnalysisResult(BackendStatus.FAILURE, error_code="timeout")
        except httpx.RequestError:
            return AnalysisResult(BackendStatus.FAILURE, error_code="transport")
        if response.status_code >= 400:
            return AnalysisResult(BackendStatus.FAILURE, error_code=_failure_code(response))
        try:
            body = response.json()
        except ValueError:
            body = None
        if self._protocol == "openai-chat-completions":
            text = _chat_content(body)
        elif self._protocol == "openai-responses":
            text = _responses_text(body)
        elif self._protocol == "gemini-generate-content":
            text = _gemini_text(body)
        else:
            text = _anthropic_text(body)
        if text is None:
            return AnalysisResult(BackendStatus.FAILURE, error_code="invalid_response")
        return AnalysisResult(BackendStatus.SUCCESS, analysis=text)

    def _headers(self, secret: str) -> dict[str, str]:
        if self._protocol == "gemini-generate-content":
            return {"x-goog-api-key": secret}
        if self._protocol == "anthropic-messages":
            return {"x-api-key": secret, "anthropic-version": "2023-06-01"}
        return {"Authorization": f"Bearer {secret}"}


def _responses_text(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    output = payload.get("output")
    if not isinstance(output, list):
        return None
    texts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if (
                isinstance(part, dict)
                and part.get("type") == "output_text"
                and isinstance(part.get("text"), str)
            ):
                texts.append(part["text"].strip())
    text = "\n".join(item for item in texts if item)
    return text or None


def _gemini_text(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        return None
    content = candidates[0].get("content")
    if not isinstance(content, dict) or not isinstance(content.get("parts"), list):
        return None
    texts = [
        part["text"].strip()
        for part in content["parts"]
        if isinstance(part, dict)
        and part.get("thought") is not True
        and isinstance(part.get("text"), str)
        and part["text"].strip()
    ]
    result = "\n".join(texts)
    return result or None


def _anthropic_text(payload: object) -> str | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("content"), list):
        return None
    texts = [
        block["text"].strip()
        for block in payload["content"]
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
        and block["text"].strip()
    ]
    result = "\n".join(texts)
    return result or None


def _endpoint_for(protocol: str, endpoint: str, model: str) -> str:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("provider endpoint is invalid")
    path = parsed.path.rstrip("/")
    if protocol == "gemini-generate-content":
        if path.endswith("/v1beta/models"):
            final_path = f"{path}/{quote(model, safe='._-')}:generateContent"
        elif path.endswith(":generateContent"):
            final_path = path
        else:
            raise ValueError("provider endpoint path is invalid")
    else:
        suffix = {
            "openai-chat-completions": "/v1/chat/completions",
            "openai-responses": "/v1/responses",
            "anthropic-messages": "/v1/messages",
        }[protocol]
        if path.endswith(suffix):
            final_path = path
        elif path.endswith("/v1"):
            final_path = path + suffix.removeprefix("/v1")
        elif not path:
            final_path = suffix
        else:
            raise ValueError("provider endpoint path is invalid")
    return parsed._replace(path=final_path).geturl()


def build_llm_backend(
    provider: Mapping[str, object],
    *,
    credential_loader: Callable[[], str],
    client: httpx.AsyncClient,
) -> AnalysisBackend:
    """Build only an explicitly supported, text-only OpenAI protocol adapter."""

    catalog_id = provider.get("catalog_id")
    protocol = provider.get("protocol")
    model = provider.get("model_id")
    endpoint = provider.get("endpoint")
    effort_value = provider.get("reasoning_effort")
    required_values = (catalog_id, protocol, model, endpoint)
    if not all(isinstance(value, str) and value.strip() for value in required_values):
        raise ValueError("provider configuration is incomplete")
    catalog_id = str(catalog_id)
    protocol = str(protocol)
    model = str(model)
    endpoint = str(endpoint)
    allowed_pairs = {
        ("openai", "openai-chat-completions"),
        ("openai", "openai-responses"),
        ("upstage-solar", "openai-chat-completions"),
        ("gemini", "gemini-generate-content"),
        ("anthropic", "anthropic-messages"),
    }
    if (catalog_id, protocol) not in allowed_pairs:
        raise ValueError("provider protocol is unsupported")

    effort = str(effort_value or "provider_default")
    if effort not in {"provider_default", "none", "minimal", "low", "medium", "high", "xhigh"}:
        raise ValueError("provider reasoning effort is unsupported")
    capability = reasoning_capability(catalog_id, protocol, model)
    if effort != "provider_default" and (capability is None or effort not in capability.efforts):
        raise ValueError("provider reasoning effort is unsupported")
    return _ProviderTextBackend(
        endpoint=_endpoint_for(protocol, endpoint, model),
        protocol=protocol,
        model=model,
        effort=effort,  # type: ignore[arg-type]
        capability=capability,
        credential_loader=credential_loader,
        client=client,
    )
