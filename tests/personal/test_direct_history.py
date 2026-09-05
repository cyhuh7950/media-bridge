"""이미지 OCR 재구성 시 역할·도구 이력 손실을 방지한다."""
import json
from copy import deepcopy

import httpx
import pytest

from media_bridge.contracts import TextPart
from media_bridge.gate import DownstreamPayload
from media_bridge.openai_responses import normalize_responses_request
from media_bridge_gateway.transaction import _build_downstream_payload
from media_bridge_personal.npm_runtime import build_personal_app, build_personal_runtime
from media_bridge_personal.solar_responses import SolarResponsesDownstream
from tests.personal.test_npm_runtime import FakeOcr, _image_request


@pytest.mark.asyncio
async def test_personal_previous_response_id_is_explicitly_unsupported(tmp_path):
    calls = []

    def provider(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "first"}}]})

    runtime = build_personal_runtime(
        model="solar-pro4", asset_root=tmp_path / "assets", receipt_secret=b"r" * 32,
        ocr_backend=FakeOcr(), downstream_factory=lambda signer: SolarResponsesDownstream(
            endpoint="https://synthetic.example.test/v1/chat/completions", model="solar-pro4",
            receipt_signer=signer, credential_loader=lambda: "synthetic",
            transport=httpx.MockTransport(provider)),
    )
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build_personal_app(runtime)),
                                     base_url="http://127.0.0.1") as client:
            first = await client.post("/v1/responses", json={"model": "solar-pro4", "input": "hi"})
            result = await client.post("/v1/responses", json={
                "model": "solar-pro4", "input": "next",
                "previous_response_id": first.json()["id"]})
        assert result.status_code == 400
        assert result.json()["error"]["code"] == "previous_response_id_unsupported"
        assert len(calls) == 1
    finally:
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("ocr_failure", [False, True])
@pytest.mark.parametrize("history", [False, True])
async def test_personal_followup_ocr_history_preserves_roles_and_blocks_failures(
    tmp_path, ocr_failure, history,
):
    sent = []

    def provider(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "followup"}}]})

    runtime = build_personal_runtime(
        model="solar-pro4", asset_root=tmp_path / "assets", receipt_secret=b"r" * 32,
        ocr_backend=FakeOcr(fail=ocr_failure),
        downstream_factory=lambda signer: SolarResponsesDownstream(
            endpoint="https://synthetic.example.test/v1/chat/completions", model="solar-pro4",
            receipt_signer=signer, credential_loader=lambda: "synthetic",
            transport=httpx.MockTransport(provider)),
    )
    payload = _image_request()
    original_content = payload["input"][0]["content"]
    original_content.extend([{"type": "input_text", "text": "  둘째: Ａ  "},
                             deepcopy(original_content[1])])
    if history:
        payload["input"] += [{"role": "assistant", "content": "previous answer"},
                             {"role": "user", "content": "Explain the earlier screenshot again"}]
    before = deepcopy(payload)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build_personal_app(runtime)),
                                     base_url="http://127.0.0.1") as client:
            response = await client.post("/v1/responses", json=payload)
    finally:
        await runtime.close()
    if ocr_failure:
        assert not sent
        assert response.json()["error"]["code"] == "ocr_failed"
    else:
        assert response.status_code == 200
        expected_roles = ["user", "assistant", "user"] if history else ["user"]
        assert [m["role"] for m in sent[0]["messages"]] == expected_roles
        text = sent[0]["messages"][0]["content"]
        first_ocr = text.index("ERROR 104 from screenshot")
        second_text = text.index("  둘째: Ａ  ")
        last_ocr = text.rindex("ERROR 104 from screenshot")
        assert first_ocr < second_text < last_ocr
        if history:
            assert sent[0]["messages"][1]["content"] == "previous answer"
            assert sent[0]["messages"][2]["content"] == "Explain the earlier screenshot again"
        assert "data:image" not in json.dumps(sent)
    assert payload == before


@pytest.mark.parametrize("message_id", [None, "msg_codex_1"])
def test_codex_message_id_is_accepted_and_preserved(message_id: str | None) -> None:
    payload = {"model": "solar-pro4", "input": [{
        "type": "message", "id": message_id, "role": "user", "content": "Read a file"}]}
    normalized = normalize_responses_request(payload, None)
    prepared = DownstreamPayload(
        target_id="solar-pro4", capability="non_vision", action="passthrough",
        content=(TextPart(text="Read a file"),), input_digest="a" * 64,
        output_digest="b" * 64, receipt="fixture",
    )
    assert _build_downstream_payload(payload, normalized, prepared)["input"] == payload["input"]


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
