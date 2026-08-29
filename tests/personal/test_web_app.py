from pathlib import Path

import httpx
import pytest

from media_bridge_personal.local_state import PersonalStateStore
from media_bridge_personal.web_app import build_personal_web_app


@pytest.mark.asyncio
async def test_first_run_renders_safe_rate_defaults(tmp_path: Path) -> None:
    app = build_personal_web_app(state=PersonalStateStore(root=tmp_path / "state"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert "2,000" not in response.text
    assert 'value="2000"' in response.text
    assert 'value="750000"' in response.text
    assert "외부 데이터베이스" in response.text


@pytest.mark.asyncio
async def test_settings_save_persists_rate_profile(tmp_path: Path) -> None:
    store = PersonalStateStore(root=tmp_path / "state")
    app = build_personal_web_app(state=store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.post("/settings", json={"solar_rpm": 100, "solar_tpm": 5000})
    assert response.status_code == 200
    assert store.load_last_known_good()["rate"] == {"rpm": 100, "tpm": 5000}


@pytest.mark.asyncio
async def test_invalid_rate_profile_is_rejected_without_state_change(tmp_path: Path) -> None:
    store = PersonalStateStore(root=tmp_path / "state")
    store.publish({"version": 1, "rate": {"rpm": 2000, "tpm": 750000}})
    app = build_personal_web_app(state=store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.post("/settings", json={"solar_rpm": 0, "solar_tpm": 1})
    assert response.status_code == 400
    assert store.load_last_known_good()["rate"] == {"rpm": 2000, "tpm": 750000}
