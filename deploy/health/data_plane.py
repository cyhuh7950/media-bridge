"""Data Plane readiness probe with first-snapshot fail-closed semantics."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

MAX_HEALTH_BYTES = 4_096
MAX_SNAPSHOT_BYTES = 1_048_576


class HealthCheckError(RuntimeError):
    pass


def fetch_json(url: str) -> dict[str, Any]:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username is not None:
        raise HealthCheckError("gateway_not_ready")
    request = Request(url, headers={"accept": "application/json"})  # noqa: S310
    try:
        with urlopen(request, timeout=2) as response:  # noqa: S310
            body = response.read(MAX_HEALTH_BYTES + 1)
    except OSError as error:
        raise HealthCheckError("gateway_not_ready") from error
    if len(body) > MAX_HEALTH_BYTES:
        raise HealthCheckError("gateway_not_ready")
    try:
        value = json.loads(body)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise HealthCheckError("gateway_not_ready") from error
    if not isinstance(value, dict):
        raise HealthCheckError("gateway_not_ready")
    return value


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
    if fetch_json(url).get("status") != "ready":
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
