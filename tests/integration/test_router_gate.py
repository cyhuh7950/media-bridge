from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from pypdf import PdfWriter

from media_bridge.acquisition import MediaAcquirer
from media_bridge.assets import AssetStore
from media_bridge.backends import (
    BackendStatus,
    OcrResult,
    VisionResult,
)
from media_bridge.capabilities import CapabilityRegistry, ModelCapability
from media_bridge.contracts import MediaPart, PrepareForModelRequest, TargetModel, TextPart
from media_bridge.gate import (
    DownstreamPayload,
    PreRequestGate,
    digest_content,
)
from media_bridge.receipts import GateReceiptSigner, ReceiptBinding
from media_bridge.router import (
    DownstreamRequest,
    GuardedDownstream,
    GuardRejectedError,
    RouterAdapter,
)
from media_bridge.sanitizer import SanitizationError
from media_bridge.workspace import TemporaryMediaWorkspace


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (2, 2), color="blue").save(output, format="PNG")
    return output.getvalue()


def _media_part(data: bytes | None = None) -> MediaPart:
    return MediaPart.model_validate(
        {
            "type": "media",
            "media_type": "image",
            "source": {
                "kind": "base64",
                "data": base64.b64encode(data or _png()).decode("ascii"),
            },
            "filename": "original-secret.png",
            "declared_mime": "image/png",
        }
    )


def _pdf_part() -> MediaPart:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(output)
    return MediaPart.model_validate(
        {
            "type": "media",
            "media_type": "pdf",
            "source": {
                "kind": "base64",
                "data": base64.b64encode(output.getvalue()).decode("ascii"),
            },
            "declared_mime": "application/pdf",
        }
    )


class FakeOcr:
    def __init__(self, result: OcrResult | None = None) -> None:
        self.result = result or OcrResult(BackendStatus.SUCCESS, text="ERROR 104: timeout")
        self.calls = 0

    async def extract(self, **_kwargs: Any) -> OcrResult:
        self.calls += 1
        return self.result


class FakeVision:
    def __init__(self, result: VisionResult | None = None) -> None:
        self.result = result or VisionResult(
            BackendStatus.SUCCESS,
            description="Terminal screenshot with a red stack trace",
        )
        self.calls = 0

    async def describe(self, **_kwargs: Any) -> VisionResult:
        self.calls += 1
        return self.result


class SpyDownstream:
    def __init__(self) -> None:
        self.calls: list[DownstreamRequest] = []

    async def invoke(self, request: DownstreamRequest) -> dict[str, str]:
        self.calls.append(request)
        return {"status": "called"}


def _registry(now: datetime) -> CapabilityRegistry:
    future = now + timedelta(hours=1)
    return CapabilityRegistry(
        [
            ModelCapability("text-model", {"text"}, future),
            ModelCapability("vision-model", {"text", "image", "pdf"}, future),
            ModelCapability("image-only-model", {"text", "image"}, future),
            ModelCapability("stale-model", {"text"}, now - timedelta(seconds=1)),
        ],
        version="test-v1",
    )


def _gate(
    tmp_path: Path,
    *,
    now: datetime,
    ocr: FakeOcr | None = None,
    vision: FakeVision | None = None,
    sanitizer: Any = None,
    workspace_factory: Any = None,
) -> tuple[PreRequestGate, GateReceiptSigner]:
    signer = GateReceiptSigner(secret=b"g" * 32, clock=lambda: now.timestamp())
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
    return gate, signer


@pytest.mark.asyncio
async def test_image_nonvision_delivers_only_converted_text(tmp_path: Path) -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)
    gate, signer = _gate(tmp_path, now=now)
    spy = SpyDownstream()
    router = RouterAdapter(gate=gate, downstream=GuardedDownstream(spy, signer))
    request = PrepareForModelRequest(
        content=[TextPart(text="Diagnose this"), _media_part()],
        target=TargetModel(registry_id="text-model"),
        conversion_profile="error_screenshot",
    )

    invocation = await router.invoke(request, tenant_id="tenant-a")

    assert invocation.gate_result.action == "converted"
    assert invocation.gate_result.original_image_removed is True
    assert invocation.gate_result.target_supports_vision is False
    assert len(spy.calls) == 1
    assert spy.calls[0].media_count == 0
    serialized = repr(spy.calls[0].content)
    assert "ERROR 104" in serialized
    assert "red stack trace" in serialized
    assert "original-secret.png" not in serialized
    assert "base64" not in serialized


@pytest.mark.asyncio
async def test_pdf_nonvision_delivers_only_converted_text(tmp_path: Path) -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)
    gate, signer = _gate(tmp_path, now=now)
    spy = SpyDownstream()
    router = RouterAdapter(gate=gate, downstream=GuardedDownstream(spy, signer))

    invocation = await router.invoke(
        PrepareForModelRequest(
            content=[TextPart(text="Summarize this PDF"), _pdf_part()],
            target=TargetModel(registry_id="text-model"),
            conversion_profile="document",
        ),
        tenant_id="tenant-a",
    )

    assert invocation.gate_result.action == "converted"
    assert invocation.gate_result.contains_pdf is True
    assert len(spy.calls) == 1
    assert spy.calls[0].media_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["ocr", "vision", "sanitizer", "cleanup"])
