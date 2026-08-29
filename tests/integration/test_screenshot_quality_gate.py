from datetime import UTC, datetime
from pathlib import Path

import pytest

from media_bridge.backends import BackendStatus, OcrResult
from media_bridge.contracts import PrepareForModelRequest, TargetModel
from media_bridge.router import RouterAdapter
from tests.integration.test_router_gate import (
    FakeOcr,
    GuardedDownstream,
    SpyDownstream,
    _gate,
    _media_part,
)


@pytest.mark.asyncio
async def test_empty_screenshot_ocr_blocks_before_downstream(tmp_path: Path) -> None:
    gate, signer = _gate(
        tmp_path,
        now=datetime(2026, 8, 23, tzinfo=UTC),
        ocr=FakeOcr(OcrResult(BackendStatus.NO_TEXT)),
    )
    spy = SpyDownstream()
    router = RouterAdapter(gate=gate, downstream=GuardedDownstream(spy, signer))

    invocation = await router.invoke(
        PrepareForModelRequest(
            content=[_media_part()],
            target=TargetModel(registry_id="text-model"),
            conversion_profile="error_screenshot",
        ),
        tenant_id="tenant-a",
    )

    assert invocation.gate_result.action == "blocked"
