"""Loopback-only executable entrypoint for the personal Web settings runtime."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from media_bridge_personal.local_state import PersonalStateStore
from media_bridge_personal.web_app import build_personal_web_app


def run_personal_web(*, profile_root: Path, port: int, host: str = "127.0.0.1") -> None:
    if host != "127.0.0.1":
        raise ValueError("personal web runtime must bind loopback only")
    if not 1 <= port <= 65_535:
        raise ValueError("personal web port is invalid")
    app = build_personal_web_app(state=PersonalStateStore(root=profile_root / "state"))
    uvicorn.run(app, host=host, port=port, access_log=False, server_header=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Media Bridge personal loopback Web UI")
    parser.add_argument("--profile-root", type=Path, default=Path.home() / ".media-bridge")
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("MEDIA_BRIDGE_WEB_PORT", "8765"))
    )
    args = parser.parse_args()
    run_personal_web(profile_root=args.profile_root, port=args.port)


if __name__ == "__main__":
    main()
