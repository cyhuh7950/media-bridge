from __future__ import annotations

import httpx

from tests.packaging.e2e.conftest import DATA_PORT, compose, data_authorization, login


def test_restart_and_control_outage_preserve_last_known_good(control_client: httpx.Client) -> None:
    compose("restart", "media-bridge-control", "media-bridge-data")
    compose("up", "-d", "--wait", "media-bridge-control", "media-bridge-data")
    csrf = login(control_client)
    headers = {"X-CSRF-Token": csrf}
    models = control_client.get("/admin/v1/models", headers=headers).json()
    assert models[0]["model_id"] == "vendor/text-model"
    assert control_client.get("/admin/v1/snapshots", headers=headers).json()[0]["version"] == 1

    compose("stop", "media-bridge-control")
    status = httpx.get(
        f"http://127.0.0.1:{DATA_PORT}/status",
        headers=data_authorization(),
        timeout=15,
    )
    assert status.status_code == 200
    assert status.json() == {"status": "ready", "snapshot_version": 1}
    compose("up", "-d", "--wait", "media-bridge-control")
