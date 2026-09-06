from __future__ import annotations

from importlib import import_module

import pytest
from pydantic import ValidationError


@pytest.mark.parametrize("namespace", ["media_bridge", "media_bridge_local.core"])
def test_core_namespaces_keep_the_same_media_input_contract(namespace: str) -> None:
    contracts = import_module(f"{namespace}.contracts")
    detector = import_module(f"{namespace}.detector")

    request = contracts.PrepareForModelRequest(
        content=[
            contracts.TextPart(text="설명해 주세요"),
            contracts.MediaPart(
                media_type="image",
                source=contracts.Base64Source(data="aGVsbG8="),
                filename="capture.png",
            ),
        ],
        target=contracts.TargetModel(registry_id="upstage/solar-pro4"),
    )

    detection = detector.detect_media(request.content)

    assert detection.media_count == 1
    assert detection.contains_image is True
    assert detection.contains_pdf is False


@pytest.mark.parametrize("namespace", ["media_bridge", "media_bridge_local.core"])
def test_core_namespaces_reject_unknown_contract_fields(namespace: str) -> None:
    contracts = import_module(f"{namespace}.contracts")

    with pytest.raises(ValidationError):
        contracts.PrepareForModelRequest.model_validate(
            {
                "content": [{"type": "text", "text": "hello", "unexpected": True}],
                "target": {"registry_id": "upstage/solar-pro4"},
            }
        )
