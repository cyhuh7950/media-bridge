from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfWriter

from media_bridge.contracts import PrepareForModelRequest
from media_bridge.entrypoints import run_http, run_stdio
from media_bridge.runtime import RuntimeConfigurationError, build_runtime_from_environment


def _configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, registry: str) -> None:
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(registry, encoding="utf-8")
    monkeypatch.setenv("MEDIA_BRIDGE_MODEL_REGISTRY", str(registry_path))
    monkeypatch.setenv("MEDIA_BRIDGE_ASSET_ROOT", str(tmp_path / "assets"))
    monkeypatch.setenv("MEDIA_BRIDGE_RECEIPT_SECRET", "r" * 32)
    monkeypatch.setenv("MEDIA_BRIDGE_OCR_ENDPOINT", "https://ocr.example/v1/ocr")
    monkeypatch.setenv(
        "MEDIA_BRIDGE_VISION_ENDPOINT",
        "https://vision.example/v1/chat/completions",
    )
    monkeypatch.setenv("MEDIA_BRIDGE_VISION_MODEL", "vision-converter")
    monkeypatch.delenv("MEDIA_BRIDGE_OMNIROUTE_BASE_URL", raising=False)
    monkeypatch.delenv("MEDIA_BRIDGE_OMNIROUTE_API_KEY", raising=False)
    monkeypatch.delenv("MEDIA_BRIDGE_OMNIROUTE_API_KEY_FILE", raising=False)


@pytest.mark.asyncio
async def test_runtime_loads_strict_registry_and_builds_both_entrypoints(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure(
        monkeypatch,
        tmp_path,
        """version: test-v1
models:
  - id: text-model
    input_modalities: [text]
    expires_at: 2099-01-01T00:00:00Z
    pdf_passthrough_verified: false
""",
    )

    runtime = build_runtime_from_environment()
    result = await runtime.service.prepare_for_model(
        PrepareForModelRequest.model_validate(
            {
                "content": [{"type": "text", "text": "hello"}],
                "target": {"registry_id": "text-model"},
            }
        ),
        tenant_id="tenant-a",
    )

    assert result.action == "passthrough"
    assert callable(run_stdio)
    assert callable(run_http)
    assert runtime.responses_gateway is None
    await runtime.close()


@pytest.mark.asyncio
async def test_runtime_registry_requires_explicit_pdf_passthrough_verification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure(
        monkeypatch,
        tmp_path,
        """version: test-v1
models:
  - id: pdf-model
    input_modalities: [text, pdf]
    expires_at: 2099-01-01T00:00:00Z
    pdf_passthrough_verified: true
""",
    )

    runtime = build_runtime_from_environment()
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(output)
    result = await runtime.service.prepare_for_model(
        PrepareForModelRequest.model_validate(
            {
                "content": [
                    {
                        "type": "media",
                        "media_type": "pdf",
                        "source": {
                            "kind": "base64",
                            "data": base64.b64encode(output.getvalue()).decode("ascii"),
                        },
                        "declared_mime": "application/pdf",
                    }
                ],
                "target": {"registry_id": "pdf-model"},
            }
        ),
        tenant_id="tenant-a",
    )

    assert result.action == "passthrough"
    assert result.original_image_removed is False
    await runtime.close()


def test_runtime_rejects_duplicate_models_and_unknown_registry_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    duplicate = """version: test-v1
models:
  - id: same-model
    input_modalities: [text]
    expires_at: 2099-01-01T00:00:00Z
  - id: same-model
    input_modalities: [text, image]
    expires_at: 2099-01-01T00:00:00Z
"""
    _configure(monkeypatch, tmp_path, duplicate)
    with pytest.raises(RuntimeConfigurationError, match="duplicate"):
        build_runtime_from_environment()

    unknown_field = """version: test-v1
models:
  - id: text-model
    input_modalities: [text]
    expires_at: 2099-01-01T00:00:00Z
    guess_vision: true
"""
    _configure(monkeypatch, tmp_path, unknown_field)
    with pytest.raises(RuntimeConfigurationError, match="registry"):
        build_runtime_from_environment()


def test_runtime_requires_receipt_secret_without_reading_arbitrary_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure(
        monkeypatch,
        tmp_path,
        """version: test-v1
models: []
""",
    )
    monkeypatch.delenv("MEDIA_BRIDGE_RECEIPT_SECRET")
    monkeypatch.delenv("MEDIA_BRIDGE_RECEIPT_SECRET_FILE", raising=False)
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-be-used")

    with pytest.raises(RuntimeConfigurationError, match="receipt"):
        build_runtime_from_environment()


@pytest.mark.asyncio
async def test_runtime_optionally_wires_gateway_from_exact_secret_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure(monkeypatch, tmp_path, """version: test-v1
models:
  - id: text-model
    input_modalities: [text]
    expires_at: 2099-01-01T00:00:00Z
""")
    monkeypatch.setenv(
        "MEDIA_BRIDGE_OMNIROUTE_BASE_URL",
        "http://127.0.0.1:20128/v1/responses",
    )
    secret_file = tmp_path / "omniroute.key"
    secret_file.write_text("omniroute-secret\n", encoding="utf-8")
    monkeypatch.setenv("MEDIA_BRIDGE_OMNIROUTE_API_KEY_FILE", str(secret_file))

    runtime = build_runtime_from_environment()

    assert runtime.responses_gateway is not None
    await runtime.close()


def test_runtime_blocks_enabled_gateway_without_exact_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure(monkeypatch, tmp_path, """version: test-v1
models: []
""")
    monkeypatch.setenv(
        "MEDIA_BRIDGE_OMNIROUTE_BASE_URL",
        "http://127.0.0.1:20128/v1/responses",
    )
    monkeypatch.setenv("UNRELATED_OMNIROUTE_SECRET", "must-not-be-used")

    with pytest.raises(RuntimeConfigurationError, match="OmniRoute"):
        build_runtime_from_environment()
