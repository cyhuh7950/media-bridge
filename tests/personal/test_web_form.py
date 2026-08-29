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
