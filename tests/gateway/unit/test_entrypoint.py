from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from media_bridge_control.snapshots import SnapshotSigner
from media_bridge_gateway.entrypoints import (
    GatewayConfigurationError,
    build_gateway_process_from_environment,
    run_gateway,
)
from tests.control.snapshot_helpers import private_key_pem, snapshot_body


def test_gateway_console_entrypoint_is_callable() -> None:
    assert callable(run_gateway)


def test_gateway_process_factory_builds_from_strict_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signer = SnapshotSigner(key_id="gateway-key", private_key_pem=private_key_pem())
    snapshot = signer.sign(
        snapshot_id=UUID("00000000-0000-0000-0000-000000000001"),
        version=1,
        issued_at=datetime(2026, 8, 24, 8, 0, tzinfo=UTC),
        body=snapshot_body(),
    )
    snapshot_path = tmp_path / "active-snapshot.json"
    snapshot_path.write_text(snapshot.model_dump_json())
    public_key = base64.urlsafe_b64encode(signer.public_key_bytes).rstrip(b"=").decode()
    settings = {
        "MEDIA_BRIDGE_SNAPSHOT_KEY_ID": "gateway-key",
        "MEDIA_BRIDGE_SNAPSHOT_PUBLIC_KEY": public_key,
        "MEDIA_BRIDGE_SNAPSHOT_PATH": str(snapshot_path),
        "MEDIA_BRIDGE_ASSET_ROOT": str(tmp_path / "assets"),
        "MEDIA_BRIDGE_GATEWAY_AUTH_PEPPER": "p" * 32,
        "MEDIA_BRIDGE_RECEIPT_SECRET": "r" * 32,
        "MEDIA_BRIDGE_OCR_ENDPOINT": "https://provider.test/v1/ocr",
        "MEDIA_BRIDGE_OCR_API_KEY": "ocr-test-value",
        "MEDIA_BRIDGE_VISION_ENDPOINT": "https://provider.test/v1/responses",
        "MEDIA_BRIDGE_VISION_MODEL": "vision-model",
        "MEDIA_BRIDGE_VISION_API_KEY": "vision-test-value",
        "MEDIA_BRIDGE_DOWNSTREAM_RESPONSES_URL": "http://127.0.0.1:20128/v1/responses",
        "MEDIA_BRIDGE_DOWNSTREAM_API_KEY": "downstream-test-value",
    }
    for name, value in settings.items():
        monkeypatch.setenv(name, value)

    process = build_gateway_process_from_environment()

    assert process.runtime.current().version == 1
    asyncio.run(process.close())
    assert list((tmp_path / "assets").iterdir()) == []


def test_invalid_gateway_port_fails_before_process_resources_are_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEDIA_BRIDGE_GATEWAY_PORT", "0")

    with pytest.raises(GatewayConfigurationError, match="allowed range"):
        run_gateway()
