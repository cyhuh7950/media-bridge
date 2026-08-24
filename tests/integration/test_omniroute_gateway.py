from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image

from media_bridge.acquisition import MediaAcquirer
from media_bridge.assets import AssetStore
from media_bridge.backends import BackendStatus, OcrResult, VisionResult
from media_bridge.capabilities import CapabilityRegistry, ModelCapability
from media_bridge.gate import PreRequestGate
from media_bridge.omniroute_adapter import GuardedOmniRouteAdapter
from media_bridge.receipts import GateReceiptSigner
from media_bridge.responses_gateway import ResponsesIngressGateway
from media_bridge.responses_state import ResponsesStateStore
from media_bridge.workspace import TemporaryMediaWorkspace


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (2, 2), color="blue").save(output, format="PNG")
    return output.getvalue()


def _image_uri() -> str:
    return f"data:image/png;base64,{base64.b64encode(_png()).decode('ascii')}"


class FakeOcr:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def extract(self, **_kwargs: Any) -> OcrResult:
        self.calls += 1
        if self.fail:
            return OcrResult(BackendStatus.FAILURE, error_code="timeout")
        return OcrResult(BackendStatus.SUCCESS, text="ERROR 104")


class FakeVision:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def describe(self, **_kwargs: Any) -> VisionResult:
        self.calls += 1
        if self.fail:
            return VisionResult(BackendStatus.FAILURE, error_code="timeout")
        return VisionResult(BackendStatus.SUCCESS, description="A red terminal error")


def _registry(now: datetime) -> CapabilityRegistry:
    future = now + timedelta(hours=1)
    return CapabilityRegistry(
        [
            ModelCapability("text-model", {"text"}, future),
            ModelCapability(
                "vision-model",
                {"text", "image", "pdf"},
                future,
                pdf_passthrough_verified=True,
            ),
            ModelCapability("unverified-pdf-model", {"text", "pdf"}, future),
            ModelCapability("stale-model", {"text"}, now - timedelta(seconds=1)),
        ],
        version="gateway-test",
    )


def _gateway(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    handler: httpx.MockTransport,
    *,
    ocr: FakeOcr | None = None,
    vision: FakeVision | None = None,
    sanitizer: Any = None,
    workspace_factory: Any = None,
) -> tuple[ResponsesIngressGateway, GuardedOmniRouteAdapter, ResponsesStateStore]:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    signer = GateReceiptSigner(secret=b"r" * 32, clock=lambda: now.timestamp())
    gate = PreRequestGate(
        registry=_registry(now),
        acquirer=MediaAcquirer(asset_store=AssetStore(tmp_path / "assets")),
        ocr_backend=ocr or FakeOcr(),
        vision_backend=vision or FakeVision(),
        receipt_signer=signer,
        sanitizer=sanitizer,
        workspace_factory=workspace_factory,
        now=lambda: now,
    )
    monkeypatch.setenv("TEST_OMNIROUTE_KEY", "omniroute-secret")
    adapter = GuardedOmniRouteAdapter(
        endpoint="http://127.0.0.1:20128/v1/responses",
        receipt_signer=signer,
        api_key_env="TEST_OMNIROUTE_KEY",
        transport=handler,
    )
    state_store = ResponsesStateStore(clock=lambda: now.timestamp())
    gateway = ResponsesIngressGateway(
        gate=gate,
        adapter=adapter,
        receipt_signer=signer,
        state_store=state_store,
    )
    return gateway, adapter, state_store


@pytest.mark.asyncio
async def test_image_nonvision_reaches_omniroute_as_text_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downstream_payloads: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer omniroute-secret"
        downstream_payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "resp_image", "output": []})

    gateway, adapter, state_store = _gateway(
        tmp_path,
        monkeypatch,
        httpx.MockTransport(handler),
    )
    payload = {
        "model": "text-model",
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Diagnose"},
                    {"type": "input_image", "image_url": _image_uri()},
                ],
            }
        ],
        "tools": [{"type": "function", "name": "lookup", "parameters": {}}],
    }

    result = await gateway.invoke(payload, tenant_id="tenant-a")

    assert result.status == "completed"
    assert result.gate_result is not None
    assert result.gate_result.action == "converted"
    assert len(downstream_payloads) == 1
    serialized = json.dumps(downstream_payloads[0])
    assert "input_image" not in serialized
    assert "data:image" not in serialized
    assert "ERROR 104" in serialized
    assert "red terminal" in serialized
    assert downstream_payloads[0]["tools"] == payload["tools"]
    record = state_store.resolve("resp_image", tenant_id="tenant-a")
    assert record.media_tainted is False
    assert record.media_modalities == frozenset()
    await adapter.close()


