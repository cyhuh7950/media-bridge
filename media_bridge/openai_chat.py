"""Small, bounded OpenAI Chat Completions compatibility translation."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any


class ChatNormalizationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


def _error(message: str) -> ChatNormalizationError:
    return ChatNormalizationError("invalid_request", message)


def _text_part(value: object) -> dict[str, str]:
    if not isinstance(value, str):
        raise _error("Chat message content is malformed.")
    return {"type": "input_text", "text": value}


def _user_content(value: object) -> list[dict[str, Any]]:
    if isinstance(value, str):
        return [_text_part(value)]
    if not isinstance(value, list) or not value:
        raise _error("Chat message content is malformed.")
    parts: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict) or not isinstance(raw.get("type"), str):
            raise _error("Chat message content is malformed.")
        item_type = raw["type"]
        if item_type == "text":
            if set(raw) != {"type", "text"}:
                raise _error("Chat text content is malformed.")
            parts.append(_text_part(raw["text"]))
        elif item_type == "image_url":
            locator = raw.get("image_url")
            if isinstance(locator, dict):
                locator = locator.get("url")
            if not isinstance(locator, str) or not locator:
                raise _error("Chat image content is malformed.")
            parts.append({"type": "input_image", "image_url": locator})
        else:
            raise _error("Chat message content type is not supported.")
    return parts


def _message_content(role: str, value: object) -> list[dict[str, Any]]:
    if role == "user":
        return _user_content(value)
    if isinstance(value, str):
        output_type = "output_text" if role == "assistant" else "input_text"
        return [{"type": output_type, "text": value}]
    if value is None and role == "assistant":
        return []
    raise _error("Chat message content is malformed.")


def _tool_items(message: dict[str, Any]) -> list[dict[str, Any]]:
    calls = message.get("tool_calls")
    if calls is None:
        return []
    if not isinstance(calls, list):
        raise _error("Chat tool calls are malformed.")
    items: list[dict[str, Any]] = []
    for call in calls:
        if not isinstance(call, dict):
            raise _error("Chat tool calls are malformed.")
        function = call.get("function")
        if (
            call.get("type") != "function"
            or not isinstance(function, dict)
            or not isinstance(call.get("id"), str)
            or not isinstance(function.get("name"), str)
            or not isinstance(function.get("arguments"), str)
        ):
            raise _error("Chat tool calls are malformed.")
        items.append(
            {
                "type": "function_call",
                "call_id": call["id"],
                "name": function["name"],
                "arguments": function["arguments"],
            }
        )
    return items


def chat_request_to_responses(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _error("Chat request must be a JSON object.")
    model = payload.get("model")
    messages = payload.get("messages")
    if not isinstance(model, str) or not model or not isinstance(messages, list) or not messages:
        raise _error("Chat request requires a model and messages.")

    instructions: list[str] = []
    input_items: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("role"), str):
            raise _error("Chat message is malformed.")
        role = message["role"]
        if role in {"system", "developer"}:
            content = message.get("content")
            if not isinstance(content, str):
                raise _error("System message content is malformed.")
            if content.strip():
                instructions.append(content)
            continue
        if role not in {"user", "assistant", "tool"}:
            raise _error("Chat message role is not supported.")
        if role == "tool":
            call_id = message.get("tool_call_id")
            output = message.get("content")
            if not isinstance(call_id, str) or not isinstance(output, str):
                raise _error("Chat tool message is malformed.")
            input_items.append(
                {"type": "function_call_output", "call_id": call_id, "output": output}
            )
            continue
        item: dict[str, Any] = {
            "role": role,
            "content": _message_content(role, message.get("content")),
        }
        input_items.append(item)
        input_items.extend(_tool_items(message))

    result: dict[str, Any] = {
        key: value
        for key, value in payload.items()
        if key not in {"messages", "max_tokens"}
    }
    result["model"] = model
    result["input"] = input_items
    if instructions:
        result["instructions"] = "\n\n".join(instructions)
    if "max_tokens" in payload and "max_output_tokens" not in payload:
        result["max_output_tokens"] = payload["max_tokens"]
    return result


def _output_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str):
        return direct
    sections: list[str] = []
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    text = part.get("text")
                    if isinstance(text, str):
                        sections.append(text)
    return "".join(sections)


def chat_response_from_responses(body: bytes, *, request_model: str) -> bytes:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Responses response is not valid JSON.") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("id"), str):
        raise ValueError("Responses response is malformed.")
    text = _output_text(payload)
    completion: dict[str, Any] = {
        "id": payload["id"],
        "object": "chat.completion",
        "created": int(time.time()),
        "model": payload.get("model", request_model),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
    }
    if isinstance(payload.get("usage"), dict):
        completion["usage"] = payload["usage"]
    return json.dumps(completion, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


async def chat_stream_from_responses(
    source: AsyncIterator[bytes],
    *,
    response_id: str,
    request_model: str,
) -> AsyncIterator[bytes]:
    emitted_role = False
    buffer = ""
    finished = False

    def chunk(delta: dict[str, Any], finish_reason: str | None = None) -> bytes:
        body = {
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": request_model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        return f"data: {json.dumps(body, ensure_ascii=False, separators=(',', ':'))}\n\n".encode()

    async for raw in source:
        buffer += raw.decode("utf-8", errors="strict")
        while "\n\n" in buffer:
            event, buffer = buffer.split("\n\n", 1)
            data_lines = [
                line[5:].strip()
                for line in event.splitlines()
                if line.startswith("data:")
            ]
            if not data_lines:
                continue
            data = "\n".join(data_lines)
            if data == "[DONE]":
                finished = True
                break
            try:
                event_body = json.loads(data)
            except json.JSONDecodeError:
                continue
            if not isinstance(event_body, dict):
                continue
            event_type = event_body.get("type")
            if event_type == "response.output_text.delta":
                delta = event_body.get("delta")
                if isinstance(delta, str):
                    if not emitted_role:
                        yield chunk({"role": "assistant", "content": ""})
                        emitted_role = True
                    yield chunk({"content": delta})
            elif event_type == "response.completed":
                if not emitted_role:
                    yield chunk({"role": "assistant", "content": ""})
                    emitted_role = True
                yield chunk({}, "stop")
                yield b"data: [DONE]\n\n"
                finished = True
                break
        if finished:
            break
    if not finished:
        if not emitted_role:
            yield chunk({"role": "assistant", "content": ""})
        yield chunk({}, "stop")
        yield b"data: [DONE]\n\n"


__all__ = [
    "ChatNormalizationError",
    "chat_request_to_responses",
    "chat_response_from_responses",
    "chat_stream_from_responses",
]
