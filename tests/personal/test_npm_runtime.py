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
from media_bridge_personal.credential_store import CredentialStore
from media_bridge_personal.npm_runtime import (
    ProviderTester,
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


def test_settings_script_warns_when_port_change_requires_restart() -> None:
    script = npm_runtime_module._settings_script()

    assert "saved.restartRequired" in script
    assert "mb service restart" in script


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
        lambda selected, *, max_request_bytes, config_file, **_kwargs: (
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


class FakeProviderTester:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def test_text_llm(self, config: dict[str, Any], prompt: str) -> dict[str, Any]:
        self.calls.append(("text-llm", {"config": config, "prompt": prompt}))
        return {"ok": True, "text": "LLM 연결 정상"}

    async def test_media_processor(
        self,
        config: dict[str, Any],
        *,
        data: bytes,
        mime_type: str,
        filename: str,
    ) -> dict[str, Any]:
        self.calls.append(("media-processor", {"bytes": data, "mime": mime_type}))
        return {"ok": True, "text": "추출된 텍스트"}

    async def test_pipeline(
        self,
        config: dict[str, Any],
        *,
        data: bytes,
        mime_type: str,
        filename: str,
        question: str,
    ) -> dict[str, Any]:
        self.calls.append(("pipeline", {"bytes": data, "question": question}))
        return {
            "ok": True,
            "extractedText": "추출된 텍스트",
            "forwardedText": "질문과 추출 텍스트",
            "originalMediaForwarded": False,
            "answer": "최종 응답",
        }


@pytest.mark.asyncio
async def test_provider_console_saves_generic_profiles_and_secrets_without_echo(
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "runtimeMode": "personal",
                "host": "127.0.0.1",
                "port": 8642,
                "opencodex": {"baseUrl": "http://127.0.0.1:8642/v1"},
                "solar": {
                    "model": "solar-pro4",
                    "endpoint": "https://api.upstage.ai/v1/chat/completions",
                    "apiKeyEnv": "SOLAR_API_KEY",
                },
                "ocr": {
                    "model": "document-parse",
                    "endpoint": "https://api.upstage.ai/v1/document-digitization",
                    "apiKeyEnv": "SOLAR_API_KEY",
                },
                "conversion": {"maxBytes": 8388608, "ocrEnabled": True, "visionEnabled": True},
                "failurePolicy": {"blockSolarOnPreparationFailure": True},
            }
        ),
        encoding="utf-8",
    )
    credential_store = CredentialStore(tmp_path / "secrets" / "providers.json")
    runtime = build_personal_runtime(
        model="solar-pro4",
        asset_root=tmp_path / "assets",
        receipt_secret=b"r" * 32,
        ocr_backend=FakeOcr(),
        downstream_factory=lambda signer: SolarResponsesDownstream(
            endpoint="https://api.example.test/v1/chat/completions",
            model="solar-pro4",
            receipt_signer=signer,
            api_key_env="MISSING_TEST_KEY",
            transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        ),
    )
    app = build_personal_app(
        runtime,
        config_file=config_file,
        credential_store=credential_store,
        provider_tester=FakeProviderTester(),
    )
    payload = {
        "port": 8642,
        "codingAgent": {
            "preset": "eoul-gateway",
            "protocol": "openai-responses",
            "baseUrl": "http://127.0.0.1:8642/v1",
        },
        "textLlm": {
            "preset": "custom",
            "protocol": "openai-chat-completions",
            "endpoint": "https://llm.example.test/v1/chat/completions",
            "model": "text-model",
            "credentialRef": "text-llm",
            "credentialEnv": "CUSTOM_LLM_KEY",
            "apiKey": "llm-secret-value",
        },
        "mediaProcessor": {
            "preset": "upstage-document-parse",
            "protocol": "upstage-document-parse",
            "endpoint": "https://api.upstage.ai/v1/document-digitization",
            "model": "document-parse",
            "credentialRef": "media-processor",
            "credentialEnv": "UPSTAGE_API_KEY",
            "apiKey": "ocr-secret-value",
        },
        "conversion": {"maxBytes": 8388608, "ocrEnabled": True, "visionEnabled": True},
        "failurePolicy": {"blockSolarOnPreparationFailure": True},
    }
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8642"
        ) as client:
            saved = await client.post(
                "/api/settings",
                json=payload,
                headers={"origin": "http://127.0.0.1:8642"},
            )
            loaded = await client.get("/api/settings")
            page = await client.get("/")
    finally:
        await runtime.close()

    assert saved.status_code == 200
    assert loaded.status_code == 200
    assert loaded.json()["credentials"] == {"text-llm": True, "media-processor": True}
    serialized = json.dumps(loaded.json()) + page.text + config_file.read_text(encoding="utf-8")
    assert "llm-secret-value" not in serialized
    assert "ocr-secret-value" not in serialized
    assert credential_store.get("text-llm") == "llm-secret-value"
    assert credential_store.get("media-processor") == "ocr-secret-value"
    persisted = json.loads(config_file.read_text(encoding="utf-8"))
    assert persisted["codingAgent"]["preset"] == "eoul-gateway"
    assert persisted["textLlm"]["model"] == "text-model"
    assert persisted["mediaProcessor"]["protocol"] == "upstage-document-parse"


