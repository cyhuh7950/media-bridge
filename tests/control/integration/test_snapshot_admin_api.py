from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from starlette.testclient import TestClient

from media_bridge_control.api import build_control_app
from media_bridge_control.bootstrap import ControlPlaneService
from media_bridge_control.db import Database
from media_bridge_control.security import SecurityContext
from media_bridge_control.snapshots import SnapshotPublisher, SnapshotSigner
from tests.control.snapshot_helpers import private_key_pem


def _client(database_url: str, output_path: Path) -> tuple[TestClient, str, Database]:
    database = Database(database_url)
    service = ControlPlaneService(
        database=database,
        security=SecurityContext(pepper=b"a" * 32),
        now=lambda: datetime(2026, 8, 24, 6, 0, tzinfo=UTC),
    )
    token = service.issue_bootstrap_token()
    value = "correct horse battery staple"
    service.complete_bootstrap(token=token, username="admin", password=value)
    publisher = SnapshotPublisher(
        database=database,
        signer=SnapshotSigner(key_id="test-key", private_key_pem=private_key_pem()),
        output_path=output_path,
        now=lambda: datetime(2026, 8, 24, 6, 0, tzinfo=UTC),
    )
    client = TestClient(
        build_control_app(
            service=service,
            allowed_origin="https://control.test",
            allowed_host="control.test",
            snapshot_publisher=publisher,
        ),
        base_url="https://control.test",
    )
    login = client.post(
        "/admin/v1/auth/login",
        headers={"origin": "https://control.test"},
        json={"username": "admin", "password": value},
    )
    return client, login.json()["csrf_token"], database


def test_validated_draft_is_required_before_snapshot_publish_and_rollback(
    migrated_postgres: str,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "active.json"
    client, csrf, database = _client(migrated_postgres, output_path)
    headers = {"origin": "https://control.test", "x-csrf-token": csrf}
    reviewed = datetime(2026, 8, 24, 6, 0, tzinfo=UTC)
    assert (
        client.post(
            "/admin/v1/models",
            headers=headers,
            json={
                "model_id": "vendor/text-model",
                "aliases": [],
                "input_modalities": ["text"],
                "evidence": "vendor capability statement",
                "reviewed_at": reviewed.isoformat(),
                "expires_at": (reviewed + timedelta(days=30)).isoformat(),
                "pdf_passthrough_verified": False,
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
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
        ).status_code
        == 201
    )

    direct = client.post("/admin/v1/snapshots", headers=headers, json={})
    assert direct.status_code == 400
    draft = client.post("/admin/v1/drafts/validate", headers=headers, json={})
    assert draft.status_code == 201
    published = client.post(
        "/admin/v1/snapshots",
        headers=headers,
        json={"draft_id": draft.json()["draft_id"]},
    )
    assert published.status_code == 201
    assert published.json()["version"] == 1
    rolled_back = client.post("/admin/v1/snapshots/1/rollback", headers=headers, json={})
    assert rolled_back.status_code == 201
    assert rolled_back.json()["version"] == 2
    assert output_path.is_file()
    assert [item["version"] for item in client.get("/admin/v1/snapshots").json()] == [2, 1]
    database.close()
