from __future__ import annotations

import sys
from pathlib import Path


def _runtime_type():  # type: ignore[no-untyped-def]
    try:
        from media_bridge_personal.runtime import PersonalRuntime
    except ModuleNotFoundError:
        return None
    return PersonalRuntime


def test_clean_profile_starts_with_local_defaults_without_account_or_database(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Catches first-run composition that still requires legacy DB or account configuration."""

    runtime_type = _runtime_type()
    assert runtime_type is not None, "personal runtime composition is not implemented"
    monkeypatch.delenv("MEDIA_BRIDGE_DATABASE_URL", raising=False)
    monkeypatch.delenv("MEDIA_BRIDGE_CONTROL_DATABASE_URL", raising=False)
    command = (sys.executable, "-c", "import time; time.sleep(60)")
    runtime = runtime_type(profile_root=tmp_path, control_command=command, data_command=command)
    try:
        status = runtime.start()
        assert status.control_pid is not None
        assert status.data_pid is not None
        assert runtime.state.load_last_known_good() == {
            "version": 1,
            "mode": "first_run",
            "rate": {"rpm": 2000, "tpm": 750000},
        }
    finally:
        runtime.stop(timeout_seconds=1.0)
