from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from media_bridge.backends import (
    BackendStatus,
    OpenAICompatibleVisionBackend,
    SolarAnalysisBackend,
    UpstageOcrBackend,
    load_secret,
)
from media_bridge.llm_backends import build_llm_backend


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, timeout=1)


def test_secret_loader_uses_named_env_or_secret_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret_file = tmp_path / "provider.key"
    secret_file.write_text("file-secret\n", encoding="utf-8")
    monkeypatch.setenv("TEST_KEY_FILE", str(secret_file))

    assert load_secret("TEST_KEY", "TEST_KEY_FILE") == "file-secret"

    monkeypatch.setenv("TEST_KEY", "environment-secret")
    assert load_secret("TEST_KEY", "TEST_KEY_FILE") == "environment-secret"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("protocol", "endpoint", "expected_field", "catalog_id", "model_id"),
    [
        (
            "openai-chat-completions",
            "https://api.upstage.ai/v1/chat/completions",
            "reasoning_effort",
            "upstage-solar",
            "solar-pro4",
        ),
        (
            "openai-responses",
            "https://api.openai.com/v1/responses",
            "reasoning",
            "openai",
            "gpt-5.1",
        ),
    ],
)
async def test_build_llm_backend_sends_text_and_configured_reasoning(
    protocol: str,
    endpoint: str,
    expected_field: str,
    catalog_id: str,
    model_id: str,
) -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.headers["Authorization"] == "Bearer database-key"
        payload = json.loads(request.content)
        assert payload["model"] == model_id
        if protocol == "openai-chat-completions":
            assert payload["messages"][-1]["content"] == "sanitized OCR text"
            assert payload[expected_field] == "high"
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "answer"}}]},
            )
        assert payload["input"] == "sanitized OCR text"
        assert payload[expected_field] == {"effort": "high"}
        return httpx.Response(
            200,
            json={"id": "resp_test", "output_text": "answer"},
        )

    provider = {
        "id": "provider-uuid",
        "catalog_id": catalog_id,
        "protocol": protocol,
        "endpoint": endpoint,
        "model_id": model_id,
        "reasoning_effort": "high",
    }
    async with _client(httpx.MockTransport(handler)) as client:
        backend = build_llm_backend(
            provider,
            credential_loader=lambda: "database-key",
            client=client,
        )
        result = await backend.analyze(context="sanitized OCR text", user_request="")

    assert result.status is BackendStatus.SUCCESS
    assert result.analysis == "answer"
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_build_llm_backend_rejects_unverified_protocol_without_http() -> None:
    provider = {
        "id": "provider-uuid",
        "catalog_id": "custom-llm-compatible",
        "protocol": "openai-chat-completions",
        "endpoint": "https://custom.example/v1/chat/completions",
        "model_id": "unknown-model",
        "reasoning_effort": "provider_default",
    }
    async with _client(httpx.MockTransport(lambda _request: httpx.Response(200))) as client:
        with pytest.raises(ValueError, match="unsupported"):
            build_llm_backend(provider, credential_loader=lambda: "key", client=client)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "catalog_id",
        "protocol",
        "endpoint",
        "model_id",
        "expected_url",
        "api_key_header",
        "expected_field",
    ),
    [
        (
            "gemini",
            "gemini-generate-content",
            "https://generativelanguage.googleapis.com/v1beta/models",
            "gemini-3.6-flash",
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent",
            "x-goog-api-key",
            {"generationConfig": {"thinkingConfig": {"thinkingLevel": "high"}}},
        ),
        (
            "anthropic",
            "anthropic-messages",
            "https://api.anthropic.com/v1",
            "claude-sonnet-4-6",
            "https://api.anthropic.com/v1/messages",
            "x-api-key",
            {"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}},
        ),
    ],
)
async def test_native_llm_backends_send_provider_specific_effort_and_parse_visible_text(
    catalog_id: str,
    protocol: str,
    endpoint: str,
    model_id: str,
    expected_url: str,
    api_key_header: str,
    expected_field: dict[str, object],
) -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert str(request.url) == expected_url
        assert request.headers[api_key_header] == "native-test-key"
        payload = json.loads(request.content)
        if protocol == "gemini-generate-content":
            assert "model" not in payload
            assert payload["contents"] == [
                {"role": "user", "parts": [{"text": "sanitized context"}]}
            ]
            assert payload["generationConfig"] == expected_field["generationConfig"]
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"text": "internal thought", "thought": True},
                                    {"text": "visible answer"},
                                ]
                            }
                        }
                    ]
                },
            )
        assert payload["model"] == model_id
        assert payload["max_tokens"] == 4096
        assert payload["messages"] == [
            {"role": "user", "content": "sanitized context"}
        ]
        assert {key: payload[key] for key in expected_field} == expected_field
        assert request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "thinking", "thinking": "internal thought"},
                    {"type": "text", "text": "visible answer"},
                ]
            },
        )

    provider = {
        "id": "provider-native",
        "catalog_id": catalog_id,
        "protocol": protocol,
        "endpoint": endpoint,
        "model_id": model_id,
        "reasoning_effort": "high",
    }
    async with _client(httpx.MockTransport(handler)) as client:
        backend = build_llm_backend(
            provider,
            credential_loader=lambda: "native-test-key",
            client=client,
        )
        result = await backend.analyze(context="sanitized context", user_request="")

    assert result.status is BackendStatus.SUCCESS
    assert result.analysis == "visible answer"
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_native_llm_provider_default_omits_effort_and_upstream_error_is_safe() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert "thinking" not in json.loads(request.content)
        return httpx.Response(401, json={"error": "secret provider diagnostic"})

    provider = {
        "id": "provider-native",
        "catalog_id": "anthropic",
        "protocol": "anthropic-messages",
        "endpoint": "https://api.anthropic.com/v1",
        "model_id": "claude-sonnet-4-6",
        "reasoning_effort": None,
    }
    async with _client(httpx.MockTransport(handler)) as client:
        backend = build_llm_backend(
            provider,
            credential_loader=lambda: "native-test-key",
            client=client,
        )
        result = await backend.analyze(context="safe", user_request="")

    assert result.status is BackendStatus.FAILURE
    assert result.error_code == "authentication"
    assert "secret provider diagnostic" not in repr(result)
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_native_llm_invalid_credential_fails_without_socket_call() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    provider = {
        "id": "provider-native",
        "catalog_id": "gemini",
        "protocol": "gemini-generate-content",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/models",
        "model_id": "gemini-3.6-flash",
        "reasoning_effort": "provider_default",
    }

    def invalid_credential() -> str:
        raise ValueError("secret detail")

    async with _client(httpx.MockTransport(handler)) as client:
        backend = build_llm_backend(
            provider,
            credential_loader=invalid_credential,
            client=client,
        )
        result = await backend.analyze(context="safe", user_request="")

    assert result.status is BackendStatus.FAILURE
    assert result.error_code == "configuration"
    assert not seen