@pytest.mark.asyncio
async def test_text_only_request_preserves_safe_responses_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downstream_payloads: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        downstream_payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "resp_text", "output": []})

    gateway, adapter, state_store = _gateway(
        tmp_path,
        monkeypatch,
        httpx.MockTransport(handler),
    )
    payload = {
        "model": "text-model",
        "input": "hello",
        "instructions": "Be concise",
        "temperature": 0.2,
        "tools": [{"type": "function", "name": "lookup", "parameters": {}}],
        "stream": False,
    }

    result = await gateway.invoke(payload, tenant_id="tenant-a")

    assert result.status == "completed"
    assert downstream_payloads == [payload]
    record = state_store.resolve("resp_text", tenant_id="tenant-a")
    assert record.sanitized_text == "hello"
    assert record.media_tainted is False
    await adapter.close()


@pytest.mark.asyncio
async def test_safe_followup_is_rebuilt_without_previous_or_assistant_items(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downstream_payloads: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        downstream_payloads.append(json.loads(request.content))
        response_id = "resp_first" if len(downstream_payloads) == 1 else "resp_second"
        return httpx.Response(200, json={"id": response_id, "output": []})

    gateway, adapter, _state_store = _gateway(
        tmp_path,
        monkeypatch,
        httpx.MockTransport(handler),
    )
    first = await gateway.invoke(
        {"model": "text-model", "input": "safe first"},
        tenant_id="tenant-a",
    )
    assert first.status == "completed"

    second = await gateway.invoke(
        {
            "model": "text-model",
            "previous_response_id": "resp_first",
            "input": [
                {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "must be dropped"}],
                },
                {"role": "user", "content": [{"type": "input_text", "text": "Next?"}]},
            ],
            "tools": [{"type": "function", "name": "safe_tool", "parameters": {}}],
        },
        tenant_id="tenant-a",
    )

    assert second.status == "completed"
    rebuilt = json.dumps(downstream_payloads[1])
    assert "previous_response_id" not in rebuilt
    assert "must be dropped" not in rebuilt
    assert "safe first" in rebuilt
    assert "Next?" in rebuilt
    assert "safe_tool" in rebuilt
    await adapter.close()


@pytest.mark.asyncio
async def test_tainted_followup_blocks_nonvision_but_allows_verified_vision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downstream_calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal downstream_calls
        downstream_calls += 1
        return httpx.Response(200, json={"id": f"resp_{downstream_calls}", "output": []})

    gateway, adapter, state_store = _gateway(
        tmp_path,
        monkeypatch,
        httpx.MockTransport(handler),
    )
    state_store.put(
        response_id="resp_tainted",
        tenant_id="tenant-a",
        sanitized_text="converted image context",
        media_tainted=True,
        media_modalities=frozenset({"image"}),
    )

    blocked = await gateway.invoke(
        {
            "model": "text-model",
            "previous_response_id": "resp_tainted",
            "input": "Continue",
        },
        tenant_id="tenant-a",
    )
    assert blocked.status == "blocked"
    assert blocked.error is not None
    assert blocked.error.code == "tainted_state_nonvision"
    assert downstream_calls == 0

    passed = await gateway.invoke(
        {
            "model": "vision-model",
            "previous_response_id": "resp_tainted",
            "input": "Continue",
        },
        tenant_id="tenant-a",
    )
    assert passed.status == "completed"
    assert downstream_calls == 1
    await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", ["unknown-model", "stale-model"])
async def test_unknown_and_stale_capability_make_zero_omniroute_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    model_id: str,
) -> None:
    downstream_calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal downstream_calls
        downstream_calls += 1
        return httpx.Response(200, json={"id": "resp_forbidden"})

    gateway, adapter, _state_store = _gateway(
        tmp_path,
        monkeypatch,
        httpx.MockTransport(handler),
    )

    result = await gateway.invoke({"model": model_id, "input": "hello"}, tenant_id="tenant-a")

    assert result.status == "blocked"
    assert downstream_calls == 0
    await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["ocr", "vision", "sanitizer", "cleanup"])
async def test_every_conversion_failure_makes_zero_omniroute_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    downstream_calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal downstream_calls
        downstream_calls += 1
        return httpx.Response(200, json={"id": "resp_forbidden"})

    def rejected_sanitizer(_text: str, **_kwargs: Any) -> str:
        raise RuntimeError("unsafe converted text")

    def failed_workspace() -> TemporaryMediaWorkspace:
        return TemporaryMediaWorkspace(parent=tmp_path, remove_tree=lambda _path: None)

    gateway, adapter, _state_store = _gateway(
        tmp_path,
        monkeypatch,
        httpx.MockTransport(handler),
        ocr=FakeOcr(fail=failure_stage == "ocr"),
        vision=FakeVision(fail=failure_stage == "vision"),
        sanitizer=rejected_sanitizer if failure_stage == "sanitizer" else None,
        workspace_factory=failed_workspace if failure_stage == "cleanup" else None,
    )

    result = await gateway.invoke(
        {
            "model": "text-model",
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_image", "image_url": _image_uri()}],
                }
            ],
        },
        tenant_id="tenant-a",
    )

    assert result.status == "blocked"
    assert result.error is not None
    assert result.error.code == {
        "ocr": "ocr_failed",
        "vision": "vision_failed",
        "sanitizer": "sanitization_failed",
        "cleanup": "cleanup_failed",
    }[failure_stage]
    assert downstream_calls == 0
    await adapter.close()
