"""이미지 OCR 재구성 시 역할·도구 이력 손실을 방지한다."""
from copy import deepcopy

from media_bridge.contracts import TextPart
from media_bridge.gate import DownstreamPayload
from media_bridge.openai_responses import normalize_responses_request
from media_bridge_gateway.transaction import _build_downstream_payload


def test_image_conversion_keeps_surrounding_messages_and_tool_results() -> None:
    payload = {"model": "solar-pro4", "input": [
        {"role": "developer", "content": "Keep identifiers."},
        {"role": "assistant", "content": "Earlier answer."},
        {"role": "user", "content": [
            {"type": "input_text", "text": "Read screenshot"},
            {"type": "input_image", "image_url": "data:image/png;base64,YQ=="}]},
        {"type": "function_call", "call_id": "c1", "name": "read_file", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c1", "output": "unchanged"}]}
    before = deepcopy(payload)
    normalized = normalize_responses_request(payload, None)
    prepared = DownstreamPayload(
        target_id="solar-pro4", capability="non_vision", action="converted",
        content=(TextPart(text="Read screenshot\nOCR extracted characters"),),
        input_digest="a" * 64, output_digest="b" * 64, receipt="fixture",
    )
    rebuilt = _build_downstream_payload(payload, normalized, prepared)
    assert rebuilt["input"][:2] == before["input"][:2]
    assert rebuilt["input"][3:] == before["input"][3:]
    assert rebuilt["input"][2] == {"role": "user", "content": [
        {"type": "input_text", "text": "Read screenshot\nOCR extracted characters"}]}
    assert payload == before
