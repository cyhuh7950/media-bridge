from __future__ import annotations

from dataclasses import asdict

import pytest

from media_bridge.responses_state import ResponsesStateError, ResponsesStateStore


def test_state_store_resolves_only_same_tenant_active_record() -> None:
    now = 1_000.0
    store = ResponsesStateStore(ttl_seconds=60, max_entries=3, clock=lambda: now)

    record = store.put(
        response_id="resp_one",
        tenant_id="tenant-a",
        sanitized_text="safe text",
        media_tainted=False,
        media_modalities=frozenset(),
    )

    assert store.resolve("resp_one", tenant_id="tenant-a") == record
    assert record.expires_at == 1_060.0
    assert set(asdict(record)) == {
        "response_id",
        "tenant_id",
        "sanitized_text",
        "media_tainted",
        "media_modalities",
        "expires_at",
    }


def test_state_store_unknown_cross_tenant_and_expired_are_indistinguishable() -> None:
    now = 1_000.0
    store = ResponsesStateStore(ttl_seconds=10, max_entries=3, clock=lambda: now)
    store.put(
        response_id="resp_one",
        tenant_id="tenant-a",
        sanitized_text="safe text",
        media_tainted=False,
        media_modalities=frozenset(),
    )

    with pytest.raises(ResponsesStateError, match="unavailable") as cross_tenant:
        store.resolve("resp_one", tenant_id="tenant-b")
    assert cross_tenant.value.code == "state_unavailable"

    with pytest.raises(ResponsesStateError, match="unavailable"):
        store.resolve("resp_missing", tenant_id="tenant-a")

    now = 1_011.0
    with pytest.raises(ResponsesStateError, match="unavailable"):
        store.resolve("resp_one", tenant_id="tenant-a")


def test_state_store_capacity_evicts_oldest_entry() -> None:
    now = 1_000.0
    store = ResponsesStateStore(ttl_seconds=60, max_entries=2, clock=lambda: now)
    for response_id in ("resp_one", "resp_two", "resp_three"):
        store.put(
            response_id=response_id,
            tenant_id="tenant-a",
            sanitized_text=response_id,
            media_tainted=False,
            media_modalities=frozenset(),
        )

    with pytest.raises(ResponsesStateError):
        store.resolve("resp_one", tenant_id="tenant-a")
    assert store.resolve("resp_two", tenant_id="tenant-a").sanitized_text == "resp_two"
    assert store.resolve("resp_three", tenant_id="tenant-a").sanitized_text == "resp_three"


def test_state_store_enforces_taint_modality_and_text_bounds() -> None:
    store = ResponsesStateStore(ttl_seconds=60, max_entries=2, clock=lambda: 1_000.0)

    invalid = [
        {"media_tainted": False, "media_modalities": frozenset({"image"})},
        {"media_tainted": True, "media_modalities": frozenset()},
        {"media_tainted": True, "media_modalities": frozenset({"audio"})},
    ]
    for values in invalid:
        with pytest.raises(ValueError):
            store.put(
                response_id="resp_invalid",
                tenant_id="tenant-a",
                sanitized_text="safe",
                **values,
            )

    with pytest.raises(ValueError, match="text"):
        store.put(
            response_id="resp_large",
            tenant_id="tenant-a",
            sanitized_text="x" * 200_001,
            media_tainted=False,
            media_modalities=frozenset(),
        )
