from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from media_bridge.assets import AssetStore
from media_bridge.http_app import build_http_app
from media_bridge.mcp_server import build_mcp_server


class UnusedService:
    pass


@pytest.mark.asyncio
async def test_http_health_is_available_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MEDIA_BRIDGE_SERVICE_TOKEN", "service-secret")
    store = AssetStore(tmp_path / "assets", max_bytes=16)
    server = build_mcp_server(UnusedService(), tenant_provider=lambda: "tenant-a")
    app = build_http_app(server=server, asset_store=store, max_upload_bytes=16)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_http_upload_requires_bearer_and_tenant(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MEDIA_BRIDGE_SERVICE_TOKEN", "service-secret")
    store = AssetStore(tmp_path / "assets", max_bytes=16)
    server = build_mcp_server(UnusedService(), tenant_provider=lambda: "tenant-a")
    app = build_http_app(server=server, asset_store=store, max_upload_bytes=16)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        unauthenticated = await client.post("/assets", content=b"image")
        missing_tenant = await client.post(
            "/assets",
            headers={"Authorization": "Bearer service-secret"},
            content=b"image",
        )

    assert unauthenticated.status_code == 401
    assert missing_tenant.status_code == 400


@pytest.mark.asyncio
async def test_authenticated_upload_is_bounded_and_tenant_scoped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MEDIA_BRIDGE_SERVICE_TOKEN", "service-secret")
    store = AssetStore(tmp_path / "assets", max_bytes=16)
    server = build_mcp_server(UnusedService(), tenant_provider=lambda: "tenant-a")
    app = build_http_app(server=server, asset_store=store, max_upload_bytes=16)
    headers = {
        "Authorization": "Bearer service-secret",
        "X-Media-Bridge-Tenant": "tenant-a",
        "X-Filename": "capture.png",
        "Content-Type": "image/png",
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        uploaded = await client.post("/assets", headers=headers, content=b"safe-test-bytes")
        oversized = await client.post("/assets", headers=headers, content=b"x" * 17)

    assert uploaded.status_code == 201
    asset_id = uploaded.json()["asset_id"]
    assert asset_id.startswith("mb_")
    assert oversized.status_code == 413

    consumed = store.consume(asset_id=asset_id, tenant_id="tenant-a")
    assert consumed.data == b"safe-test-bytes"
    assert list((tmp_path / "assets").glob("*.bin")) == []
