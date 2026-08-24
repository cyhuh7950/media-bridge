from __future__ import annotations

import pytest

from media_bridge_gateway.state import GatewayStateError, GatewayStateStore


def test_state_is_subject_scoped_and_keeps_only_sanitized_metadata() -> None:
    store = GatewayStateStore(clock=lambda: 100.0)
    record = store.put(
        response_id="resp_safe",
        tenant_id="client-selector-a",
        credential_selector="selector-a",
        sanitized_text="sanitized user context",
        media_tainted=True,
        media_modalities=frozenset({"image"}),
        target_id="vendor/text-model",
        snapshot_version=7,
    )

    assert record.sanitized_text == "sanitized user context"
    assert record.target_id == "vendor/text-model"
    assert record.snapshot_version == 7
    assert not hasattr(record, "assistant_message")
    assert not hasattr(record, "reasoning")
    assert not hasattr(record, "tool_result")
    with pytest.raises(GatewayStateError):
        store.resolve(
            "resp_safe",
            tenant_id="client-selector-a",
            credential_selector="selector-b",
        )


def test_state_ttl_and_capacity_are_bounded() -> None:
    now = 100.0
    store = GatewayStateStore(ttl_seconds=10, max_entries=1, clock=lambda: now)
    store.put(
        response_id="resp_first",
        tenant_id="client-selector-a",
        credential_selector="selector-a",
        sanitized_text="first",
        media_tainted=False,
        media_modalities=frozenset(),
        target_id="model-a",
        snapshot_version=1,
    )
    store.put(
        response_id="resp_second",
        tenant_id="client-selector-a",
        credential_selector="selector-a",
        sanitized_text="second",
        media_tainted=False,
        media_modalities=frozenset(),
        target_id="model-a",
        snapshot_version=1,
    )

    with pytest.raises(GatewayStateError):
        store.resolve(
            "resp_first",
            tenant_id="client-selector-a",
            credential_selector="selector-a",
        )
    now += 11
    with pytest.raises(GatewayStateError):
        store.resolve(
            "resp_second",
            tenant_id="client-selector-a",
            credential_selector="selector-a",
        )
