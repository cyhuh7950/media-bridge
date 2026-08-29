"""Single-user local runtime composition without legacy service dependencies."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from media_bridge_personal.events import PersonalEventLog
from media_bridge_personal.local_state import LocalStateError, PersonalStateStore
from media_bridge_personal.supervisor import PersonalSupervisor, RuntimeStatus

_FIRST_RUN_STATE = {
    "version": 1,
    "mode": "first_run",
    "rate": {"rpm": 2000, "tpm": 750000},
}


class PersonalRuntime:
    """Own local profile state and the separate Control/Data child lifecycle."""

    def __init__(
        self,
        *,
        profile_root: Path,
        control_command: Sequence[str],
        data_command: Sequence[str],
    ) -> None:
        self.state = PersonalStateStore(root=profile_root / "state")
        self.events = PersonalEventLog(root=profile_root / "events", max_entries=200)
        self._supervisor = PersonalSupervisor(
            control_command=control_command,
            data_command=data_command,
        )

    def start(self) -> RuntimeStatus:
        try:
            self.state.load_last_known_good()
        except LocalStateError:
            self.state.publish(_FIRST_RUN_STATE)
        try:
            return self._supervisor.start()
        except Exception:
            self._supervisor.stop(timeout_seconds=1.0)
            raise

    def stop(self, *, timeout_seconds: float) -> None:
        self._supervisor.stop(timeout_seconds=timeout_seconds)
