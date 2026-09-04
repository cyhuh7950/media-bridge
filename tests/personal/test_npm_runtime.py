from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import pytest
from PIL import Image

from media_bridge.backends import BackendStatus, OcrResult
from media_bridge_personal import npm_runtime as npm_runtime_module
from media_bridge_personal.npm_runtime import (
    UpstageDocumentParseBackend,
    build_personal_app,
    build_personal_runtime,
)
from media_bridge_personal.solar_responses import SolarResponsesDownstream


def _image_uri() -> str:
    output = BytesIO()
    Image.new("RGB", (4, 4), color="red").save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()


class FakeOcr:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def extract(self, **_kwargs: Any) -> OcrResult:
        self.calls += 1
        if self.fail:
            return OcrResult(BackendStatus.FAILURE, error_code="test_failure")
        return OcrResult(BackendStatus.SUCCESS, text="ERROR 104 from screenshot")


def test_process_entrypoint_applies_configured_request_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    class FakeRuntime:
        async def close(self) -> None:
            captured["closed"] = True

    runtime = FakeRuntime()
    monkeypatch.setenv("MEDIA_BRIDGE_HTTP_HOST", "127.0.0.1")
    monkeypatch.setenv("MEDIA_BRIDGE_HTTP_PORT", "8879")
    monkeypatch.setenv("MEDIA_BRIDGE_MAX_REQUEST_BYTES", "4096")
    config_file = tmp_path / "config.json"
    monkeypatch.setenv("MEDIA_BRIDGE_CONFIG_FILE", str(config_file))
    monkeypatch.setattr(
        npm_runtime_module,
        "build_personal_runtime_from_environment",
        lambda: runtime,
    )
    monkeypatch.setattr(
        npm_runtime_module,
        "build_personal_app",
        lambda selected, *, max_request_bytes, config_file: (
            selected,
            max_request_bytes,
            config_file,
        ),
    )
    monkeypatch.setattr(
        npm_runtime_module.uvicorn,
        "run",
        lambda app, **kwargs: captured.update(app=app, kwargs=kwargs),
    )

    npm_runtime_module.run_personal_npm_runtime()

    assert captured["app"] == (
        runtime,
        4096,
        config_file,
    )
    assert captured["kwargs"]["port"] == 8879
    assert captured["closed"] is True


def test_process_entrypoint_defaults_to_port_8642(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    class FakeRuntime:
        async def close(self) -> None:
            captured["closed"] = True

    monkeypatch.delenv("MEDIA_BRIDGE_HTTP_PORT", raising=False)
    monkeypatch.setenv("MEDIA_BRIDGE_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(
        npm_runtime_module,
        "build_personal_runtime_from_environment",
        lambda: FakeRuntime(),
    )
    monkeypatch.setattr(
        npm_runtime_module,
        "build_personal_app",
        lambda runtime, **_kwargs: runtime,
    )
    monkeypatch.setattr(
        npm_runtime_module.uvicorn,
        "run",
        lambda _app, **kwargs: captured.update(kwargs),
    )

    npm_runtime_module.run_personal_npm_runtime()

    assert captured["port"] == 8642
    assert captured["closed"] is True


def test_settings_page_defaults_to_port_8642() -> None:
    page = npm_runtime_module._settings_page({})

    assert 'name="port" type="number" min="1" max="65535" required value="8642"' in page
    assert 'name="opencodex_base_url" type="url" required value="http://127.0.0.1:8642/v1"' in page


@pytest.mark.asyncio
async def test_document_parse_backend_sends_required_form_fields_and_extracts_content_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_UPSTAGE_KEY", "secret-not-logged")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret-not-logged"
        assert b'name="ocr"\r\n\r\nforce' in request.content
        assert b'name="model"\r\n\r\ndocument-parse' in request.content
        assert b'name="document"; filename="capture.png"' in request.content
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"content": {"html": "<p>ERROR 104</p>"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        backend = UpstageDocumentParseBackend(
            endpoint="https://api.example.test/v1/document-digitization",
            api_key_env="TEST_UPSTAGE_KEY",
            client=client,
        )
        result = await backend.extract(
            data=b"png-bytes",
            mime_type="image/png",
            filename="capture.png",
        )

    assert result.status is BackendStatus.SUCCESS
    assert result.text == "ERROR 104"


def _image_request(*, stream: bool = False) -> dict[str, Any]:
    return {
        "model": "solar-pro4",
        "stream": stream,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "이 오류를 분석해줘"},
                    {"type": "input_image", "image_url": _image_uri()},
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_image_request_reaches_solar_as_ocr_text_without_original_media(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    solar_requests: list[dict[str, Any]] = []

    def solar_handler(request: httpx.Request) -> httpx.Response:
        solar_requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "id": "chatcmpl-image",
                "choices": [{"message": {"role": "assistant", "content": "분석 결과"}}],
            },
        )

    monkeypatch.setenv("TEST_SOLAR_API_KEY", "secret-not-logged")
    ocr = FakeOcr()
    runtime = build_personal_runtime(
        model="solar-pro4",
        asset_root=tmp_path / "assets",
        receipt_secret=b"r" * 32,
        ocr_backend=ocr,
        downstream_factory=lambda signer: SolarResponsesDownstream(
            endpoint="https://api.example.test/v1/chat/completions",
            model="solar-pro4",
            receipt_signer=signer,
            api_key_env="TEST_SOLAR_API_KEY",
            transport=httpx.MockTransport(solar_handler),
        ),
    )
    app = build_personal_app(runtime)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            response = await client.post("/v1/responses", json=_image_request())
    finally:
        await runtime.close()

    assert response.status_code == 200
    assert response.json()["output"][0]["content"][0]["text"] == "분석 결과"
    assert ocr.calls == 1
    assert len(solar_requests) == 1
    serialized = json.dumps(solar_requests[0])
    assert "ERROR 104 from screenshot" in serialized
    assert "input_image" not in serialized
    assert "data:image" not in serialized


@pytest.mark.asyncio
async def test_ocr_failure_blocks_without_solar_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    solar_calls = 0

    def solar_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal solar_calls
        solar_calls += 1
        return httpx.Response(500)

    monkeypatch.setenv("TEST_SOLAR_API_KEY", "secret-not-logged")
    ocr = FakeOcr(fail=True)
    runtime = build_personal_runtime(
        model="solar-pro4",
        asset_root=tmp_path / "assets",
        receipt_secret=b"r" * 32,
        ocr_backend=ocr,
        downstream_factory=lambda signer: SolarResponsesDownstream(
            endpoint="https://api.example.test/v1/chat/completions",
            model="solar-pro4",
            receipt_signer=signer,
            api_key_env="TEST_SOLAR_API_KEY",
            transport=httpx.MockTransport(solar_handler),
        ),
    )
    app = build_personal_app(runtime)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            response = await client.post("/v1/responses", json=_image_request())
    finally:
        await runtime.close()

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ocr_failed"
    assert ocr.calls == 1
    assert solar_calls == 0


@pytest.mark.asyncio
async def test_personal_health_and_streaming_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def solar_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "id": "chatcmpl-stream",
                "choices": [{"message": {"role": "assistant", "content": "stream answer"}}],
            },
        )

    monkeypatch.setenv("TEST_SOLAR_API_KEY", "secret-not-logged")
    runtime = build_personal_runtime(
        model="solar-pro4",
        asset_root=tmp_path / "assets",
        receipt_secret=b"r" * 32,
        ocr_backend=FakeOcr(),
        downstream_factory=lambda signer: SolarResponsesDownstream(
            endpoint="https://api.example.test/v1/chat/completions",
            model="solar-pro4",
            receipt_signer=signer,
            api_key_env="TEST_SOLAR_API_KEY",
            transport=httpx.MockTransport(solar_handler),
        ),
    )
    app = build_personal_app(runtime)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            health = await client.get("/health")
            response = await client.post(
                "/v1/responses",
                json={"model": "solar-pro4", "input": "hello", "stream": True},
            )
    finally:
        await runtime.close()

    assert health.json() == {"status": "ok", "mode": "personal"}
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "response.created" in response.text
    assert "response.output_text.delta" in response.text
    assert response.text.endswith("data: [DONE]\n\n")


