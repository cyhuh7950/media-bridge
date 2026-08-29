from __future__ import annotations

from pathlib import Path

import httpx
import pytest


def _types():  # type: ignore[no-untyped-def]
    try:
        from media_bridge_personal.data_app import build_personal_data_app
        from media_bridge_personal.local_state import PersonalStateStore
    except ModuleNotFoundError:
        return None, None
    return build_personal_data_app, PersonalStateStore


@pytest.mark.asyncio
async def test_status_serves_previous_lkg_when_active_snapshot_is_corrupt(tmp_path: Path) -> None:
    """Catches Data status depending on Control or accepting a corrupt active snapshot."""

    build_app, store_type = _types()
    assert build_app is not None and store_type is not None, "personal data app is not implemented"
    store = store_type(root=tmp_path)
    store.publish({"version": 1, "mode": "safe"})
    store.publish({"version": 2, "mode": "safe"})
    (tmp_path / "active.json").write_text('{"version":', encoding="utf-8")
    app = build_app(state=store)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.get("/status")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "snapshot_version": 1}


@pytest.mark.asyncio
async def test_responses_route_returns_structured_unavailable_when_not_configured(
    tmp_path: Path,
) -> None:
    build_app, store_type = _types()
    assert build_app is not None and store_type is not None
    store = store_type(root=tmp_path)
    store.publish({"version": 1, "mode": "safe"})
    app = build_app(state=store)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.post(
            "/v1/responses",
            headers={"content-type": "application/json"},
            json={"model": "solar-pro4", "input": "test"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "gateway_unavailable"
