from __future__ import annotations

import json

import httpx
import pytest

from media_bridge_adapters.cli import probe_connection


@pytest.mark.asyncio
async def test_probe_calls_only_documented_endpoint_and_redacts_authorization() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            422,
            json={
                "status": "blocked",
                "provider": "media-bridge-probe",
                "target_model": "media-bridge-probe-text",
                "capability": None,
                "body": None,
                "original_media_removed": False,
                "input_digest": None,
                "output_digest": None,
                "decision_token": None,
                "error": {"code": "policy_denied", "message": "Request blocked."},
            },
            headers={"content-type": "application/json"},
        )

    result = await probe_connection(
        endpoint="https://bridge.example/adapter/v1/pre-upstream",
        credential_env="MEDIA_BRIDGE_ADAPTER_CREDENTIAL",
        environ={"MEDIA_BRIDGE_ADAPTER_CREDENTIAL": "mbc_probe_private_value"},
        transport=httpx.MockTransport(handler),
    )

    assert result.reachable is True
    assert result.http_status == 422
    assert result.error is None
    assert captured["url"] == "https://bridge.example/adapter/v1/pre-upstream"
    assert captured["authorization"] == "Bearer mbc_probe_private_value"
    assert captured["body"] == {
        "body": {"input": "Media Bridge connectivity probe", "model": "media-bridge-probe-text"},
        "contract_version": "media-bridge-pre-upstream/v1",
        "provider": "media-bridge-probe",
        "request_id": "media-bridge-connectivity-probe",
        "target_model": "media-bridge-probe-text",
        "wire_format": "openai-responses",
    }
    assert "mbc_probe_private_value" not in repr(result)


@pytest.mark.asyncio
async def test_probe_fails_safely_on_missing_secret_redirect_and_oversized_response() -> None:
    missing = await probe_connection(
        endpoint="https://bridge.example/adapter/v1/pre-upstream",
        credential_env="MEDIA_BRIDGE_ADAPTER_CREDENTIAL",
        environ={},
    )
    assert missing.reachable is False
    assert missing.error == "credential_unavailable"

    for response in (
        httpx.Response(307, headers={"location": "https://other.example/"}),
        httpx.Response(200, content=b"x" * 1025, headers={"content-type": "application/json"}),
    ):
        result = await probe_connection(
            endpoint="https://bridge.example/adapter/v1/pre-upstream",
            credential_env="MEDIA_BRIDGE_ADAPTER_CREDENTIAL",
            environ={"MEDIA_BRIDGE_ADAPTER_CREDENTIAL": "mbc_probe_private_value"},
            max_response_bytes=1024,
            transport=httpx.MockTransport(lambda _request, value=response: value),
        )
        assert result.reachable is False
        assert "mbc_probe_private_value" not in repr(result)