@pytest.mark.asyncio
async def test_personal_settings_page_saves_non_secret_npm_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TEST_SOLAR_API_KEY", "secret-must-not-appear")
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "runtimeMode": "personal",
                "host": "127.0.0.1",
                "port": 8765,
                "opencodex": {"baseUrl": "http://127.0.0.1:8765/v1"},
                "solar": {
                    "model": "solar-pro4",
                    "endpoint": "https://api.upstage.ai/v1/chat/completions",
                    "apiKeyEnv": "TEST_SOLAR_API_KEY",
                },
                "ocr": {
                    "model": "document-parse",
                    "endpoint": "https://api.upstage.ai/v1/document-digitization",
                    "apiKeyEnv": "TEST_SOLAR_API_KEY",
                },
                "conversion": {
                    "maxBytes": 8388608,
                    "ocrEnabled": True,
                    "visionEnabled": True,
                },
                "failurePolicy": {"blockSolarOnPreparationFailure": True},
            }
        ),
        encoding="utf-8",
    )
    runtime = build_personal_runtime(
        model="solar-pro4",
        asset_root=tmp_path / "assets",
        receipt_secret=b"r" * 32,
        ocr_backend=FakeOcr(),
        downstream_factory=lambda signer: SolarResponsesDownstream(
            endpoint="https://api.example.test/v1/chat/completions",
            model="solar-pro4",
            receipt_signer=signer,
            api_key_env="TEST_SOLAR_API_KEY",
            transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        ),
    )
    app = build_personal_app(runtime, config_file=config_file)
    form = urlencode(
        {
            "port": "8877",
            "opencodex_base_url": "http://127.0.0.1:8877/v1",
            "solar_model": "solar-pro4",
            "solar_endpoint": "https://api.upstage.ai/v1/chat/completions",
            "solar_api_key_env": "UPSTAGE_API_KEY",
            "ocr_endpoint": "https://api.upstage.ai/v1/document-digitization",
            "ocr_api_key_env": "UPSTAGE_API_KEY",
            "max_bytes": "4194304",
            "ocr_enabled": "true",
            "vision_enabled": "true",
            "block_solar_on_failure": "true",
        }
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765"
        ) as client:
            page = await client.get("/")
            rejected = await client.post(
                "/settings",
                content=form,
                headers={
                    "content-type": "application/x-www-form-urlencoded",
                    "origin": "https://malicious.example",
                },
            )
            saved = await client.post(
                "/settings",
                content=form,
                headers={
                    "content-type": "application/x-www-form-urlencoded",
                    "origin": "http://127.0.0.1:8765",
                },
            )
    finally:
        await runtime.close()

    assert page.status_code == 200
    assert "Media Bridge 설정" in page.text
    assert "secret-must-not-appear" not in page.text
    assert rejected.status_code == 403
    assert saved.status_code == 200
    assert "mb service restart" in saved.text
    persisted = json.loads(config_file.read_text(encoding="utf-8"))
    assert persisted["port"] == 8877
    assert persisted["solar"]["apiKeyEnv"] == "UPSTAGE_API_KEY"
    assert "apiKey" not in persisted["solar"]
