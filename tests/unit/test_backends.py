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
async def test_upstage_ocr_success_uses_header_not_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_UPSTAGE_KEY", "provider-secret")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer provider-secret"
        assert "provider-secret" not in str(request.url)
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