async def test_every_conversion_boundary_failure_makes_zero_downstream_calls(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)
    ocr = FakeOcr(
        OcrResult(BackendStatus.FAILURE, error_code="timeout")
        if failure_stage == "ocr"
        else None
    )
    vision = FakeVision(
        VisionResult(BackendStatus.FAILURE, error_code="timeout")
        if failure_stage == "vision"
        else None
    )

    def rejected_sanitizer(_text: str, **_kwargs: Any) -> str:
        raise SanitizationError("unsafe")

    def failed_workspace() -> TemporaryMediaWorkspace:
        return TemporaryMediaWorkspace(parent=tmp_path, remove_tree=lambda _path: None)

    gate, signer = _gate(
        tmp_path,
        now=now,
        ocr=ocr,
        vision=vision,
        sanitizer=rejected_sanitizer if failure_stage == "sanitizer" else None,
        workspace_factory=failed_workspace if failure_stage == "cleanup" else None,
    )
    spy = SpyDownstream()
    router = RouterAdapter(gate=gate, downstream=GuardedDownstream(spy, signer))
    request = PrepareForModelRequest(
        content=[_media_part()],
        target=TargetModel(registry_id="text-model"),
    )

    invocation = await router.invoke(request, tenant_id="tenant-a")

    assert invocation.gate_result.action == "blocked"
    assert invocation.gate_result.error is not None
    assert len(spy.calls) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", ["unknown-model", "stale-model"])
async def test_unknown_and_stale_capability_block_before_downstream(
    tmp_path: Path,
    model_id: str,
) -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)
    gate, signer = _gate(tmp_path, now=now)
    spy = SpyDownstream()
    router = RouterAdapter(gate=gate, downstream=GuardedDownstream(spy, signer))
    request = PrepareForModelRequest(
        content=[TextPart(text="plain request")],
        target=TargetModel(registry_id=model_id),
    )

    invocation = await router.invoke(request, tenant_id="tenant-a")

    assert invocation.gate_result.action == "blocked"
    assert invocation.gate_result.target_supports_vision is None
    assert len(spy.calls) == 0


@pytest.mark.asyncio
async def test_ordinary_router_request_automatically_runs_gate(tmp_path: Path) -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)
    gate, signer = _gate(tmp_path, now=now)
    prepare_calls = 0
    original_prepare = gate.prepare_for_model

    async def counted_prepare(*args: Any, **kwargs: Any) -> Any:
        nonlocal prepare_calls
        prepare_calls += 1
        return await original_prepare(*args, **kwargs)

    gate.prepare_for_model = counted_prepare  # type: ignore[method-assign]
    spy = SpyDownstream()
    router = RouterAdapter(gate=gate, downstream=GuardedDownstream(spy, signer))

    invocation = await router.invoke(
        PrepareForModelRequest(
            content=[TextPart(text="normal user request")],
            target=TargetModel(registry_id="text-model"),
        ),
        tenant_id="tenant-a",
    )

    assert prepare_calls == 1
    assert invocation.gate_result.action == "passthrough"
    assert len(spy.calls) == 1


@pytest.mark.asyncio
async def test_followup_and_subagent_handoff_are_fresh_text_only_inputs(tmp_path: Path) -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)
    store = AssetStore(tmp_path / "assets")
    asset_id = store.put(
        tenant_id="tenant-a",
        data=_png(),
        filename="private-shot.png",
        declared_mime="image/png",
    )
    signer = GateReceiptSigner(secret=b"g" * 32, clock=lambda: now.timestamp())
    gate = PreRequestGate(
        registry=_registry(now),
        acquirer=MediaAcquirer(asset_store=store),
        ocr_backend=FakeOcr(),
        vision_backend=FakeVision(),
        receipt_signer=signer,
        now=lambda: now,
    )
    spy = SpyDownstream()
    router = RouterAdapter(gate=gate, downstream=GuardedDownstream(spy, signer))
    first = await router.invoke(
        PrepareForModelRequest.model_validate(
            {
                "content": [
                    {"type": "text", "text": "First request"},
                    {
                        "type": "media",
                        "media_type": "image",
                        "source": {"kind": "asset_id", "asset_id": asset_id},
                    },
                ],
                "target": {"registry_id": "text-model"},
            }
        ),
        tenant_id="tenant-a",
    )
    assert first.safe_state is not None

    followup_request = router.build_followup_request(
        state=first.safe_state,
        user_text="What should I try next?",
        target=TargetModel(registry_id="text-model"),
    )
    handoff = router.build_subagent_handoff(
        state=first.safe_state,
        user_text="Investigate the converted context",
        target=TargetModel(registry_id="text-model"),
    )

    for candidate in (followup_request, handoff):
        dumped = candidate.model_dump_json()
        assert asset_id not in dumped
        assert "private-shot.png" not in dumped
        assert '"type":"media"' not in dumped
        assert "assistant" not in dumped
        assert "reasoning" not in dumped
        assert "tool_result" not in dumped


