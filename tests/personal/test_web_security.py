from pathlib import Path

import httpx
import pytest

from media_bridge_personal.local_state import PersonalStateStore
from media_bridge_personal.web_app import build_personal_web_app


@pytest.mark.asyncio
async def test_web_rejects_non_loopback_host(tmp_path: Path) -> None:
    app = build_personal_web_app(state=PersonalStateStore(root=tmp_path / "state"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.get("/", headers={"Host": "evil.example"})
    assert response.status_code == 400
