from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from media_bridge_gateway.app import build_gateway_app
from media_bridge_gateway.rate_limit import CredentialRouteRateLimiter
from tests.gateway.helpers import TEST_RAW_CREDENTIAL, build_test_runtime, png_bytes


def _limiter() -> CredentialRouteRateLimiter:
    return CredentialRouteRateLimiter(
        capacity=20,
        refill_per_second=20,
        max_keys=20,
        idle_ttl_seconds=60,
    )


@pytest.mark.asyncio
async def test_authenticated_status_prepare_and_asset_cleanup(tmp_path: Path) -> None:
    runtime, downstream, asset_store = build_test_runtime(tmp_path)
    app = build_gateway_app(
        runtime=runtime,
        asset_store=asset_store,
        rate_limiter=_limiter(),
    )
    authorization = {"Authorization": f"Bearer {TEST_RAW_CREDENTIAL}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://gateway.test",
    ) as client:
        status = await client.get("/status", headers=authorization)
        uploaded = await client.post(
            "/assets",
            headers={
                **authorization,
                "Content-Type": "image/png",
                "X-Filename": "error.png",
            },
            content=png_bytes(),
        )
        asset_id = uploaded.json()["asset_id"]
        prepared = await client.post(
            "/v1/prepare",
            headers=authorization,
            json={
                "content": [
                    {"type": "text", "text": "이 오류를 설명해줘"},
                    {
                        "type": "media",
                        "media_type": "image",
                        "source": {"kind": "asset_id", "asset_id": asset_id},
                        "filename": "error.png",
                        "declared_mime": "image/png",
                    },
                ],
                "target": {"registry_id": "text-model"},
                "conversion_profile": "error_screenshot",
            },
        )
        cleanup = await client.delete(f"/assets/{asset_id}", headers=authorization)
        cleanup_again = await client.delete(f"/assets/{asset_id}", headers=authorization)

    assert status.status_code == 200
    assert status.json() == {"status": "ready", "snapshot_version": 1}
    assert uploaded.status_code == 201
    assert prepared.status_code == 200
    assert prepared.json()["action"] == "converted"
    assert prepared.json()["original_image_removed"] is True
    assert prepared.json()["sanitized_text"]
    assert cleanup.status_code == 204
    assert cleanup_again.status_code == 204
    assert downstream.requests == []


@pytest.mark.asyncio
async def test_lifecycle_routes_reject_admin_cookie_and_missing_scope(
    tmp_path: Path,
) -> None:
    runtime, downstream, asset_store = build_test_runtime(tmp_path)
    app = build_gateway_app(
        runtime=runtime,
        asset_store=asset_store,
        rate_limiter=_limiter(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://gateway.test",
    ) as client:
        missing = await client.get("/status")
        cookie = await client.get(
            "/status",
            headers={
                "Authorization": f"Bearer {TEST_RAW_CREDENTIAL}",
                "Cookie": "mb_admin_session=must-not-cross-boundary",
            },
        )

    assert missing.status_code == 401
    assert cookie.status_code == 403
    assert downstream.requests == []