@pytest.mark.asyncio
async def test_vision_passthrough_requires_exact_active_modality_support(tmp_path: Path) -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)
    gate, signer = _gate(tmp_path, now=now)
    spy = SpyDownstream()
    router = RouterAdapter(gate=gate, downstream=GuardedDownstream(spy, signer))
    vision_request = PrepareForModelRequest(
        content=[TextPart(text="Describe"), _media_part()],
        target=TargetModel(registry_id="vision-model"),
    )

    passed = await router.invoke(vision_request, tenant_id="tenant-a")

    assert passed.gate_result.action == "passthrough"
    assert passed.gate_result.original_image_removed is False
    assert len(spy.calls) == 1
    assert spy.calls[0].media_count == 1

    pdf_for_image_only = PrepareForModelRequest.model_validate(
        {
            "content": [
                {
                    "type": "media",
                    "media_type": "pdf",
                    "source": {"kind": "base64", "data": "JVBERi0xLjQ="},
                }
            ],
            "target": {"registry_id": "image-only-model"},
        }
    )
    blocked = await router.invoke(pdf_for_image_only, tenant_id="tenant-a")
    assert blocked.gate_result.action == "blocked"
    assert len(spy.calls) == 1


@pytest.mark.asyncio
async def test_vision_passthrough_still_validates_media_source(tmp_path: Path) -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)
    gate, signer = _gate(tmp_path, now=now)
    spy = SpyDownstream()
    router = RouterAdapter(gate=gate, downstream=GuardedDownstream(spy, signer))
    invalid_media = MediaPart(
        media_type="image",
        source={"kind": "base64", "data": "not-valid-base64"},
    )

    invocation = await router.invoke(
        PrepareForModelRequest(
            content=[invalid_media],
            target=TargetModel(registry_id="vision-model"),
        ),
        tenant_id="tenant-a",
    )

    assert invocation.gate_result.action == "blocked"
    assert len(spy.calls) == 0


@pytest.mark.asyncio
async def test_unexpected_sanitizer_crash_is_blocked(tmp_path: Path) -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)

    def crashed_sanitizer(_text: str, **_kwargs: Any) -> str:
        raise RuntimeError("sensitive internal detail")

    gate, signer = _gate(tmp_path, now=now, sanitizer=crashed_sanitizer)
    spy = SpyDownstream()
    router = RouterAdapter(gate=gate, downstream=GuardedDownstream(spy, signer))

    invocation = await router.invoke(
        PrepareForModelRequest(
            content=[_media_part()],
            target=TargetModel(registry_id="text-model"),
        ),
        tenant_id="tenant-a",
    )

    assert invocation.gate_result.action == "blocked"
    assert invocation.gate_result.error is not None
    assert "sensitive" not in invocation.gate_result.error.message
    assert len(spy.calls) == 0


@pytest.mark.asyncio
async def test_guard_blocks_forged_nonvision_media_even_with_valid_signature() -> None:
    signer = GateReceiptSigner(secret=b"g" * 32, clock=lambda: 10_000)
    spy = SpyDownstream()
    guarded = GuardedDownstream(spy, signer)
    content = (TextPart(text="unsafe"), _media_part())
    binding = ReceiptBinding(
        target_id="text-model",
        capability="non_vision",
        input_digest="forged-input",
        output_digest=digest_content(content),
        action="converted",
    )
    payload = DownstreamPayload(
        target_id=binding.target_id,
        capability=binding.capability,
        action=binding.action,
        content=content,
        input_digest=binding.input_digest,
        output_digest=binding.output_digest,
        receipt=signer.sign(binding),
    )

    with pytest.raises(GuardRejectedError, match="media"):
        await guarded.invoke(payload)
    assert len(spy.calls) == 0


@pytest.mark.asyncio
async def test_guard_rejects_signed_but_unknown_action() -> None:
    signer = GateReceiptSigner(secret=b"g" * 32, clock=lambda: 10_000)
    spy = SpyDownstream()
    guarded = GuardedDownstream(spy, signer)
    content = (TextPart(text="safe text"),)
    binding = ReceiptBinding(
        target_id="text-model",
        capability="non_vision",
        input_digest="input",
        output_digest=digest_content(content),
        action="unreviewed-action",
    )
    payload = DownstreamPayload(
        target_id=binding.target_id,
        capability=binding.capability,
        action=binding.action,
        content=content,
        input_digest=binding.input_digest,
        output_digest=binding.output_digest,
        receipt=signer.sign(binding),
    )

    with pytest.raises(GuardRejectedError, match="action"):
        await guarded.invoke(payload)
    assert len(spy.calls) == 0
