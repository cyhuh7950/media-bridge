from __future__ import annotations

import os
import signal
import sys
import time


def _supervisor_type():  # type: ignore[no-untyped-def]
    try:
        from media_bridge_personal.supervisor import PersonalSupervisor
    except ModuleNotFoundError:
        return None
    return PersonalSupervisor


def _wait_for(predicate, *, timeout: float = 2.0) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("process condition was not reached before timeout")


def test_control_exit_restarts_only_control_and_stop_reaps_all_children() -> None:
    """Catches a supervisor that kills Data with Control or leaks child processes."""

    supervisor_type = _supervisor_type()
    assert supervisor_type is not None, "personal supervisor is not implemented"
    command = (sys.executable, "-c", "import time; time.sleep(60)")
    supervisor = supervisor_type(control_command=command, data_command=command)
    try:
        supervisor.start()
        initial = supervisor.status()
        assert initial.control_pid is not None
        assert initial.data_pid is not None

        os.kill(initial.control_pid, signal.SIGTERM)
        _wait_for(lambda: supervisor.reconcile().control_pid not in {None, initial.control_pid})
        recovered = supervisor.status()
        assert recovered.data_pid == initial.data_pid
    finally:
        supervisor.stop(timeout_seconds=1.0)
    _wait_for(lambda: supervisor.status().control_pid is None)
    assert supervisor.status().data_pid is None


def test_data_exit_restarts_after_backoff_without_restarting_control() -> None:
    """Catches immediate retry storms and a Data restart that drops Control."""

    supervisor_type = _supervisor_type()
    assert supervisor_type is not None, "personal supervisor is not implemented"
    command = (sys.executable, "-c", "import time; time.sleep(60)")
    supervisor = supervisor_type(
        control_command=command,
        data_command=command,
        restart_base_seconds=0.05,
        restart_max_seconds=0.10,
    )
    try:
        initial = supervisor.start()
        assert initial.control_pid is not None
        assert initial.data_pid is not None
        os.kill(initial.data_pid, signal.SIGTERM)
        _wait_for(lambda: supervisor.status().data_pid is None)

        assert supervisor.reconcile().data_pid is None
        time.sleep(0.06)
        _wait_for(lambda: supervisor.reconcile().data_pid not in {None, initial.data_pid})
        assert supervisor.status().control_pid == initial.control_pid
    finally:
        supervisor.stop(timeout_seconds=1.0)
