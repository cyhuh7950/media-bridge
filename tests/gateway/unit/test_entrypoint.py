from __future__ import annotations

import asyncio
import base64
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from media_bridge.config_snapshot import SnapshotVerificationError
from media_bridge_control.snapshots import SnapshotSigner
from media_bridge_gateway.entrypoints import (
    GatewayConfigurationError,
    build_gateway_process_from_environment,
    run_gateway,
)
from tests.control.snapshot_helpers import private_key_pem, snapshot_body


def _install_valid_gateway_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    signer = SnapshotSigner(key_id="gateway-key", private_key_pem=private_key_pem())
    body = snapshot_body()
    llm_provider_id = "00000000-0000-0000-0000-000000000099"
    body["providers"].append(
        {
            "id": llm_provider_id,
            "kind": "llm",
            "enabled": True,
            "catalog_id": "upstage-solar",
            "protocol": "openai-chat-completions",
            "endpoint": "https://api.upstage.ai/v1/chat/completions",
            "model_id": "solar-pro4",
            "reasoning_effort": "high",
        }
    )
    body["registry"]["models"][0]["provider_id"] = llm_provider_id
    body["registry"]["models"][0]["aliases"] = ["public/text-alias"]
    snapshot = signer.sign(
        snapshot_id=UUID("00000000-0000-0000-0000-000000000001"),
        version=1,
        issued_at=datetime(2026, 8, 24, 8, 0, tzinfo=UTC),
        body=body,
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
        "MEDIA_BRIDGE_DOWNSTREAM_RESPONSES_URL": (
            "http://127.0.0.1:20128/v1/responses"
        ),
        "MEDIA_BRIDGE_DOWNSTREAM_API_KEY": "downstream-test-value",
        "MEDIA_BRIDGE_CONTROL_DATABASE_URL": "postgresql+psycopg://test:test@localhost/test",
    }
    for name, value in settings.items():
        monkeypatch.setenv(name, value)

    class FakeSession:
        def __init__(self) -> None:
            self.catalog_reads = 0
            self.provider_id_reads: list[object] = []

        def scalar(self, _statement: object) -> object:
            providers = [
                SimpleNamespace(
                    id="00000000-0000-0000-0000-000000000001",
                    catalog_id="upstage-document-parse",
                    endpoint=os.environ.get(
                        "TEST_DB_OCR_ENDPOINT", "https://provider.test/v1/ocr"
                    ),
                    model_id="document-parse",
                    enabled=True,
                    encrypted_api_key="encrypted-ocr",
                ),
                SimpleNamespace(
                    id="00000000-0000-0000-0000-000000000002",
                    catalog_id="upstage-solar",
                    endpoint="https://api.upstage.ai/v1",
                    model_id="solar-pro4",
                    enabled=True,
                    encrypted_api_key="encrypted-solar",
                ),
            ]
            value = providers[self.catalog_reads]
            self.catalog_reads += 1
            return value

        def get(self, _model: object, provider_id: object) -> object:
            self.provider_id_reads.append(provider_id)
            return SimpleNamespace(
                id=provider_id,
                enabled=True,
                encrypted_api_key="encrypted-provider",
            )

    class FakeDatabase:
        def __init__(self, _url: str) -> None:
            self.session_value = FakeSession()

        @contextmanager
        def session(self) -> Any:
            yield self.session_value

        def close(self) -> None:
            return None

    monkeypatch.setattr("media_bridge_gateway.entrypoints.Database", FakeDatabase)
    monkeypatch.setattr(
        "media_bridge_gateway.entrypoints.SecurityContext.decrypt_secret",
        lambda _self, _value: "db-decrypted-key",
    )
    return snapshot_path


def _track_async_clients(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    clients: list[Any] = []

    class TrackingAsyncClient:
        def __init__(self, **kwargs: object) -> None:
            self.closed = False
            self.kwargs = kwargs
            clients.append(self)

        async def aclose(self) -> None:
            self.closed = True

    monkeypatch.setattr(
        "media_bridge_gateway.entrypoints.httpx.AsyncClient",
        TrackingAsyncClient,
    )
    return clients


def test_gateway_backend_client_uses_explicit_ca_without_trusting_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_valid_gateway_environment(tmp_path, monkeypatch)
    ca_file = tmp_path / "staging-ca.pem"
    ca_file.write_text("test-ca")
    monkeypatch.setenv("MEDIA_BRIDGE_BACKEND_CA_FILE", str(ca_file))
    clients = _track_async_clients(monkeypatch)

    process = build_gateway_process_from_environment()

    assert len(clients) == 1
    assert clients[0].kwargs["verify"] == str(ca_file)
    assert all(client.kwargs["trust_env"] is False for client in clients)
    asyncio.run(process.close())


def test_gateway_console_entrypoint_is_callable() -> None:
    assert callable(run_gateway)


def test_gateway_process_factory_builds_from_strict_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_valid_gateway_environment(tmp_path, monkeypatch)

    process = build_gateway_process_from_environment()

    assert process.runtime.current().version == 1
    assert process.runtime.current().models == ("vendor/text-model",)
    assert process.runtime.current().gate.resolve_capability(
        "public/text-alias"
    ).state.value == "non_vision"
    downstream = process.runtime.current().downstream
    assert downstream._provider_for_target("vendor/text-model")["id"] == (
        "00000000-0000-0000-0000-000000000099"
    )
    provider = downstream._provider_for_target("vendor/text-model")
    backend = downstream._backend_factory(provider)
    assert backend._credential_loader() == "db-decrypted-key"
    assert process.database.session_value.provider_id_reads == [
        UUID("00000000-0000-0000-0000-000000000099")
    ]
    assert downstream._provider_for_target("public/text-alias")["id"] == provider["id"]
    asyncio.run(process.close())
    assert list((tmp_path / "assets").iterdir()) == []


def test_invalid_gateway_port_fails_before_process_resources_are_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEDIA_BRIDGE_GATEWAY_PORT", "0")

    with pytest.raises(GatewayConfigurationError, match="allowed range"):
        run_gateway()


def test_invalid_backend_endpoint_closes_partial_clients(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_valid_gateway_environment(tmp_path, monkeypatch)
    monkeypatch.setenv("TEST_DB_OCR_ENDPOINT", "http://provider.test/v1/ocr")
    clients = _track_async_clients(monkeypatch)

    with pytest.raises(ValueError, match="credential-free HTTPS"):
        build_gateway_process_from_environment()

    assert clients
    assert all(client.closed is True for client in clients)


def test_tampered_snapshot_closes_partial_clients(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot_path = _install_valid_gateway_environment(tmp_path, monkeypatch)
    snapshot_path.write_text("{}")
    clients = _track_async_clients(monkeypatch)

    with pytest.raises(SnapshotVerificationError, match="snapshot"):
        build_gateway_process_from_environment()

    assert len(clients) == 1
    assert all(client.closed is True for client in clients)


def test_app_build_failure_closes_partial_clients(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_valid_gateway_environment(tmp_path, monkeypatch)
    clients = _track_async_clients(monkeypatch)

    def fail_app_build(**_kwargs: object) -> object:
        raise RuntimeError("simulated app build failure")

    monkeypatch.setattr(
        "media_bridge_gateway.entrypoints.build_gateway_app",
        fail_app_build,
    )

    with pytest.raises(RuntimeError, match="app build failure"):
        build_gateway_process_from_environment()

    assert len(clients) == 1
    assert all(client.closed is True for client in clients)