@pytest.mark.asyncio
async def test_native_llm_rejects_effort_for_unverified_model() -> None:
    provider = {
        "id": "provider-native",
        "catalog_id": "gemini",
        "protocol": "gemini-generate-content",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/models",
        "model_id": "gemini-2.0-flash",
        "reasoning_effort": "high",
    }
    async with _client(httpx.MockTransport(lambda _request: httpx.Response(200))) as client:
        with pytest.raises(ValueError, match="reasoning effort"):
            build_llm_backend(
                provider,
                credential_loader=lambda: "native-test-key",
                client=client,
            )


@pytest.mark.asyncio
async def test_upstage_ocr_success_uses_header_not_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_UPSTAGE_KEY", "provider-secret")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer provider-secret"
        assert "provider-secret" not in str(request.url)
        body = request.content
        assert b'name="ocr"' in body and b'\r\n\r\nforce' in body
        assert b'name="model"' in body and b'\r\n\r\ndocument-parse' in body
        assert b'name="output_formats"' in body and b'\r\n\r\n["markdown"]' in body
        return httpx.Response(200, json={"text": "Fatal: connection timeout"})

    async with _client(httpx.MockTransport(handler)) as client:
        backend = UpstageOcrBackend(
            endpoint="https://ocr.example/v1/ocr",
            api_key_env="TEST_UPSTAGE_KEY",
            client=client,
        )
        result = await backend.extract(
            data=b"test-image",
            mime_type="image/png",
            filename="capture.png",
        )

    assert result.status is BackendStatus.SUCCESS
    assert result.text == "Fatal: connection timeout"
    assert "provider-secret" not in repr(result)


