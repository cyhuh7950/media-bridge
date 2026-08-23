from __future__ import annotations

import base64

import pytest

from media_bridge.contracts import Base64Source, MediaPart, TextPart, UrlSource
from media_bridge.openai_responses import (
    ResponsesNormalizationError,
    normalize_responses_request,
)
from media_bridge.responses_state import ResponsesStateRecord


def _data_uri(mime_type: str, data: bytes) -> str:
    return f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"


def _state(*, tainted: bool = False) -> ResponsesStateRecord:
    return ResponsesStateRecord(
        response_id="resp_previous",
        tenant_id="tenant-a",
        sanitized_text="safe converted context",
        media_tainted=tainted,
        media_modalities=frozenset({"image"}) if tainted else frozenset(),
        expires_at=10_000,
    )


def test_normalize_string_input_to_exact_model_request() -> None:
    normalized = normalize_responses_request(
        {"model": "provider/text-model", "input": "Explain this"},
        state=None,
    )

    assert normalized.request.target.registry_id == "provider/text-model"
    assert normalized.request.content == [TextPart(text="Explain this")]
    assert normalized.current_user_text == "Explain this"
    assert normalized.input_had_media is False
    assert normalized.previous_state is None


def test_normalize_current_user_image_pdf_and_https_sources() -> None:
    normalized = normalize_responses_request(
        {
            "model": "verified/vision-model",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Inspect these"},
                        {
                            "type": "input_image",
                            "image_url": _data_uri("image/png", b"png"),
                        },
                        {
                            "type": "input_image",
                            "image_url": "https://media.example/screenshot.webp",
                        },
                        {
                            "type": "input_file",
                            "file_data": _data_uri("application/pdf", b"%PDF-1.7"),
                            "filename": "report.pdf",
                        },
                    ],
                }
            ],
        },
        state=None,
    )

    assert normalized.input_had_media is True
    assert normalized.request.conversion_profile == "document"
    assert normalized.request.content[0] == TextPart(text="Inspect these")
    image_data = normalized.request.content[1]
    image_url = normalized.request.content[2]
    pdf = normalized.request.content[3]
    assert isinstance(image_data, MediaPart)
    assert isinstance(image_data.source, Base64Source)
    assert image_data.declared_mime == "image/png"
    assert isinstance(image_url, MediaPart)
    assert isinstance(image_url.source, UrlSource)
    assert isinstance(pdf, MediaPart)
    assert pdf.media_type == "pdf"
    assert pdf.filename == "report.pdf"


@pytest.mark.parametrize(
    ("part", "code"),
    [
        ({"type": "input_image", "file_id": "file_secret"}, "unsupported_media_locator"),
        (
            {"type": "input_image", "image_url": "http://internal/image.png"},
            "unsupported_media_locator",
        ),
        ({"type": "input_file", "file_id": "file_secret"}, "unsupported_media_locator"),
        (
            {"type": "input_file", "file_data": _data_uri("image/png", b"png")},
            "unsupported_media_locator",
        ),
    ],
)
def test_normalize_rejects_provider_ids_and_unsupported_media_locators(
    part: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(ResponsesNormalizationError) as raised:
        normalize_responses_request(
            {"model": "text-model", "input": [{"role": "user", "content": [part]}]},
            state=None,
        )

    assert raised.value.code == code


@pytest.mark.parametrize("history_role", ["user", "assistant", "tool"])
def test_normalize_rejects_media_in_any_non_current_history(history_role: str) -> None:
    history = {
        "role": history_role,
        "content": [
            {
                "type": "input_image",
                "image_url": _data_uri("image/png", b"history"),
            }
        ],
    }
    payload = {
        "model": "text-model",
        "input": [history, {"role": "user", "content": "Current question"}],
    }

    with pytest.raises(ResponsesNormalizationError) as raised:
        normalize_responses_request(payload, state=None)

    assert raised.value.code == "unsafe_history_media"


def test_normalize_rebuilds_safe_followup_without_history_items() -> None:
    normalized = normalize_responses_request(
        {
            "model": "text-model",
            "previous_response_id": "resp_previous",
            "input": [
                {"role": "assistant", "content": [{"type": "output_text", "text": "drop"}]},
                {"role": "user", "content": [{"type": "input_text", "text": "Next?"}]},
            ],
        },
        state=_state(),
    )

    assert normalized.previous_state == _state()
    assert normalized.request.content == [
        TextPart(text="safe converted context"),
        TextPart(text="Next?"),
    ]
    assert "drop" not in normalized.request.model_dump_json()
    assert "resp_previous" not in normalized.request.model_dump_json()


def test_normalize_surfaces_tainted_state_for_capability_policy() -> None:
    normalized = normalize_responses_request(
        {
            "model": "vision-model",
            "previous_response_id": "resp_previous",
            "input": "Continue",
        },
        state=_state(tainted=True),
    )

    assert normalized.previous_state is not None
    assert normalized.previous_state.media_tainted is True
    assert normalized.previous_state.media_modalities == frozenset({"image"})
    assert normalized.request.content == [
        TextPart(text="safe converted context"),
        TextPart(text="Continue"),
    ]


def test_normalize_blocks_conversation_missing_state_and_hidden_top_level_media() -> None:
    cases = [
        (
            {"model": "text-model", "conversation": "conv_1", "input": "hello"},
            None,
            "conversation_unsupported",
        ),
        (
            {"model": "text-model", "previous_response_id": "resp_missing", "input": "hello"},
            None,
            "state_unavailable",
        ),
        (
            {
                "model": "text-model",
                "input": "hello",
                "metadata": {"hidden": _data_uri("image/png", b"hidden")},
            },
            None,
            "unsafe_media_reference",
        ),
    ]

    for payload, state, code in cases:
        with pytest.raises(ResponsesNormalizationError) as raised:
            normalize_responses_request(payload, state=state)
        assert raised.value.code == code


def test_normalize_rejects_mismatched_state_and_malformed_current_input() -> None:
    cases: list[tuple[object, ResponsesStateRecord | None, str]] = [
        ({"model": "text-model", "input": []}, None, "current_user_required"),
        ({"model": "Text Model", "input": "hello"}, None, "invalid_request"),
        (
            {
                "model": "text-model",
                "previous_response_id": "resp_other",
                "input": "hello",
            },
            _state(),
            "state_unavailable",
        ),
    ]

    for payload, state, code in cases:
        with pytest.raises(ResponsesNormalizationError) as raised:
            normalize_responses_request(payload, state=state)
        assert raised.value.code == code
