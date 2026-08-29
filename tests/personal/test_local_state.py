from __future__ import annotations

from pathlib import Path

import pytest


def _store_type():  # type: ignore[no-untyped-def]
    try:
        from media_bridge_personal.local_state import PersonalStateStore
    except ModuleNotFoundError:
        return None
    return PersonalStateStore


def test_corrupt_active_snapshot_recovers_only_the_previous_lkg(tmp_path: Path) -> None:
    """Catches a partial active write being accepted instead of using prior LKG."""

    store_type = _store_type()
    assert store_type is not None, "personal local-state runtime is not implemented"
    store = store_type(root=tmp_path)

    store.publish({"version": 1, "mode": "safe", "rate": {"rpm": 2000, "tpm": 750000}})
    store.publish({"version": 2, "mode": "safe", "rate": {"rpm": 1000, "tpm": 500000}})
    (tmp_path / "active.json").write_text('{"version":', encoding="utf-8")

    assert store.load_last_known_good() == {
        "version": 1,
        "mode": "safe",
        "rate": {"rpm": 2000, "tpm": 750000},
    }


@pytest.mark.parametrize(
    "unsafe_snapshot",
    [
        {"version": 1, "provider": {"api_key": "raw-secret"}},
        {"version": 1, "request": {"media_body": "data:image/png;base64,AAAA"}},
        {"version": 1, "workspace_path": "/private/user/file.png"},
    ],
)
def test_publish_rejects_sensitive_values_before_any_local_state_is_written(
    tmp_path: Path,
    unsafe_snapshot: dict[str, object],
) -> None:
    """Catches a state writer persisting raw credentials, media, or absolute paths."""

    store_type = _store_type()
    assert store_type is not None, "personal local-state runtime is not implemented"
    store = store_type(root=tmp_path)

    with pytest.raises(Exception, match="snapshot_sensitive_value"):
        store.publish(unsafe_snapshot)

    assert not (tmp_path / "active.json").exists()
    assert not (tmp_path / "previous.json").exists()


def test_sensitive_active_snapshot_is_treated_as_corrupt_and_falls_back_to_lkg(
    tmp_path: Path,
) -> None:
    """Catches invalid active state crashing the runtime instead of preserving LKG."""

    store_type = _store_type()
    assert store_type is not None, "personal local-state runtime is not implemented"
    store = store_type(root=tmp_path)
    store.publish({"version": 1, "mode": "safe"})
    store.publish({"version": 2, "mode": "safe"})
    (tmp_path / "active.json").write_text(
        '{"version":2,"provider":{"api_key":"raw-secret"}}', encoding="utf-8"
    )

    assert store.load_last_known_good() == {"version": 1, "mode": "safe"}
