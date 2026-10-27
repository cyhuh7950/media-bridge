"""승인 A안의 닫힌 진단 분류·크기·UTF8·context 안전 경계."""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import httpx
import pytest

from tests.gateway.integration.test_private_http_failure_diagnostics import (
    FLAGS,
    LOGGER,
    assert_record,
    records,
)

RAW = b' { "request" : "exact bytes" }\n'


def emit(response: Any, classification: str = "upstream_http") -> None:
    # baseline에서 신규 모듈이 없음을 명확한 RED로 드러내며 skip하지 않는다.
    from media_bridge.diagnostics import diagnostic_scope, record_upstream_http_failure

    with diagnostic_scope("unit_qa-25", RAW):
        record_upstream_http_failure(response, classification)


@pytest.mark.parametrize("content_type,kind", [
    (None, "missing"), ("application/json; token=private-parameter", "json"),
    ("application/problem+json", "json"), ("text/plain; charset=utf-8", "text"),
    ("text/html; private=secret", "html"), ("application/octet-stream", "other"),
])
def test_closed_content_type_classification_never_logs_parameters(
    caplog: pytest.LogCaptureFixture, content_type: str | None, kind: str,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    headers = {"Content-Type": content_type} if content_type is not None else {}
    emit(httpx.Response(400, content=b"unclassified", headers=headers))
    emitted = records(caplog)
    assert len(emitted) == 1
    assert_record(emitted[0], RAW, "unit_qa-25")
    assert emitted[0]["content_type_kind"] == kind
    assert emitted[0]["diagnostic_flags"] == dict.fromkeys(FLAGS, False)
    assert "private-parameter" not in caplog.text
    assert "charset" not in caplog.text


@pytest.mark.parametrize("size", [0, 65535, 65536, 65537, 131072])
def test_only_actual_64k_prefix_is_inspected(
    caplog: pytest.LogCaptureFixture, size: int,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    # schema token은 한도 이후에만 위치: tail을 해석하면 실패해야 한다.
    body = (b"x" * 65536 + b" schema uniqueItems response_format").ljust(size, b"x")[:size]
    emit(httpx.Response(500, content=body))
    record = records(caplog)[0]
    assert record["response_bytes"] == size
    assert type(record["response_bytes"]) is int
    assert record["inspected_bytes"] == min(size, 65536)
    assert record["body_truncated"] is (size > 65536)
    assert record["encoding_status"] == "utf8"
    assert record["body_status"] == "inspected"
    assert record["diagnostic_flags"] == dict.fromkeys(FLAGS, False)
    assert "xxxxx" not in caplog.text


@pytest.mark.parametrize("body,encoding", [
    ("한국어 정상".encode(), "utf8"), (b"\xff\xfe", "invalid_utf8"),
    (b"x" * 65535 + "가".encode(), "invalid_utf8"),
])
def test_utf8_and_truncated_multibyte_prefix_are_distinguished(
    caplog: pytest.LogCaptureFixture, body: bytes, encoding: str,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    emit(httpx.Response(400, content=body))
    record = records(caplog)[0]
    assert record["encoding_status"] == encoding
    assert record["response_bytes"] == len(body)
    assert record["inspected_bytes"] == min(len(body), 65536)
    assert record["body_truncated"] is (len(body) > 65536)
    assert record["diagnostic_flags"] == dict.fromkeys(FLAGS, False)
    assert "한국어 정상" not in caplog.text


def test_unread_body_is_unavailable_not_zero_length(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    response = httpx.Response(400, stream=httpx.ByteStream(b"unread private body"))
    emit(response)
    record = records(caplog)[0]
    assert record["response_bytes"] is None
    assert record["body_status"] == "unavailable"
    assert record["inspected_bytes"] == 0
    assert record["body_truncated"] is None
    assert record["encoding_status"] == "unavailable"
    assert record["diagnostic_flags"] == dict.fromkeys(FLAGS, False)
    assert "unread private body" not in caplog.text


def test_unobservable_header_is_unknown(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    class UnavailableHeaders:
        def get(self, *_args: Any, **_kwargs: Any) -> str:
            raise RuntimeError("private header exception")

    response = httpx.Response(400, content=b"unclassified")
    response.headers = UnavailableHeaders()  # type: ignore[assignment]
    emit(response)
    record = records(caplog)[0]
    assert record["content_type_kind"] == "unknown"
    assert record["body_status"] == "inspected"
    assert "private header exception" not in caplog.text


@pytest.mark.parametrize("request_id", ["", "bad id", "한글", "x" * 129, None, True])
def test_invalid_context_is_not_synthesized(
    caplog: pytest.LogCaptureFixture, request_id: Any,
) -> None:
    from media_bridge.diagnostics import diagnostic_scope, record_upstream_http_failure

    caplog.set_level(logging.DEBUG, logger=LOGGER)
    with diagnostic_scope(request_id, RAW):
        record_upstream_http_failure(httpx.Response(400, content=b"schema"), "upstream_http")
    assert records(caplog) == []


@pytest.mark.parametrize("status", [True, 200, 399, 600])
def test_only_actual_int_http_failure_status_is_logged(
    caplog: pytest.LogCaptureFixture, status: Any,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    response = httpx.Response(400, content=b"schema")
    response.status_code = status
    emit(response)
    assert records(caplog) == []


def test_unknown_classification_does_not_create_arbitrary_field_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    emit(httpx.Response(400, content=b"schema"), "private raw exception classification")
    assert records(caplog) == []


def test_no_context_and_exception_reset_do_not_leak_previous_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from media_bridge.diagnostics import diagnostic_scope, record_upstream_http_failure

    caplog.set_level(logging.DEBUG, logger=LOGGER)
    response = httpx.Response(400, content=b"schema")
    record_upstream_http_failure(response, "upstream_http")
    assert records(caplog) == []
    with pytest.raises(RuntimeError, match="synthetic scope failure"):
        with diagnostic_scope("before_exception", RAW):
            raise RuntimeError("synthetic scope failure")
    record_upstream_http_failure(response, "upstream_http")
    assert records(caplog) == []
    with diagnostic_scope("after_exception", RAW):
        record_upstream_http_failure(response, "upstream_http")
    emitted = records(caplog)
    assert len(emitted) == 1
    assert emitted[0]["gateway_request_id"] == "after_exception"
    assert emitted[0]["request_checksum"] == hashlib.sha256(RAW).hexdigest()


def test_nested_context_restores_outer_bytes(caplog: pytest.LogCaptureFixture) -> None:
    from media_bridge.diagnostics import diagnostic_scope, record_upstream_http_failure

    caplog.set_level(logging.DEBUG, logger=LOGGER)
    response = httpx.Response(400, content=b"schema")
    with diagnostic_scope("outer", RAW):
        with diagnostic_scope("inner", b"different raw"):
            record_upstream_http_failure(response, "upstream_http")
        record_upstream_http_failure(response, "upstream_http")
    emitted = records(caplog)
    assert [item["gateway_request_id"] for item in emitted] == ["inner", "outer"]
    assert emitted[0]["request_checksum"] == hashlib.sha256(b"different raw").hexdigest()
    assert emitted[1]["request_checksum"] == hashlib.sha256(RAW).hexdigest()
    assert "different raw" not in json.dumps(emitted)

@pytest.mark.parametrize("token", sorted(FLAGS))
def test_each_flag_is_independent_closed_word_classification(
    caplog: pytest.LogCaptureFixture, token: str,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    emit(httpx.Response(400, content=token.encode()))
    expected = dict.fromkeys(FLAGS, False)
    expected[token] = True
    assert records(caplog)[0]["diagnostic_flags"] == expected
