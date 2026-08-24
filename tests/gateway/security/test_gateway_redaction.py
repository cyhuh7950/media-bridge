from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from media_bridge_gateway.app import build_gateway_app
from media_bridge_gateway.auth import CredentialAuthenticationError, SnapshotCredentialVerifier
from media_bridge_gateway.events import GatewayEvent
from media_bridge_gateway.rate_limit import CredentialRouteRateLimiter
from tests.gateway.helpers import TEST_RAW_CREDENTIAL, build_test_runtime
from tests.gateway.unit.test_auth import PEPPER, RAW, _snapshot


def test_authentication_error_and_object_repr_do_not_expose_raw_credential() -> None:
    verifier = SnapshotCredentialVerifier(
        snapshot=_snapshot(),
        pepper=PEPPER,
        now=lambda: datetime(2026, 8, 24, tzinfo=UTC),
    )

    with pytest.raises(CredentialAuthenticationError) as caught:
        verifier.authenticate(
            authorization=f"Bearer {RAW}tampered",
            required_scope="responses:invoke",
            cookie_header=None,
        )

    assert RAW not in str(caught.value)
    assert RAW not in repr(caught.value)
    assert RAW not in repr(verifier)
    assert "super-secret-value" not in str(caught.value)


class RecordingEventSink:
    def __init__(self) -> None:
        self.events: list[GatewayEvent] = []

    def emit(self, event: GatewayEvent) -> None:
        self.events.append(event)


def test_gateway_events_are_bodyless_and_do_not_expose_request_or_credential(
    tmp_path: Path,
) -> None:
    runtime, downstream, asset_store = build_test_runtime(tmp_path)
    sink = RecordingEventSink()
    app = build_gateway_app(
        runtime=runtime,
        asset_store=asset_store,
        rate_limiter=CredentialRouteRateLimiter(
            capacity=10,
            refill_per_second=10,
            max_keys=10,
            idle_ttl_seconds=60,
        ),
        event_sink=sink,
        request_id_factory=lambda: "request-redaction-1",
        monotonic=lambda: 100.0,
    )
    raw_body_marker = "raw-media-or-ocr-marker-never-record"

    with TestClient(app, base_url="https://gateway.test") as client:
        response = client.post(
            "/v1/responses",
            headers={"Authorization": f"Bearer {TEST_RAW_CREDENTIAL}"},
            json={"model": "text-model", "input": raw_body_marker},
        )

    assert response.status_code == 200
    assert len(downstream.requests) == 1
    assert sink.events == [
        GatewayEvent(
            request_id="request-redaction-1",
            event_type="gateway.responses",
            model_id="text-model",
            policy_version=1,
            status_code="completed",
            latency_bucket="lt_100ms",
            size_bucket="lt_2kb",
        )
    ]
    serialized = repr(sink.events)
    assert raw_body_marker not in serialized
    assert TEST_RAW_CREDENTIAL not in serialized
    assert "body" not in GatewayEvent.__dataclass_fields__
    assert "payload" not in GatewayEvent.__dataclass_fields__