@pytest.mark.asyncio
async def test_provider_console_exposes_connection_ocr_pipeline_and_agent_contracts(
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "runtimeMode": "personal",
                "host": "127.0.0.1",
                "port": 8642,
                "codingAgent": {
                    "preset": "opencodex",
                    "protocol": "openai-responses",
                    "baseUrl": "http://127.0.0.1:8642/v1",
                },
                "textLlm": {
                    "preset": "upstage-solar",
                    "protocol": "openai-chat-completions",
                    "endpoint": "https://api.upstage.ai/v1/chat/completions",
                    "model": "solar-pro4",
                    "credentialRef": "text-llm",
                    "credentialEnv": "SOLAR_API_KEY",
                },
                "mediaProcessor": {
                    "preset": "upstage-document-parse",
                    "protocol": "upstage-document-parse",
                    "endpoint": "https://api.upstage.ai/v1/document-digitization",
                    "model": "document-parse",
                    "credentialRef": "media-processor",
                    "credentialEnv": "SOLAR_API_KEY",
                },
                "conversion": {"maxBytes": 8388608, "ocrEnabled": True, "visionEnabled": True},
                "failurePolicy": {"blockSolarOnPreparationFailure": True},
            }
        ),
        encoding="utf-8",
    )
    tester = FakeProviderTester()
    runtime = build_personal_runtime(
        model="solar-pro4",
        asset_root=tmp_path / "assets",
        receipt_secret=b"r" * 32,
        ocr_backend=FakeOcr(),
        downstream_factory=lambda signer: SolarResponsesDownstream(
            endpoint="https://api.example.test/v1/chat/completions",
            model="solar-pro4",
            receipt_signer=signer,
            api_key_env="MISSING_TEST_KEY",
            transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        ),
    )
    app = build_personal_app(
        runtime,
        config_file=config_file,
        credential_store=CredentialStore(tmp_path / "providers.json"),
        provider_tester=tester,
    )
    image = base64.b64encode(b"fake-image-bytes").decode()
    headers = {"origin": "http://127.0.0.1:8642"}
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8642"
        ) as client:
            agent = await client.get("/api/coding-agent")
            llm = await client.post(
                "/api/test/text-llm", json={"prompt": "연결 시험"}, headers=headers
            )
            ocr = await client.post(
                "/api/test/media-processor",
                json={"filename": "test.png", "mimeType": "image/png", "dataBase64": image},
                headers=headers,
            )
            pipeline = await client.post(
                "/api/test/pipeline",
                json={
                    "filename": "test.png",
                    "mimeType": "image/png",
                    "dataBase64": image,
                    "question": "무엇이 보이나요?",
                },
                headers=headers,
            )
    finally:
        await runtime.close()

    assert agent.json()["preset"] == "opencodex"
    assert agent.json()["responsesUrl"] == "http://127.0.0.1:8642/v1/responses"
    assert llm.json() == {"ok": True, "text": "LLM 연결 정상"}
    assert ocr.json()["text"] == "추출된 텍스트"
    assert pipeline.json()["originalMediaForwarded"] is False
    assert [call[0] for call in tester.calls] == ["text-llm", "media-processor", "pipeline"]


@pytest.mark.asyncio
async def test_real_provider_tester_runs_ocr_then_text_without_forwarding_media(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer shared-provider-secret"
        if request.url.path == "/v1/document-digitization":
            assert b"fake-image-bytes" in request.content
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={"content": {"text": "사진에서 읽은 문장"}},
            )
        body = json.loads(request.content)
        serialized = json.dumps(body, ensure_ascii=False)
        assert "사진에서 읽은 문장" in serialized
        assert "fake-image-bytes" not in serialized
        assert "data:image" not in serialized
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "choices": [{"message": {"content": "최종 분석 결과"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            },
        )

    store = CredentialStore(tmp_path / "providers.json")
    store.set("text-llm", "shared-provider-secret")
    store.set("media-processor", "shared-provider-secret")
    tester = ProviderTester(store, transport=httpx.MockTransport(handler))
    config = {
        "textLlm": {
            "protocol": "openai-chat-completions",
            "endpoint": "https://api.example.test/v1/chat/completions",
            "model": "text-model",
            "credentialRef": "text-llm",
            "credentialEnv": "MISSING_LLM_KEY",
        },
        "mediaProcessor": {
            "protocol": "upstage-document-parse",
            "endpoint": "https://api.example.test/v1/document-digitization",
            "model": "document-parse",
            "credentialRef": "media-processor",
            "credentialEnv": "MISSING_OCR_KEY",
        },
    }

    result = await tester.test_pipeline(
        config,
        data=b"fake-image-bytes",
        mime_type="image/png",
        filename="screen.png",
        question="무엇이 보이나요?",
    )

    assert result["originalMediaForwarded"] is False
    assert result["extractedText"] == "사진에서 읽은 문장"
    assert result["answer"] == "최종 분석 결과"
    assert [request.url.path for request in requests] == [
        "/v1/document-digitization",
        "/v1/chat/completions",
    ]
