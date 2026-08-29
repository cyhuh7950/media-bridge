from __future__ import annotations

from pathlib import Path

import pytest


def _event_log_type():  # type: ignore[no-untyped-def]
    try:
        from media_bridge_personal.events import PersonalEventLog
    except ModuleNotFoundError:
        return None
    return PersonalEventLog


@pytest.mark.parametrize(
    "unsafe_event",
    [
        {"status": "blocked", "reason_code": "quality_low", "token": "raw-secret"},
        {"status": "blocked", "reason_code": "quality_low", "media_body": "base64-data"},
        {"status": "blocked", "reason_code": "quality_low", "asset_path": "/private/screen.png"},
    ],
)
def test_event_log_rejects_sensitive_metadata_without_creating_a_log_file(
    tmp_path: Path,
    unsafe_event: dict[str, str],
) -> None:
    """Catches an observability path that persists data-plane bodies or credentials."""

    event_log_type = _event_log_type()
    assert event_log_type is not None, "personal event log is not implemented"
    event_log = event_log_type(root=tmp_path, max_entries=2)

    with pytest.raises(Exception, match="event_sensitive_value"):
        event_log.append(unsafe_event)

    assert not (tmp_path / "events.jsonl").exists()


def test_event_log_keeps_only_the_bounded_latest_metadata(tmp_path: Path) -> None:
    """Catches unbounded personal event retention."""

    event_log_type = _event_log_type()
    assert event_log_type is not None, "personal event log is not implemented"
    event_log = event_log_type(root=tmp_path, max_entries=2)

    event_log.append({"status": "blocked", "reason_code": "first"})
    event_log.append({"status": "blocked", "reason_code": "second"})
    event_log.append({"status": "blocked", "reason_code": "third"})

    assert event_log.read() == [
        {"status": "blocked", "reason_code": "second"},
        {"status": "blocked", "reason_code": "third"},
    ]
