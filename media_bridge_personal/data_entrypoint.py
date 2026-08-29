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
from media_bridge_personal.local_state import PersonalStateStore


def run_personal_data(*, profile_root: Path, port: int, host: str = "127.0.0.1") -> None:
    if host != "127.0.0.1":
        raise ValueError("personal data runtime must bind loopback only")
    if not 1 <= port <= 65_535:
        raise ValueError("personal data port is invalid")
    gateway_process: GatewayProcess | None = None
    if os.environ.get("MEDIA_BRIDGE_GATEWAY_ENABLED", "").strip().lower() == "true":
        gateway_process = build_gateway_process_from_environment()
    app = build_personal_data_app(
        state=PersonalStateStore(root=profile_root / "state"),
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
