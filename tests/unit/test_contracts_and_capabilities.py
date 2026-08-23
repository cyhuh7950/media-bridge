from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from media_bridge.capabilities import (
    CapabilityRegistry,
    CapabilityState,
    ModelCapability,
)
from media_bridge.contracts import (
    AssetSource,
    Base64Source,
    MediaPart,
    PrepareForModelRequest,
    TargetModel,
    TextPart,
)
from media_bridge.detector import detect_media


def active_capability(model_id: str, modalities: set[str]) -> ModelCapability:
    return ModelCapability(
        model_id=model_id,
        input_modalities=modalities,
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )


def test_detector_does_not_treat_url_or_base64_looking_text_as_media() -> None:
    request = PrepareForModelRequest(
        content=[TextPart(text="see https://example.test/a.png and data:image/png;base64,AAAA")],
        target=TargetModel(registry_id="upstage/solar-pro4"),
    )

    detection = detect_media(request.content)

    assert detection.media_count == 0
    assert detection.contains_image is False
    assert detection.contains_pdf is False


def test_detector_reports_mixed_image_and_pdf_modalities() -> None:
    request = PrepareForModelRequest(
        content=[
            MediaPart(media_type="image", source=Base64Source(data="aGVsbG8=")),
            MediaPart(media_type="pdf", source=AssetSource(asset_id="mb_abcdefghijklmnopqrstuv")),
        ],
        target=TargetModel(registry_id="provider/vision-model"),
    )

    detection = detect_media(request.content)

    assert detection.media_count == 2
    assert detection.modalities == frozenset({"image", "pdf"})
    assert detection.contains_image is True
    assert detection.contains_pdf is True


def test_registry_uses_exact_model_id_without_name_guessing() -> None:
    registry = CapabilityRegistry(
        [active_capability("upstage/solar-pro4", {"text"})],
        version="registry-v1",
    )

    known = registry.resolve("upstage/solar-pro4")
    guessed = registry.resolve("solar-pro4-latest")

    assert known.state is CapabilityState.NON_VISION
    assert guessed.state is CapabilityState.UNKNOWN


def test_registry_marks_expired_entry_stale() -> None:
    expired = ModelCapability(
        model_id="provider/expired-vision",
        input_modalities={"text", "image"},
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    registry = CapabilityRegistry([expired], version="registry-v1")

    resolution = registry.resolve("provider/expired-vision")

    assert resolution.state is CapabilityState.STALE
    assert resolution.capability is expired


def test_registry_requires_support_for_every_detected_media_modality() -> None:
    image_only = active_capability("provider/image-only", {"text", "image"})

    assert image_only.supports_all(frozenset({"image"})) is True
    assert image_only.supports_all(frozenset({"image", "pdf"})) is False


def test_contract_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        PrepareForModelRequest.model_validate(
            {
                "content": [{"type": "text", "text": "hello", "image": "hidden"}],
                "target": {"registry_id": "upstage/solar-pro4"},
            }
        )
