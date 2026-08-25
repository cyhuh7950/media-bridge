"""Issue the one-time initial bootstrap token from the Control Plane container."""

from __future__ import annotations

import json

from media_bridge_control.entrypoints import require_migration_head
from media_bridge_control.runtime import build_control_runtime
from media_bridge_control.settings import ControlSettings


def main() -> int:
    settings = ControlSettings.from_environment()
    require_migration_head(settings.database_url)
    runtime = build_control_runtime(settings)
    try:
        token = runtime.service.issue_bootstrap_token()
        print(json.dumps({"bootstrap_token": token}, sort_keys=True))
    finally:
        runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
