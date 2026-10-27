"""승인 A안: 실제 Gateway 경로의 무송신 비공개 HTTP 실패 진단 계약."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from media_bridge.acquisition import MediaAcquirer
from media_bridge.assets import AssetStore
from media_bridge.config_snapshot import SignedSnapshot, SnapshotVerifier
from media_bridge.gate import PreRequestGate
from media_bridge.llm_backends import build_llm_backend
from media_bridge.receipts import GateReceiptSigner
from media_bridge.runtime_snapshot import capability_registry_from_snapshot
from media_bridge_control.snapshots import SnapshotSigner
from media_bridge_gateway.app import build_gateway_app
from media_bridge_gateway.downstream import ProviderResponsesDownstream
from media_bridge_gateway.rate_limit import CredentialRouteRateLimiter
from media_bridge_gateway.runtime import GatewayTransactionFactory, VerifiedSnapshotRuntime
from media_bridge_gateway.state import GatewayStateStore
from tests.control.snapshot_helpers import private_key_pem
from tests.gateway.helpers import TEST_PEPPER, TEST_RAW_CREDENTIAL, FakeOcr, FakeVision

LOGGER = "media_bridge.diagnostics"
FIELDS = {
    "contract_version", "event", "gateway_request_id", "request_checksum", "occurred_at",
    "upstream_http_status", "classification", "response_bytes", "content_type_kind",
    "body_status", "inspected_bytes", "body_truncated", "encoding_status", "diagnostic_flags",
}
FLAGS = {
    "schema", "uniqueItems", "response_format", "context_length", "request_too_large",
    "unsupported", "model_not_found",
}
SECRET = "synthetic-upstream-secret-do-not-log"  # noqa: S105 - 합성 시험값
RAW_ERROR = (
    b'{"error":"schema uniqueItems response_format context_length request_too_large '
    b'unsupported model_not_found synthetic-upstream-secret-do-not-log '
    b'https://private-provider.invalid/private-header-value"}'
)


def raw_request(text: str = "원문 비밀 요청") -> bytes:
    # 공백, 한글 UTF8, 마지막 개행까지 해시에 포함되어야 한다.
    return (
        ' { "model" : "qa-alias", "messages" : [{"role":"user","content":'
        + json.dumps(text, ensure_ascii=False) + '}] }\n'
    ).encode("utf-8")


def records(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [json.loads(item.getMessage()) for item in caplog.records if item.name == LOGGER]


def assert_record(record: dict[str, Any], raw: bytes, request_id: str) -> None:
    assert set(record) == FIELDS
    assert record["contract_version"] == "media-bridge-private-http-failure-v1"
    assert record["event"] == "upstream_http_failed"
    assert record["gateway_request_id"] == request_id
    assert record["request_checksum"] == hashlib.sha256(raw).hexdigest()
    assert record["request_checksum"] != hashlib.sha256(
        json.dumps(json.loads(raw), separators=(",", ":")).encode()
    ).hexdigest()
    occurred = datetime.fromisoformat(record["occurred_at"].replace("Z", "+00:00"))
    assert occurred.tzinfo is not None and occurred.utcoffset().total_seconds() == 0
    assert set(record["diagnostic_flags"]) == FLAGS
    assert all(type(value) is bool for value in record["diagnostic_flags"].values())


def gateway(tmp_path: Path, upstream: httpx.AsyncClient, request_ids: list[str]) -> Any:
    now = datetime.now(UTC)
    signer = SnapshotSigner(key_id="private-diag-qa", private_key_pem=private_key_pem())
    verifier = SnapshotVerifier({"private-diag-qa": signer.public_key_bytes})
    receipt_signer = GateReceiptSigner(secret=b"r" * 32)
    assets = AssetStore(tmp_path / "assets")
    digest = hmac.new(
        TEST_PEPPER, f"client_credential\0{TEST_RAW_CREDENTIAL}".encode(), hashlib.sha256
    ).hexdigest()
    body = {
        "registry": {"version": "private-diag-qa", "models": [{
            "id": "qa-alias", "input_modalities": ["text"],
            "pdf_passthrough_verified": False, "provider_id": "qa-provider",
        }]},
        "providers": [{
            "id": "qa-provider", "kind": "llm", "enabled": True,
            "catalog_id": "openai", "protocol": "openai-chat-completions",
            "endpoint": "https://private-provider.invalid/v1", "model_id": "qa-model",
            "reasoning_effort": "provider_default",
        }],
        "policy": {"name": "default", "fail_closed": True},
        "data_plane_auth": {"entries": [{
            "selector": "gateway-client", "digest": digest,
            "scopes": ["responses:invoke"], "revoked": False,
        }]},
    }
    snapshot = signer.sign(
        snapshot_id=UUID("00000000-0000-0000-0000-000000000025"),
        version=1, issued_at=now, body=body,
    )
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(snapshot.model_dump_json(), encoding="utf-8")

    def gate_factory(candidate: SignedSnapshot) -> PreRequestGate:
        return PreRequestGate(
            registry=capability_registry_from_snapshot(candidate),
            acquirer=MediaAcquirer(asset_store=assets), ocr_backend=FakeOcr(),
            vision_backend=FakeVision(), receipt_signer=receipt_signer,
        )

    factory = GatewayTransactionFactory(
        gate_factory=gate_factory,
        downstream_factory=lambda candidate: ProviderResponsesDownstream(
            snapshot=candidate.body, receipt_signer=receipt_signer,
            backend_factory=lambda provider: build_llm_backend(
                provider, credential_loader=lambda: SECRET, client=upstream,
            ),
        ),
        receipt_signer=receipt_signer, state_store_factory=GatewayStateStore,
        credential_pepper=TEST_PEPPER,
    )
    runtime = VerifiedSnapshotRuntime(verifier=verifier, generation_factory=factory)
    runtime.load(snapshot_path)
    ids = iter(request_ids)
    return build_gateway_app(
        runtime=runtime, asset_store=assets,
        rate_limiter=CredentialRouteRateLimiter(
            capacity=50, refill_per_second=50, max_keys=100, idle_ttl_seconds=60,
        ),
        request_id_factory=lambda: next(ids),
    )


def client_for(app: Any) -> httpx.AsyncClient:
    # 실제 socket/network 호출 없음: Gateway도 메모리 ASGI transport만 사용한다.
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://gateway.invalid",
        headers={"Authorization": f"Bearer {TEST_RAW_CREDENTIAL}",
                 "Content-Type": "application/json", "X-Request-ID": "external-untrusted-id"},
    )


@pytest.mark.parametrize("status,classification", [
    (400, "upstream_http"), (401, "authentication"), (403, "authentication"),
    (429, "rate_limit"), (500, "upstream_http"),
])
async def test_actual_gateway_failure_preserves_public_bytes_and_logs_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, status: int, classification: str,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["Authorization"] == f"Bearer {SECRET}"
        return httpx.Response(
            status, content=RAW_ERROR,
            headers={"Content-Type": "application/json; private=private-header-value"},
        )

    raw = raw_request()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        async with client_for(gateway(tmp_path, upstream, ["internal_qa-25"])) as client:
            response = await client.post("/v1/chat/completions", content=raw)
    assert len(calls) == 1
    assert response.status_code == 502
    expected = {"error": {
        "message": "Configured Provider rejected the downstream request.",
        "type": "media_bridge_error", "code": f"downstream_{classification}",
    }}
    assert response.content == json.dumps(expected, separators=(",", ":")).encode()
    emitted = records(caplog)
    assert len(emitted) == 1
    record = emitted[0]
    assert_record(record, raw, "internal_qa-25")
    assert record["upstream_http_status"] == status
    assert type(record["upstream_http_status"]) is int
    assert record["classification"] == classification
    assert record["response_bytes"] == len(RAW_ERROR)
    assert record["content_type_kind"] == "json"
    assert record["body_status"] == "inspected"
    assert record["inspected_bytes"] == len(RAW_ERROR)
    assert record["body_truncated"] is False
    assert record["encoding_status"] == "utf8"
    assert all(record["diagnostic_flags"].values())
    for forbidden in (SECRET, TEST_RAW_CREDENTIAL, "private-provider.invalid",
                      "private-header-value", "원문 비밀 요청", "external-untrusted-id"):
        assert forbidden not in caplog.text
        assert forbidden not in response.text


async def test_parallel_gateway_requests_keep_exact_context_and_reset(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    entered = 0
    release = asyncio.Event()

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal entered
        entered += 1
        if entered == 2:
            release.set()
        await asyncio.wait_for(release.wait(), timeout=2)
        return httpx.Response(400, content=b"unclassified error")

    raws = [raw_request("동시 A"), raw_request("동시 B")]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        async with client_for(gateway(tmp_path, upstream, ["parallel_A", "parallel_B"])) as client:
            responses = await asyncio.gather(*[
                client.post("/v1/chat/completions", content=raw) for raw in raws
            ])
        assert all(response.status_code == 502 for response in responses)
        emitted = records(caplog)
        assert len(emitted) == 2
        by_id = {record["gateway_request_id"]: record for record in emitted}
        for request_id, raw in zip(["parallel_A", "parallel_B"], raws, strict=True):
            assert_record(by_id[request_id], raw, request_id)
        before = len(records(caplog))
        backend = build_llm_backend(
            {"catalog_id": "openai", "protocol": "openai-chat-completions",
             "endpoint": "https://private-provider.invalid/v1", "model_id": "qa-model"},
            credential_loader=lambda: SECRET, client=upstream,
        )
        await backend.analyze(context="no Gateway context", user_request="")
        assert len(records(caplog)) == before
    assert entered == 3


@pytest.mark.parametrize("failure", ["timeout", "transport"])
async def test_transport_failures_do_not_invent_http_records(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, failure: str,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        error = httpx.ReadTimeout if failure == "timeout" else httpx.ConnectError
        raise error("synthetic private exception", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        async with client_for(gateway(tmp_path, upstream, ["transport_qa"])) as client:
            response = await client.post("/v1/chat/completions", content=raw_request())
    assert response.status_code == 502
    assert response.json()["error"]["code"] == f"downstream_{failure}"
    assert calls == 1 and records(caplog) == []
    assert "synthetic private exception" not in caplog.text


async def test_success_bytes_unchanged_and_no_diagnostic(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    monkeypatch.setattr("media_bridge_gateway.downstream.secrets.token_urlsafe", lambda _n: "fixed")
    monkeypatch.setattr("media_bridge.openai_chat.time.time", lambda: 1800000000)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "정상 응답"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        async with client_for(gateway(tmp_path, upstream, ["success_qa"])) as client:
            response = await client.post("/v1/chat/completions", content=raw_request())
    expected = {"id": "resp_fixed", "object": "chat.completion", "created": 1800000000,
                "model": "qa-alias", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": "정상 응답"}, "finish_reason": "stop"}]}
    assert response.status_code == 200
    assert response.content == json.dumps(
        expected, ensure_ascii=False, separators=(",", ":")
    ).encode()
    assert calls == 1 and records(caplog) == []


@pytest.mark.parametrize("broken", ["logger", "formatter"])
async def test_diagnostic_failure_preserves_public_error_and_does_not_retry(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch, broken: str,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    calls = 0

    class BrokenHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if broken == "formatter":
                self.format(record)
            raise RuntimeError("private logger exception must not escape")

    class BrokenFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            raise ValueError("private formatter exception must not escape")

    handler = BrokenHandler()
    handler.setFormatter(BrokenFormatter())
    logger = logging.getLogger(LOGGER)
    monkeypatch.setattr(logger, "handlers", [handler])

    def upstream_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, content=RAW_ERROR)

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler)) as upstream:
        async with client_for(gateway(tmp_path, upstream, ["broken_logger"])) as client:
            response = await client.post("/v1/chat/completions", content=raw_request())
    assert response.status_code == 502
    assert response.json() == {"error": {
        "message": "Configured Provider rejected the downstream request.",
        "type": "media_bridge_error", "code": "downstream_upstream_http",
    }}
    assert calls == 1
    assert "private logger exception" not in caplog.text
    assert "private formatter exception" not in caplog.text

async def test_strict_schema_is_forwarded_unchanged_while_failure_is_only_observed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    schema = {"type": "object", "properties": {
        "answer": {"type": "string"},
        "refs": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
    }, "required": ["answer", "refs"], "additionalProperties": False}
    response_format = {"type": "json_schema", "json_schema": {
        "name": "qa_grounded", "strict": True, "schema": schema,
    }}
    payload = json.loads(raw_request())
    payload["response_format"] = response_format
    payload["max_tokens"] = 512
    raw = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        outgoing = json.loads(request.content)
        assert outgoing["response_format"] == response_format
        assert outgoing["max_completion_tokens"] == 512
        assert outgoing["model"] == "qa-model"
        return httpx.Response(400, content=b"schema uniqueItems")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        async with client_for(gateway(tmp_path, upstream, ["schema_qa"])) as client:
            response = await client.post("/v1/chat/completions", content=raw)
    assert response.status_code == 502 and len(seen) == 1
    emitted = records(caplog)
    assert len(emitted) == 1
    assert_record(emitted[0], raw, "schema_qa")
    assert emitted[0]["diagnostic_flags"]["schema"] is True
    assert emitted[0]["diagnostic_flags"]["uniqueItems"] is True
