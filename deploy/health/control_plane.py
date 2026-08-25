"""Control Plane liveness probe."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

MAX_HEALTH_BYTES = 4_096


class HealthCheckError(RuntimeError):
    pass


def fetch_json(url: str) -> dict[str, Any]:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username is not None:
        raise HealthCheckError("control_not_ready")
    request = Request(url, headers={"accept": "application/json"})  # noqa: S310
    try:
        with urlopen(request, timeout=2) as response:  # noqa: S310
            body = response.read(MAX_HEALTH_BYTES + 1)
    except OSError as error:
        raise HealthCheckError("control_not_ready") from error
    if len(body) > MAX_HEALTH_BYTES:
        raise HealthCheckError("control_not_ready")
    try:
        value = json.loads(body)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise HealthCheckError("control_not_ready") from error
    if not isinstance(value, dict):
        raise HealthCheckError("control_not_ready")
    return value


def check(url: str) -> None:
    try:
        value = fetch_json(url)
    except (OSError, HealthCheckError) as error:
        raise HealthCheckError("control_not_ready") from error
    if value.get("status") != "ok":
        raise HealthCheckError("control_not_ready")


def main() -> int:
    try:
        check("http://127.0.0.1:8081/admin/v1/health")
    except HealthCheckError:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
