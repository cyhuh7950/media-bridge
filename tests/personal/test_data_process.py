from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


def _entrypoint_exists() -> bool:
    try:
        from media_bridge_personal.data_entrypoint import run_personal_data
    except ModuleNotFoundError:
        return False
    return callable(run_personal_data)


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as socket_handle:
        socket_handle.bind(("127.0.0.1", 0))
        return int(socket_handle.getsockname()[1])


def _wait_for_status(url: str) -> httpx.Response:
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=0.2)
        except httpx.HTTPError:
            time.sleep(0.02)
            continue
        if response.status_code == 200:
            return response
        time.sleep(0.02)
    raise AssertionError("personal data process did not become ready")


def _wait_for_port_closed(port: int) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as socket_handle:
            if socket_handle.connect_ex(("127.0.0.1", port)) != 0:
                return
        time.sleep(0.02)
    raise AssertionError("personal data process port remained open")


def test_data_process_binds_loopback_serves_lkg_and_exits_cleanly(tmp_path: Path) -> None:
    """Catches an entrypoint that cannot serve local LKG without legacy infrastructure."""

    assert _entrypoint_exists(), "personal data entrypoint is not implemented"
    state_root = tmp_path / "state"
    from media_bridge_personal.local_state import PersonalStateStore

    PersonalStateStore(root=state_root).publish({"version": 7, "mode": "safe"})
    port = _free_loopback_port()
    process = subprocess.Popen(  # noqa: S603 - fixed local test command, no shell.
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; "
                "from media_bridge_personal.data_entrypoint import run_personal_data; "
                f"run_personal_data(profile_root=Path({str(tmp_path)!r}), port={port})"
            ),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        response = _wait_for_status(f"http://127.0.0.1:{port}/status")
        assert response.json() == {"status": "ready", "snapshot_version": 7}
    finally:
        process.terminate()
        process.wait(timeout=2.0)

    _wait_for_port_closed(port)


def test_connection_metadata_maps_to_process_configuration(monkeypatch, tmp_path: Path) -> None:
    import os

    from media_bridge_personal.data_entrypoint import _apply_connection_settings
    from media_bridge_personal.local_state import PersonalStateStore

    store = PersonalStateStore(root=tmp_path / "state")
    store.publish(
        {
            "version": 2,
            "connection": {
                "opencodex_endpoint": "http://127.0.0.1:19100/v1/responses",
                "solar_endpoint": "https://api.example.test/v1/chat/completions",
                "solar_model": "solar-pro4",
                "solar_credential_env": "SOLAR_API_KEY",
            },
        }
    )
    monkeypatch.delenv("MEDIA_BRIDGE_SOLAR_ENDPOINT", raising=False)
    monkeypatch.delenv("MEDIA_BRIDGE_SOLAR_MODEL", raising=False)
    monkeypatch.delenv("MEDIA_BRIDGE_SOLAR_CREDENTIAL_ENV", raising=False)

    _apply_connection_settings(store)

    assert os.environ["MEDIA_BRIDGE_SOLAR_ENDPOINT"] == "https://api.example.test/v1/chat/completions"
    assert os.environ["MEDIA_BRIDGE_SOLAR_MODEL"] == "solar-pro4"
    assert os.environ["MEDIA_BRIDGE_SOLAR_CREDENTIAL_ENV"] == "SOLAR_API_KEY"


def test_gateway_configuration_failure_keeps_data_process_available(monkeypatch) -> None:
    from media_bridge_gateway.entrypoints import GatewayConfigurationError
    from media_bridge_personal import data_entrypoint

    monkeypatch.setenv("MEDIA_BRIDGE_GATEWAY_ENABLED", "true")

    def fail() -> object:
        raise GatewayConfigurationError("required environment setting is missing")

    monkeypatch.setattr(data_entrypoint, "build_gateway_process_from_environment", fail)

    assert data_entrypoint._build_optional_gateway() is None
