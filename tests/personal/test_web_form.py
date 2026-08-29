from pathlib import Path

import httpx
import pytest

from media_bridge_personal.local_state import PersonalStateStore
from media_bridge_personal.web_app import build_personal_web_app


@pytest.mark.asyncio
async def test_settings_html_form_saves_rate_profile(tmp_path: Path) -> None:
    store = PersonalStateStore(root=tmp_path / "state")
    app = build_personal_web_app(state=store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.post(
            "/settings",
            data={"solar_rpm": "100", "solar_tpm": "5000"},
        )
    assert response.status_code == 200
    assert store.load_last_known_good()["rate"] == {"rpm": 100, "tpm": 5000}


@pytest.mark.asyncio
async def test_settings_saves_opencodex_and_solar_connection_metadata(tmp_path: Path) -> None:
    store = PersonalStateStore(root=tmp_path / "state")
    app = build_personal_web_app(state=store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.post(
            "/settings",
            json={
                "solar_rpm": 2000,
                "solar_tpm": 750000,
                "opencodex_endpoint": "http://127.0.0.1:19100/v1/responses",
                "solar_endpoint": "https://api.example.test/v1/chat/completions",
                "solar_model": "solar-pro4",
                "solar_credential_env": "SOLAR_API_KEY",
            },
        )
    assert response.status_code == 200
    snapshot = store.load_last_known_good()
    assert snapshot["connection"] == {
        "opencodex_endpoint": "http://127.0.0.1:19100/v1/responses",
        "solar_endpoint": "https://api.example.test/v1/chat/completions",
        "solar_model": "solar-pro4",
        "solar_credential_env": "SOLAR_API_KEY",
    }


@pytest.mark.asyncio
async def test_invalid_connection_metadata_preserves_existing_state(tmp_path: Path) -> None:
    store = PersonalStateStore(root=tmp_path / "state")
    store.publish(
        {
            "version": 1,
            "rate": {"rpm": 2000, "tpm": 750000},
            "connection": {
                "opencodex_endpoint": "http://127.0.0.1:19100/v1/responses",
                "solar_endpoint": "https://api.example.test/v1/chat/completions",
                "solar_model": "solar-pro4",
                "solar_credential_env": "SOLAR_API_KEY",
            },
        }
    )
    app = build_personal_web_app(state=store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.post(
            "/settings",
            json={
                "solar_rpm": 2000,
                "solar_tpm": 750000,
                "opencodex_endpoint": "file:///unsafe",
                "solar_endpoint": "http://not-https",
                "solar_model": "",
                "solar_credential_env": "not-an-env",
            },
        )
    assert response.status_code == 400
    assert store.load_last_known_good()["version"] == 1


@pytest.mark.asyncio
async def test_first_run_shows_connection_fields_without_secret_input(tmp_path: Path) -> None:
    app = build_personal_web_app(state=PersonalStateStore(root=tmp_path / "state"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert 'name="opencodex_endpoint"' in response.text
    assert 'name="solar_endpoint"' in response.text
    assert 'name="solar_model"' in response.text
    assert 'name="solar_credential_env"' in response.text
    assert 'name="solar_api_key"' not in response.text
