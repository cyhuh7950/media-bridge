from pathlib import Path

import httpx
import pytest

from media_bridge_control.gateway_client import HttpGatewayClient
from media_bridge_gateway.app import build_gateway_app
from media_bridge_gateway.rate_limit import CredentialRouteRateLimiter
from tests.gateway.helpers import TEST_RAW_CREDENTIAL, build_test_runtime, png_bytes


@pytest.mark.asyncio
async def test_control_bff_waits_longer_for_responses_than_other_gateway_calls() -> None:
    observed: list[tuple[str, float]] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        observed.append((request.url.path, request.extensions["timeout"]["read"]))
        if request.url.path == "/status":
            return httpx.Response(200, json={"status": "ready", "snapshot_version": 1})
        return httpx.Response(200, json={"id": "resp_test"})

    client = HttpGatewayClient(transport=httpx.MockTransport(handle))
    base_url = "https://gateway.test"
    await client.status(base_url=base_url, credential=TEST_RAW_CREDENTIAL)
    await client.responses(
        base_url=base_url,
        credential=TEST_RAW_CREDENTIAL,
        payload={"model": "auto", "input": "test", "stream": False},
    )

    assert observed == [("/status", 15.0), ("/v1/responses", 45.0)]


@pytest.mark.asyncio
async def test_control_bff_client_uses_actual_gateway_prepare_and_opt_in_responses(
    tmp_path: Path,
) -> None:
    runtime, downstream, asset_store = build_test_runtime(tmp_path)
    app = build_gateway_app(
        runtime=runtime,
        asset_store=asset_store,
        rate_limiter=CredentialRouteRateLimiter(
            capacity=20,
            refill_per_second=20,
            max_keys=20,
            idle_ttl_seconds=60,
        ),
    )
    client = HttpGatewayClient(transport=httpx.ASGITransport(app=app))
    base_url = "https://gateway.test"

    status = await client.status(base_url=base_url, credential=TEST_RAW_CREDENTIAL)
    preview_asset = await client.upload(
        base_url=base_url,
        credential=TEST_RAW_CREDENTIAL,
        data=png_bytes(),
        filename="error.png",
        declared_mime="image/png",
    )
    preview = await client.prepare(
        base_url=base_url,
        credential=TEST_RAW_CREDENTIAL,
        payload={
            "content": [
                {"type": "text", "text": "explain"},
                {
                    "type": "media",
                    "media_type": "image",
                    "source": {"kind": "asset_id", "asset_id": preview_asset},
                    "filename": "error.png",
                    "declared_mime": "image/png",
                },
            ],
            "target": {"registry_id": "text-model"},
            "conversion_profile": "error_screenshot",
        },
    )
    await client.delete(
        base_url=base_url,
        credential=TEST_RAW_CREDENTIAL,
        asset_id=preview_asset,
    )

    run_asset = await client.upload(
        base_url=base_url,
        credential=TEST_RAW_CREDENTIAL,
        data=png_bytes(),
        filename="error.png",
        declared_mime="image/png",
    )
    response = await client.responses(
        base_url=base_url,
        credential=TEST_RAW_CREDENTIAL,
        payload={
            "model": "text-model",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "explain"},
                        {"type": "input_image", "asset_id": run_asset},
                    ],
                }
            ],
            "stream": False,
        },
    )
    await client.delete(
        base_url=base_url,
        credential=TEST_RAW_CREDENTIAL,
        asset_id=run_asset,
    )

    assert status == {"status": "ready", "snapshot_version": 1}
    assert preview["action"] == "converted"
    assert preview["original_image_removed"] is True
    assert response["id"] == "resp_gateway"
    assert len(downstream.requests) == 1
    assert downstream.requests[0].payload["input"]
