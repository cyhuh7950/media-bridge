from __future__ import annotations

from datetime import UTC, datetime, timedelta

from starlette.testclient import TestClient

from media_bridge_control.api import build_control_app
from media_bridge_control.bootstrap import ControlPlaneService
from media_bridge_control.db import Database
from media_bridge_control.security import SecurityContext


def _configured_client(database_url: str) -> tuple[TestClient, str, Database]:
    database = Database(database_url)
    service = ControlPlaneService(
        database=database,
        security=SecurityContext(pepper=b"c" * 32),
        now=lambda: datetime(2026, 8, 24, 3, 0, tzinfo=UTC),
    )
    token = service.issue_bootstrap_token()
    value = "correct horse battery staple"
    service.complete_bootstrap(token=token, username="admin", password=value)
    client = TestClient(
        build_control_app(
            service=service,
            allowed_origin="https://control.test",
            allowed_host="control.test",
        ),
        base_url="https://control.test",
    )
    login = client.post(
        "/admin/v1/auth/login",
        headers={"origin": "https://control.test"},
        json={"username": "admin", "password": value},
    )
    return client, login.json()["csrf_token"], database


def test_model_and_fail_closed_policy_round_trip(migrated_postgres: str) -> None:
    client, csrf, database = _configured_client(migrated_postgres)
    headers = {"origin": "https://control.test", "x-csrf-token": csrf}
    reviewed = datetime(2026, 8, 24, 3, 0, tzinfo=UTC)
    provider = client.post(
        "/admin/v1/providers",
        headers=headers,
        json={
            "name": "llm-primary",
            "kind": "llm",
            "endpoint": "https://provider.test/v1",
            "secret_ref": {"kind": "env", "identifier": "LLM_API_KEY"},
        },
    ).json()

    model = client.post(
        "/admin/v1/models",
        headers=headers,
        json={
            "provider_id": provider["id"],
            "model_id": "vendor/text-model",
            "aliases": ["text-model"],
            "input_modalities": ["text"],
            "evidence": "vendor capability statement",
            "reviewed_at": reviewed.isoformat(),
            "expires_at": (reviewed + timedelta(days=30)).isoformat(),
            "pdf_passthrough_verified": False,
        },
    )
    assert model.status_code == 201
    assert client.get("/admin/v1/models").json()[0]["model_id"] == "vendor/text-model"

    unsafe_policy = client.post(
        "/admin/v1/policies",
        headers=headers,
        json={
            "name": "unsafe",
            "max_files": 4,
            "max_media_bytes": 2097152,
            "max_pdf_pages": 20,
            "allow_url": False,
            "allow_base64": True,
            "allow_asset": True,
            "allow_local_path": False,
            "fail_closed": False,
        },
    )
    assert unsafe_policy.status_code == 400
    safe_policy = client.post(
        "/admin/v1/policies",
        headers=headers,
        json={
            "name": "default",
            "max_files": 4,
            "max_media_bytes": 2097152,
            "max_pdf_pages": 20,
            "allow_url": False,
            "allow_base64": True,
            "allow_asset": True,
            "allow_local_path": False,
            "fail_closed": True,
        },
    )
    assert safe_policy.status_code == 201
    assert client.get("/admin/v1/policies").json()[0]["fail_closed"] is True
    database.close()


