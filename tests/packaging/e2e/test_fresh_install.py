from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from tests.packaging.e2e.conftest import (
    DATA_PORT,
    compose,
    data_authorization,
    issue_bootstrap_token,
    login,
    set_data_credential,
)


def test_fresh_install_onboarding_snapshot_and_data_readiness(control_client: httpx.Client) -> None:
    health = control_client.get("/admin/v1/health")
    assert health.status_code == 200

    token = issue_bootstrap_token()
    bootstrap = control_client.post(
        "/admin/v1/bootstrap",
        headers={"X-Bootstrap-Token": token},
        json={"username": "admin", "password": "correct horse battery staple"},
    )
    assert bootstrap.status_code == 201, bootstrap.text
    assert bootstrap.json()["role"] == "admin"
    assert token not in bootstrap.text

    csrf = login(control_client)
    headers = {"X-CSRF-Token": csrf}
    reviewed = datetime.now(UTC)
    credential = control_client.post(
        "/admin/v1/credentials",
        headers=headers,
        json={
            "name": "isolated-e2e",
            "scopes": ["mcp:invoke", "responses:invoke"],
            "expires_at": (reviewed + timedelta(days=1)).isoformat(),
        },
    )
    assert credential.status_code == 201, credential.text
    set_data_credential(str(credential.json()["credential"]))
    model = control_client.post(
        "/admin/v1/models",
        headers=headers,
        json={
            "model_id": "vendor/text-model",
            "aliases": [],
            "input_modalities": ["text"],
            "evidence": "isolated packaging fixture",
            "reviewed_at": reviewed.isoformat(),
            "expires_at": (reviewed + timedelta(days=30)).isoformat(),
            "pdf_passthrough_verified": False,
        },
    )
    assert model.status_code == 201, model.text
    policy = control_client.post(
        "/admin/v1/policies",
        headers=headers,
        json={
            "name": "default",
            "max_files": 4,
            "max_media_bytes": 2_097_152,
            "max_pdf_pages": 20,
            "allow_url": False,
            "allow_base64": True,
            "allow_asset": True,
            "allow_local_path": False,
            "fail_closed": True,
        },
    )
    assert policy.status_code == 201, policy.text
    draft = control_client.post("/admin/v1/drafts/validate", headers=headers, json={})
    assert draft.status_code == 201, draft.text
    published = control_client.post(
        "/admin/v1/snapshots",
        headers=headers,
        json={"draft_id": draft.json()["draft_id"]},
    )
    assert published.status_code == 201, published.text
    assert published.json()["version"] == 1

    compose("up", "-d", "--wait", "media-bridge-data")
    status = httpx.get(
        f"http://127.0.0.1:{DATA_PORT}/status",
        headers=data_authorization(),
        timeout=15,
    )
    assert status.status_code == 200, status.text
    assert status.json() == {"status": "ready", "snapshot_version": 1}