@pytest.mark.asyncio
async def test_ocr_no_text_malformed_and_timeout_are_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_UPSTAGE_KEY", "provider-secret")

    async def no_text(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": "  "})

    async def malformed(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    async def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("sensitive upstream detail", request=request)

    cases = [
        (no_text, BackendStatus.NO_TEXT, None),
        (malformed, BackendStatus.FAILURE, "invalid_response"),
        (timeout, BackendStatus.FAILURE, "timeout"),
    ]
    for handler, expected_status, expected_code in cases:
        async with _client(httpx.MockTransport(handler)) as client:
            backend = UpstageOcrBackend(
                endpoint="https://ocr.example/v1/ocr",
                api_key_env="TEST_UPSTAGE_KEY",
                client=client,
            )
            result = await backend.extract(
                data=b"test-image",
                mime_type="image/png",
                filename=None,
            )
        assert result.status is expected_status
        assert result.error_code == expected_code
        assert "sensitive" not in repr(result)


@pytest.mark.asyncio
async def test_vision_backend_extracts_description(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_VISION_KEY", "vision-secret")

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "vision-model"
        assert payload["messages"][0]["content"][1]["type"] == "image_url"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "A terminal error screenshot"}}]},
        )

    async with _client(httpx.MockTransport(handler)) as client:
        backend = OpenAICompatibleVisionBackend(
            endpoint="https://vision.example/v1/chat/completions",
            model="vision-model",
            api_key_env="TEST_VISION_KEY",
            client=client,
        )
        result = await backend.describe(
            data=b"image-bytes",
            mime_type="image/png",
            profile="error_screenshot",
        )

    assert result.status is BackendStatus.SUCCESS
    assert result.description == "A terminal error screenshot"


@pytest.mark.asyncio
async def test_vision_backend_rejects_non_image_mime_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_VISION_KEY", "vision-secret")
    network_calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal network_calls
        network_calls += 1
        return httpx.Response(200, json={})

    async with _client(httpx.MockTransport(handler)) as client:
        backend = OpenAICompatibleVisionBackend(
            endpoint="https://vision.example/v1/chat/completions",
            model="vision-model",
            api_key_env="TEST_VISION_KEY",
            client=client,
        )
        result = await backend.describe(
            data=b"%PDF-1.7",
            mime_type="application/pdf",
            profile="document",
        )

    assert result.status is BackendStatus.FAILURE
    assert result.error_code == "unsupported_media"
    assert network_calls == 0


@pytest.mark.asyncio
async def test_solar_is_one_analysis_backend_and_missing_key_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_SOLAR_KEY", raising=False)
    network_calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal network_calls
        network_calls += 1
        return httpx.Response(200, json={})

    async with _client(httpx.MockTransport(handler)) as client:
        missing = SolarAnalysisBackend(
            endpoint="https://solar.example/v1/chat/completions",
            model="solar-pro4",
            api_key_env="TEST_SOLAR_KEY",
            client=client,
        )
        missing_result = await missing.analyze(
            context="converted context",
            user_request="diagnose",
        )
    assert missing_result.status is BackendStatus.FAILURE
    assert missing_result.error_code == "configuration"
    assert network_calls == 0

    monkeypatch.setenv("TEST_SOLAR_KEY", "solar-secret")

    async def success(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer solar-secret"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Root cause: network policy"}}]},
        )

    async with _client(httpx.MockTransport(success)) as client:
        backend = SolarAnalysisBackend(
            endpoint="https://solar.example/v1/chat/completions",
            model="solar-pro4",
            api_key_env="TEST_SOLAR_KEY",
            client=client,
        )
        result = await backend.analyze(
            context="converted context",
            user_request="diagnose",
        )
    assert result.status is BackendStatus.SUCCESS
    assert result.analysis == "Root cause: network policy"


@pytest.mark.asyncio
async def test_solar_backend_accepts_solar_api_key_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    monkeypatch.setenv("SOLAR_API_KEY", "solar-secret")

    async def success(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer solar-secret"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "alias works"}}]},
        )

    async with _client(httpx.MockTransport(success)) as client:
        backend = SolarAnalysisBackend(
            endpoint="https://solar.example/v1/chat/completions",
            model="solar-pro4",
            client=client,
        )
        result = await backend.analyze(context="converted", user_request="diagnose")

    assert result.status is BackendStatus.SUCCESS
    assert result.analysis == "alias works"
