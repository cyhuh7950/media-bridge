"""Data Plane readiness probe with first-snapshot fail-closed semantics."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from urllib.parse import urlsplit

MAX_SNAPSHOT_BYTES = 1_048_576


class HealthCheckError(RuntimeError):
    pass


def gateway_listening(url: str) -> bool:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.path != "/status"
    ):
        raise HealthCheckError("gateway_not_ready")
    try:
        with socket.create_connection(("127.0.0.1", parsed.port or 80), timeout=2):
            return True
    except OSError as error:
        raise HealthCheckError("gateway_not_ready") from error


def check(*, snapshot_path: Path, url: str) -> None:
    try:
        if (
            snapshot_path.is_symlink()
            or not snapshot_path.is_file()
            or snapshot_path.stat().st_size < 2
            or snapshot_path.stat().st_size > MAX_SNAPSHOT_BYTES
        ):
            raise HealthCheckError("snapshot_not_ready")
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except HealthCheckError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise HealthCheckError("snapshot_not_ready") from error
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("version"), int):
        raise HealthCheckError("snapshot_not_ready")
    if not gateway_listening(url):
        raise HealthCheckError("gateway_not_ready")


def main() -> int:
    try:
        check(
            snapshot_path=Path(
                os.environ.get(
                    "MEDIA_BRIDGE_SNAPSHOT_PATH",
                    "/var/lib/media-bridge/snapshots/active.json",
                )
            ),
            url="http://127.0.0.1:8001/status",
        )
    except HealthCheckError:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
