from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from media_bridge.assets import AssetStore
from media_bridge.capabilities import CapabilityRegistry, ModelCapability
from media_bridge.contracts import SafeError
from media_bridge.http_app import build_http_app
from media_bridge.mcp_server import build_mcp_server
from media_bridge.omniroute_adapter import OmniRouteResponse
from media_bridge.responses_gateway import ResponsesGatewayResult


class UnusedService:
    pass


class FakeGateway:
    def __init__(self, result: ResponsesGatewayResult) -> None:
        self.result = result
        self.calls: list[tuple[object, str]] = []

    async def invoke(self, payload: object, *, tenant_id: str) -> ResponsesGatewayResult:
        self.calls.append((payload, tenant_id))
        return self.result


def _app(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    gateway: FakeGateway | None,
    *,
    max_body: int = 4 * 1024 * 1024,
) -> Any:
    monkeypatch.setenv("MEDIA_BRIDGE_SERVICE_TOKEN", "service-secret")
    server = build_mcp_server(UnusedService(), tenant_provider=lambda: "tenant-a")
    return build_http_app(
        server=server,
        asset_store=AssetStore(tmp_path / "assets"),
        responses_gateway=gateway,
        max_responses_body_bytes=max_body,
    )


def _registry() -> CapabilityRegistry:
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    return CapabilityRegistry(
        [
            ModelCapability(
                model_id="solar-pro4",
                input_modalities={"text"},
                expires_at=now + timedelta(hours=1),
            ),
            ModelCapability(
                model_id="expired-model",
                input_modalities={"text"},
                expires_at=now - timedelta(seconds=1),
            ),
        ],
        version="test",
    )


@pytest.mark.asyncio
async def test_models_route_returns_openai_compatible_active_models(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MEDIA_BRIDGE_SERVICE_TOKEN", "service-secret")
    server = build_mcp_server(UnusedService(), tenant_provider=lambda: "tenant-a")
    app = build_http_app(
        server=server,
        asset_store=AssetStore(tmp_path / "assets"),
        model_registry=_registry(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        unauthorized = await client.get("/v1/models")
        response = await client.get(
            "/v1/models",
            headers={
                "Authorization": "Bearer service-secret",
            },
        )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert body["data"][0]["id"] == "solar-pro4"
    assert body["data"][0]["object"] == "model"
    assert isinstance(body["data"][0]["created"], int)
    assert body["data"][0]["owned_by"] == "media-bridge"
    assert [item["id"] for item in body["data"]] == ["solar-pro4"]


@pytest.mark.asyncio
async def test_responses_route_reuses_bearer_and_tenant_auth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    gateway = FakeGateway(
        ResponsesGatewayResult(
            status="completed",
            response=OmniRouteResponse(b'{"id":"resp_ok"}', "application/json", "resp_ok", 200),
            gate_result=None,
            error=None,
            http_status=200,
        )
    )
    app = _app(monkeypatch, tmp_path, gateway)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        unauthenticated = await client.post("/v1/responses", json={"model": "text", "input": "x"})
        missing_tenant = await client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer service-secret"},
            json={"model": "text", "input": "x"},
        )

    assert unauthenticated.status_code == 401
    assert missing_tenant.status_code == 400
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_responses_route_returns_bounded_upstream_body(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    body = b'{"id":"resp_ok","output":[]}'
    gateway = FakeGateway(
        ResponsesGatewayResult(
            status="completed",
            response=OmniRouteResponse(body, "application/json", "resp_ok", 200),
            gate_result=None,
            error=None,
            http_status=200,
        )
    )
    app = _app(monkeypatch, tmp_path, gateway)
    headers = {
        "Authorization": "Bearer service-secret",
        "X-Media-Bridge-Tenant": "tenant-a",
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/responses",
            headers=headers,
            json={"model": "text-model", "input": "hello"},
        )

    assert response.status_code == 200
    assert response.content == body
    assert response.headers["content-type"].startswith("application/json")
    assert gateway.calls == [({"model": "text-model", "input": "hello"}, "tenant-a")]


@pytest.mark.asyncio
async def test_responses_route_bounds_json_and_returns_safe_error_shape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    gateway = FakeGateway(
        ResponsesGatewayResult(
            status="blocked",
            response=None,
            gate_result=None,
            error=SafeError(code="capability_unknown", message="Target capability is unknown."),
            http_status=400,
        )
    )
    app = _app(monkeypatch, tmp_path, gateway, max_body=64)
    headers = {
        "Authorization": "Bearer service-secret",
        "X-Media-Bridge-Tenant": "tenant-a",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        malformed = await client.post("/v1/responses", headers=headers, content=b"not-json")
        oversized = await client.post("/v1/responses", headers=headers, content=b"{" + b"x" * 65)
        blocked = await client.post(
            "/v1/responses",
            headers=headers,
            content=json.dumps({"model": "unknown", "input": "private body"}),
        )

    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "invalid_json"
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "request_too_large"
    assert blocked.status_code == 400
    assert blocked.json() == {
        "error": {
            "message": "Target capability is unknown.",
            "type": "media_bridge_error",
            "code": "capability_unknown",
        }
    }
    assert "private body" not in blocked.text
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_responses_route_is_absent_when_gateway_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = _app(monkeypatch, tmp_path, None)
    headers = {
        "Authorization": "Bearer service-secret",
        "X-Media-Bridge-Tenant": "tenant-a",
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/v1/responses", headers=headers, json={"input": "hello"})

    assert response.status_code == 404
