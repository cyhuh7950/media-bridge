from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest

from media_bridge.openai_chat import (
    ChatNormalizationError,
    chat_request_to_responses,
    chat_response_from_responses,
    chat_stream_from_responses,
)


def test_chat_request_maps_messages_and_preserves_tools() -> None:
    payload = {
        "model": "solar-pro4",
        "messages": [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Hello"},
        ],
        "tools": [{"type": "function", "function": {"name": "lookup"}}],
        "stream": True,
    }

    result = chat_request_to_responses(payload)

    assert result == {
        "model": "solar-pro4",
        "instructions": "Be concise.",
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "Hello"}],
            }
        ],
        "tools": payload["tools"],
        "stream": True,
    }


def test_chat_request_maps_multimodal_user_content() -> None:
    result = chat_request_to_responses(
        {
            "model": "solar-pro4",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What is this?"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "https://example.com/a.png"},
                        },
                    ],
                }
            ],
        }
    )

    assert result["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "What is this?"},
                {"type": "input_image", "image_url": "https://example.com/a.png"},
            ],
        }
    ]


def test_chat_request_rejects_missing_messages() -> None:
    with pytest.raises(ChatNormalizationError) as error:
        chat_request_to_responses({"model": "solar-pro4"})

    assert error.value.code == "invalid_request"


def test_responses_body_maps_to_chat_completion() -> None:
    result = chat_response_from_responses(
        b'{"id":"resp_1","model":"solar-pro4","output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Hello"}]}]}',
        request_model="solar-pro4",
    )

    body = json.loads(result)
    assert body["id"] == "resp_1"
    assert body["object"] == "chat.completion"
    assert body["model"] == "solar-pro4"
    assert isinstance(body["created"], int)
    assert body["choices"] == [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello"},
            "finish_reason": "stop",
        }
    ]


@pytest.mark.asyncio
async def test_responses_stream_maps_text_deltas_to_chat_chunks() -> None:
    async def source() -> AsyncIterator[bytes]:
        yield b'data: {"type":"response.output_text.delta","delta":"Hi"}\n\n'
        yield b'data: {"type":"response.completed"}\n\n'

    output = b"".join(
        [
            chunk
            async for chunk in chat_stream_from_responses(
                source(), response_id="resp_1", request_model="solar-pro4"
            )
        ]
    )

    assert b'"content":"Hi"' in output
    assert b'"finish_reason":"stop"' in output
    assert output.endswith(b"data: [DONE]\n\n")
