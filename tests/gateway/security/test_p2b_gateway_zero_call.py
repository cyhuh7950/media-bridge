from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx
import pytest

from media_bridge.workspace import TemporaryMediaWorkspace
from media_bridge_gateway.app import build_gateway_app
from media_bridge_gateway.rate_limit import CredentialRouteRateLimiter
from tests.gateway.helpers import (
    TEST_RAW_CREDENTIAL,
    FakeOcr,
    FakeVision,
    build_test_runtime,
    png_bytes,
)


def _media_request(model_id: str) -> dict[str, object]:
    return {
        "content": [
            {
                "type": "media",
                "media_type": "image",
                "source": {
                    "kind": "base64",
                    "data": base64.b64encode(png_bytes()).decode(),
                },
                "filename": "error.png",
                "declared_mime": "image/png",
            }
        ],
        "target": {"registry_id": model_id},
        "conversion_profile": "error_screenshot",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", ["unknown-model", "stale-model"])
async def test_prepare_unknown_or_stale_capability_is_blocked_without_downstream(
    tmp_path: Path,
    model_id: str,
) -> None:
    runtime, downstream, asset_store = build_test_runtime(tmp_path)
    app = build_gateway_app(
        runtime=runtime,
        asset_store=asset_store,
        rate_limiter=CredentialRouteRateLimiter(
            capacity=10,
            refill_per_second=10,
            max_keys=10,
            idle_ttl_seconds=60,
        ),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://gateway.test",
    ) as client:
        response = await client.post(
            "/v1/prepare",
            headers={"Authorization": f"Bearer {TEST_RAW_CREDENTIAL}"},
            json=_media_request(model_id),
        )

    assert response.status_code == 200
    assert response.json()["action"] == "blocked"
    assert response.json()["sanitized_text"] is None
    assert downstream.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["ocr", "vision", "sanitizer", "cleanup"])
async def test_prepare_conversion_failure_is_blocked_without_downstream(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    def rejected_sanitizer(_text: str, **_kwargs: Any) -> str:
        raise RuntimeError("unsafe converted text")

    def failed_workspace() -> TemporaryMediaWorkspace:
        return TemporaryMediaWorkspace(parent=tmp_path, remove_tree=lambda _path: None)

    runtime, downstream, asset_store = build_test_runtime(
        tmp_path,
        ocr=FakeOcr(fail=failure_stage == "ocr"),
        vision=FakeVision(fail=failure_stage == "vision"),
        sanitizer=rejected_sanitizer if failure_stage == "sanitizer" else None,
        workspace_factory=failed_workspace if failure_stage == "cleanup" else None,
    )
    app = build_gateway_app(
        runtime=runtime,
        asset_store=asset_store,
        rate_limiter=CredentialRouteRateLimiter(
            capacity=10,
            refill_per_second=10,
            max_keys=10,
            idle_ttl_seconds=60,
        ),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://gateway.test",
    ) as client:
        response = await client.post(
            "/v1/prepare",
            headers={"Authorization": f"Bearer {TEST_RAW_CREDENTIAL}"},
            json=_media_request("text-model"),
        )

    assert response.status_code == 200
    assert response.json()["action"] == "blocked"
    assert response.json()["sanitized_text"] is None
    assert downstream.requests == []
