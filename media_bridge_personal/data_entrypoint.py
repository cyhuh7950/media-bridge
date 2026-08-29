"""Loopback-only executable entrypoint for the personal Data runtime."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import uvicorn

from media_bridge_gateway.entrypoints import (
    GatewayProcess,
    build_gateway_process_from_environment,
)
from media_bridge_personal.data_app import build_personal_data_app
from media_bridge_personal.local_state import LocalStateError, PersonalStateStore


def _apply_connection_settings(state: PersonalStateStore) -> None:
    try:
        snapshot = state.load_last_known_good()
    except LocalStateError:
        return
    connection = snapshot.get("connection")
    if not isinstance(connection, dict):
        return
    settings = {
        "MEDIA_BRIDGE_SOLAR_ENDPOINT": connection.get("solar_endpoint"),
        "MEDIA_BRIDGE_SOLAR_MODEL": connection.get("solar_model"),
        "MEDIA_BRIDGE_SOLAR_CREDENTIAL_ENV": connection.get("solar_credential_env"),
        "MEDIA_BRIDGE_OCR_ENDPOINT": connection.get("ocr_endpoint"),
        "MEDIA_BRIDGE_OCR_CREDENTIAL_ENV": connection.get("ocr_credential_env"),
        "MEDIA_BRIDGE_VISION_ENDPOINT": connection.get("vision_endpoint"),
        "MEDIA_BRIDGE_VISION_MODEL": connection.get("vision_model"),
        "MEDIA_BRIDGE_VISION_CREDENTIAL_ENV": connection.get("vision_credential_env"),
    }
    for name, value in settings.items():
        if isinstance(value, str) and value:
            os.environ[name] = value


def run_personal_data(*, profile_root: Path, port: int, host: str = "127.0.0.1") -> None:
    if host != "127.0.0.1":
        raise ValueError("personal data runtime must bind loopback only")
    if not 1 <= port <= 65_535:
        raise ValueError("personal data port is invalid")
    state = PersonalStateStore(root=profile_root / "state")
    _apply_connection_settings(state)
    gateway_process: GatewayProcess | None = None
    if os.environ.get("MEDIA_BRIDGE_GATEWAY_ENABLED", "").strip().lower() == "true":
        gateway_process = build_gateway_process_from_environment()
    app = build_personal_data_app(
        state=state,
        responses_app=gateway_process.app if gateway_process is not None else None,
    )
    try:
        uvicorn.run(
            app,
            host=host,
            port=port,
            access_log=False,
            server_header=False,
        )
    finally:
        if gateway_process is not None:
            asyncio.run(gateway_process.close())


def main() -> None:
    parser = argparse.ArgumentParser(description="Media Bridge personal loopback Data runtime")
    parser.add_argument("--profile-root", type=Path, default=Path.home() / ".media-bridge")
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("MEDIA_BRIDGE_DATA_PORT", "8766"))
    )
    args = parser.parse_args()
    run_personal_data(profile_root=args.profile_root, port=args.port)


if __name__ == "__main__":
    main()
