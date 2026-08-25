from __future__ import annotations

import httpx

from tests.packaging.e2e.conftest import (
    DATA_PORT,
    compose,
    data_authorization,
    docker,
    login,
)


def test_image_recreate_and_rollback_preserve_schema_and_snapshot(
    control_client: httpx.Client,
) -> None:
    schema = compose(
        "exec",
        "-T",
        "media-bridge-db",
        "psql",
        "-U",
        "media_bridge",
        "-d",
        "media_bridge",
        "-Atqc",
        "SELECT version_num FROM alembic_version",
    )
    assert schema.stdout.strip() == "0002_connections"
    candidate = {
        "MEDIA_BRIDGE_TEST_CONTROL_IMAGE": "media-bridge-control:p5-candidate",
        "MEDIA_BRIDGE_TEST_DATA_IMAGE": "media-bridge-data:p5-candidate",
    }
    try:
        docker(
            "image",
            "tag",
            "media-bridge-control:test",
            candidate["MEDIA_BRIDGE_TEST_CONTROL_IMAGE"],
        )
        docker(
            "image",
            "tag",
            "media-bridge-data:test",
            candidate["MEDIA_BRIDGE_TEST_DATA_IMAGE"],
        )
        compose(
            "up",
            "-d",
            "--force-recreate",
            "--wait",
            "media-bridge-control",
            "media-bridge-data",
            env=candidate,
        )
        assert login(control_client)
        status = httpx.get(
            f"http://127.0.0.1:{DATA_PORT}/status",
            headers=data_authorization(),
            timeout=15,
        )
        assert status.json() == {"status": "ready", "snapshot_version": 1}

        compose(
            "up",
            "-d",
            "--force-recreate",
            "--wait",
            "media-bridge-control",
            "media-bridge-data",
        )
        assert login(control_client)
        rolled_back = httpx.get(
            f"http://127.0.0.1:{DATA_PORT}/status",
            headers=data_authorization(),
            timeout=15,
        )
        assert rolled_back.json() == {"status": "ready", "snapshot_version": 1}
    finally:
        docker(
            "image",
            "rm",
            *candidate.values(),
            check=False,
        )
