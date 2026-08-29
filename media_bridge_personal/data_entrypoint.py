"""Loopback-only executable entrypoint for the personal Data runtime."""

from __future__ import annotations

from pathlib import Path

import uvicorn

from media_bridge_personal.data_app import build_personal_data_app
from media_bridge_personal.local_state import PersonalStateStore


def run_personal_data(*, profile_root: Path, port: int, host: str = "127.0.0.1") -> None:
    if host != "127.0.0.1":
        raise ValueError("personal data runtime must bind loopback only")
    if not 1 <= port <= 65_535:
        raise ValueError("personal data port is invalid")
    app = build_personal_data_app(state=PersonalStateStore(root=profile_root / "state"))
    uvicorn.run(
        app,
        host=host,
        port=port,
        access_log=False,
        server_header=False,
    )