def test_configuration_items_support_guarded_patch_and_delete(
    migrated_postgres: str,
) -> None:
    client, csrf, database = _configured_client(migrated_postgres)
    headers = {"origin": "https://control.test", "x-csrf-token": csrf}
    reviewed = datetime(2026, 8, 24, 3, 0, tzinfo=UTC)
    created_provider = client.post(
        "/admin/v1/providers",
        headers=headers,
        json={
            "name": "vision-primary",
            "kind": "vision",
            "endpoint": "https://provider.test/v1/vision",
            "secret_ref": {
                "kind": "docker_secret",
                "identifier": "vision_api_key",
            },
            "enabled": True,
        },
    ).json()
    created_policy = client.post(
        "/admin/v1/policies",
        headers=headers,
        json={
            "name": "default",
            "max_files": 4,
            "max_media_bytes": 2097152,
            "max_pdf_pages": 20,
            "allow_url": False,
            "allow_base64": True,
            "allow_asset": True,
            "allow_local_path": False,
            "fail_closed": True,
        },
    ).json()
    llm_provider = client.post(
        "/admin/v1/providers",
        headers=headers,
        json={
            "name": "llm-primary",
            "kind": "llm",
            "endpoint": "https://llm.provider.test/v1",
            "secret_ref": {"kind": "env", "identifier": "LLM_API_KEY"},
        },
    ).json()
    created_model = client.post(
        "/admin/v1/models",
        headers=headers,
        json={
            "provider_id": llm_provider["id"],
            "model_id": "vendor/vision-model",
            "aliases": [],
            "input_modalities": ["text", "image"],
            "evidence": "vendor capability statement",
            "reviewed_at": reviewed.isoformat(),
            "pdf_passthrough_verified": False,
        },
    ).json()

    provider_patch = client.patch(
        f"/admin/v1/providers/{created_provider['id']}",
        headers=headers,
        json={"enabled": False},
    )
    assert provider_patch.status_code == 200
    assert provider_patch.json()["enabled"] is False
    model_patch = client.patch(
        f"/admin/v1/models/{created_model['id']}",
        headers=headers,
        json={"evidence": "reviewed vendor documentation"},
    )
    assert model_patch.status_code == 200
    assert model_patch.json()["evidence"] == "reviewed vendor documentation"
    policy_patch = client.patch(
        f"/admin/v1/policies/{created_policy['id']}",
        headers=headers,
        json={"max_files": 8},
    )
    assert policy_patch.status_code == 200
    assert policy_patch.json()["max_files"] == 8

    for collection, item_id in (
        ("models", created_model["id"]),
        ("policies", created_policy["id"]),
        ("providers", created_provider["id"]),
        ("providers", llm_provider["id"]),
    ):
        deleted = client.delete(
            f"/admin/v1/{collection}/{item_id}",
            headers=headers,
        )
        assert deleted.status_code == 204
    for collection in ("models", "policies", "providers"):
        assert client.get(f"/admin/v1/{collection}").json() == []
    database.close()


def test_provider_reasoning_effort_is_validated_and_options_are_authenticated(
    migrated_postgres: str,
) -> None:
    client, csrf, database = _configured_client(migrated_postgres)
    headers = {"origin": "https://control.test", "x-csrf-token": csrf}
    query = "catalog_id=upstage-solar&protocol=openai-chat-completions&model_id=solar-pro4"

    options = client.get(f"/admin/v1/provider-reasoning-options?{query}")
    assert options.status_code == 200
    assert options.json() == {"efforts": ["provider_default", "low", "medium", "high"]}
    assert "credential" not in options.text.lower()

    created = client.post(
        "/admin/v1/providers",
        headers=headers,
        json={
            "name": "solar-reasoning",
            "kind": "llm",
            "catalog_id": "upstage-solar",
            "model_id": "solar-pro4",
            "endpoint": "https://api.upstage.ai/v1/chat/completions",
            "protocol": "openai-chat-completions",
            "secret_ref": {"kind": "db", "identifier": "provider_api_key"},
            "reasoning_effort": "high",
        },
    )
    assert created.status_code == 201
    assert created.json()["reasoning_effort"] == "high"
    assert "encrypted_api_key" not in created.text

    unsupported = client.post(
        "/admin/v1/providers",
        headers=headers,
        json={
            "name": "solar-analysis",
            "kind": "analysis",
            "catalog_id": "upstage-document-parse",
            "model_id": "solar-pro4",
            "endpoint": "https://api.upstage.ai/v1/document-digitization",
            "protocol": "document-digitization",
            "secret_ref": {"kind": "db", "identifier": "provider_api_key"},
            "reasoning_effort": "high",
        },
    )
    assert unsupported.status_code == 409

    changed_model = client.patch(
        f"/admin/v1/providers/{created.json()['id']}",
        headers=headers,
        json={"model_id": "solar-mini"},
    )
    assert changed_model.status_code == 409
    assert client.get("/admin/v1/providers").json()[0]["reasoning_effort"] == "high"

    database.close()


def test_provider_reasoning_options_require_authentication(migrated_postgres: str) -> None:
    database = Database(migrated_postgres)
    service = ControlPlaneService(
        database=database,
        security=SecurityContext(pepper=b"c" * 32),
        now=lambda: datetime(2026, 8, 24, 3, 0, tzinfo=UTC),
    )
    client = TestClient(
        build_control_app(
            service=service,
            allowed_origin="https://control.test",
            allowed_host="control.test",
        ),
        base_url="https://control.test",
    )

    response = client.get(
        "/admin/v1/provider-reasoning-options?catalog_id=upstage-solar"
        "&protocol=openai-chat-completions&model_id=solar-pro4"
    )
    assert response.status_code == 401
    database.close()
