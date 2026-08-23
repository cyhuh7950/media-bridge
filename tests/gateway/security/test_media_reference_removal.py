from __future__ import annotations

import json
from pathlib import Path

import pytest

from media_bridge_gateway.contracts import DataPlaneSubject
from tests.gateway.helpers import build_test_runtime, image_uri


@pytest.mark.asyncio
async def test_nonvision_sealed_payload_has_no_media_locator_or_filename(
    tmp_path: Path,
) -> None:
    runtime, downstream, _asset_store = build_test_runtime(tmp_path)
    subject = DataPlaneSubject(
        credential_selector="gateway-client",
        tenant_id="client-gateway-client",
        scopes=frozenset({"responses:invoke"}),
    )

    result = await runtime.invoke(
        {
            "model": "text-model",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Inspect"},
                        {"type": "input_image", "image_url": image_uri()},
                    ],
                }
            ],
        },
        subject=subject,
    )

    assert result.status == "completed"
    sealed = json.dumps(downstream.requests[0].payload).lower()
    for forbidden in (
        "input_image",
        "image_url",
        "file_data",
        "asset_id",
        "data:image",
        "data:application/pdf",
    ):
        assert forbidden not in sealed
