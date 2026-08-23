from __future__ import annotations

from pathlib import Path

import pytest

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
