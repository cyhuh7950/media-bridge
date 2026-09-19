from __future__ import annotations

import base64
import logging

import pytest
from sqlalchemy import text
from starlette.testclient import TestClient

from media_bridge_control.api import build_control_app
from media_bridge_control.secrets import GatewaySecretResolver
from tests.control.p2b_helpers import StubGatewayClient, configured_control, sample_password


def test_test_lab_bodies_do_not_persist_to_database_audit_or_logs(
    migrated_postgres: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    media_marker = b"media-body-retention-marker"
    caplog.set_level(logging.DEBUG)
    database, service = configured_control(migrated_postgres)
    app = build_control_app(
        service=service,
        allowed_origin="https://control.test",
        allowed_host="control.test",
        gateway_client=StubGatewayClient(),
        secret_resolver=GatewaySecretResolver(),
    )
    client = TestClient(app, base_url="https://control.test")
    login = client.post(
        "/admin/v1/auth/login",
        headers={"origin": "https://control.test"},
        json={"username": "admin", "password": sample_password()},
    )
    headers = {
        "origin": "https://control.test",
        "x-csrf-token": login.json()["csrf_token"],
    }
    response = client.post(
        "/admin/v1/test-lab/preview",
        headers=headers,
        json={
            "target_model": "text-model",
            "conversion_profile": "error_screenshot",
            "user_request": "private-user-request-marker",
            "media_type": "image",
            "filename": "error.png",
            "declared_mime": "image/png",
            "media_base64": base64.b64encode(media_marker).decode(),
        },
    )
    assert response.status_code == 200

    safe_queries = [
        text("SELECT row_to_json(entry)::text FROM connections AS entry"),
        text("SELECT row_to_json(entry)::text FROM audit_events AS entry"),
        text("SELECT row_to_json(entry)::text FROM operational_events AS entry"),
    ]
    with database.session() as session:
        dump = " ".join(
            str(value)
            for query in safe_queries
            for value in session.scalars(query)
        )
    for marker in (
        media_marker.decode(),
        base64.b64encode(media_marker).decode(),
        "private-user-request-marker",
        "OCR SAFE RESULT",
    ):
        assert marker not in dump
        assert marker not in caplog.text
    database.close()
