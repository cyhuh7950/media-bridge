from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from media_bridge_gateway.app import build_gateway_app
from media_bridge_gateway.rate_limit import CredentialRouteRateLimiter
from tests.gateway.helpers import (
    TEST_RAW_CREDENTIAL,
    build_test_runtime,
    image_uri,
)


@pytest.mark.asyncio
async def test_ordinary_responses_request_automatically_uses_shared_core_gate(
    tmp_path: Path,
) -> None:
    runtime, downstream, asset_store = build_test_runtime(tmp_path)
    app = build_gateway_app(
        runtime=runtime,
        asset_store=asset_store,
        rate_limiter=CredentialRouteRateLimiter(
            capacity=10,
            refill_per_second=10,
            max_keys=100,
            idle_ttl_seconds=60,
        ),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/responses",
            headers={"Authorization": f"Bearer {TEST_RAW_CREDENTIAL}"},
            json={
                "model": "text-model",
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Diagnose"},
                            {"type": "input_image", "image_url": image_uri()},
                        ],
                    }
                ],
            },
        )

    assert response.status_code == 200
    assert len(downstream.requests) == 1
    serialized = json.dumps(downstream.requests[0].payload)
    assert "ERROR 104" in serialized
    assert "red terminal" in serialized
    assert "input_image" not in serialized
    assert "data:image" not in serialized
    assert runtime.current().service is not None


@pytest.mark.asyncio
async def test_auth_failure_is_rejected_before_core_and_downstream(tmp_path: Path) -> None:
    runtime, downstream, asset_store = build_test_runtime(tmp_path)
    app = build_gateway_app(
        runtime=runtime,
        asset_store=asset_store,
        rate_limiter=CredentialRouteRateLimiter(
            capacity=10,
            refill_per_second=10,
            max_keys=100,
            idle_ttl_seconds=60,
        ),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/responses",
            headers={
                "Authorization": f"Bearer {TEST_RAW_CREDENTIAL}tampered",
                "Cookie": "media_bridge_admin=not-data-plane-auth",
            },
            json={"model": "text-model", "input": "must not run"},
        )

    assert response.status_code in {401, 403}
    assert downstream.requests == []
