from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from media_bridge.workspace import TemporaryMediaWorkspace
from media_bridge_gateway.contracts import DataPlaneSubject
from tests.gateway.helpers import FakeOcr, FakeVision, build_test_runtime, image_uri


def _subject() -> DataPlaneSubject:
    return DataPlaneSubject(
        credential_selector="gateway-client",
        tenant_id="client-gateway-client",
        scopes=frozenset({"responses:invoke"}),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", ["unknown-model", "stale-model"])
async def test_unknown_and_stale_capability_make_zero_downstream_calls(
    tmp_path: Path,
    model_id: str,
) -> None:
    runtime, downstream, _asset_store = build_test_runtime(tmp_path)

    result = await runtime.invoke(
        {"model": model_id, "input": "hello"},
        subject=_subject(),
    )

    assert result.status == "blocked"
    assert downstream.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["ocr", "vision", "sanitizer", "cleanup"])
async def test_conversion_failure_matrix_makes_zero_downstream_calls(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    def rejected_sanitizer(_text: str, **_kwargs: Any) -> str:
        raise RuntimeError("unsafe converted text")

    def failed_workspace() -> TemporaryMediaWorkspace:
        return TemporaryMediaWorkspace(parent=tmp_path, remove_tree=lambda _path: None)

    runtime, downstream, _asset_store = build_test_runtime(
        tmp_path,
        ocr=FakeOcr(fail=failure_stage == "ocr"),
        vision=FakeVision(fail=failure_stage == "vision"),
        sanitizer=rejected_sanitizer if failure_stage == "sanitizer" else None,
        workspace_factory=failed_workspace if failure_stage == "cleanup" else None,
    )

    result = await runtime.invoke(
        {
            "model": "text-model",
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_image", "image_url": image_uri()}],
                }
            ],
        },
        subject=_subject(),
    )

    assert result.status == "blocked"
    assert downstream.requests == []
