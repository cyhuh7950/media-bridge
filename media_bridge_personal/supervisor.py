"""Bounded two-process supervision for a local personal installation."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeStatus:
    control_pid: int | None
    data_pid: int | None


class PersonalSupervisor:
    """Keep local Control and Data processes separate and cleanly reaped."""

    def __init__(
        self,
        *,
        control_command: Sequence[str],
        data_command: Sequence[str],
        restart_base_seconds: float = 0.05,
        restart_max_seconds: float = 5.0,
    ) -> None:
        if not control_command or not data_command:
            raise ValueError("runtime commands are required")
        if restart_base_seconds <= 0 or restart_max_seconds < restart_base_seconds:
            raise ValueError("restart backoff is invalid")
        self._control_command = tuple(control_command)
        self._data_command = tuple(data_command)
        self._restart_base_seconds = restart_base_seconds
        self._restart_max_seconds = restart_max_seconds
        self._control: subprocess.Popen[bytes] | None = None
        self._data: subprocess.Popen[bytes] | None = None
        self._stopping = False
        self._control_failures = 0
        self._data_failures = 0
        self._control_restart_pending = False
        self._data_restart_pending = False
        self._control_restart_at = 0.0
        self._data_restart_at = 0.0

    def start(self) -> RuntimeStatus:
        if self._stopping:
            raise RuntimeError("supervisor_stopped")
        if not self._running(self._control):
            self._control = self._launch(self._control_command)
        if not self._running(self._data):
            self._data = self._launch(self._data_command)
        return self.status()

    def reconcile(self) -> RuntimeStatus:
        if not self._stopping:
            self._control = self._reconcile_child(
                process=self._control,
                command=self._control_command,
                name="control",
            )
            self._data = self._reconcile_child(
                process=self._data,
                command=self._data_command,
                name="data",
            )
        return self.status()

    def status(self) -> RuntimeStatus:
        return RuntimeStatus(
            control_pid=self._pid_if_running(self._control),
            data_pid=self._pid_if_running(self._data),
        )

    def stop(self, *, timeout_seconds: float) -> None:
        if timeout_seconds <= 0:
            raise ValueError("stop timeout must be positive")
        self._stopping = True
        children: list[subprocess.Popen[bytes]] = []
        for process in (self._control, self._data):
            if self._running(process):
                assert process is not None
                children.append(process)
        for process in children:
            self._terminate_group(process)
        deadline = time.monotonic() + timeout_seconds
        for process in children:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                self._kill_group(process)
                process.wait(timeout=1.0)
        self._control = None
        self._data = None

    def _reconcile_child(
        self,
        *,
        process: subprocess.Popen[bytes] | None,
        command: Sequence[str],
        name: str,
    ) -> subprocess.Popen[bytes] | None:
        if self._running(process):
            return process
        if process is None:
            return self._launch(command)

        pending, restart_at = self._restart_state(name)
        now = time.monotonic()
        if not pending:
            self._schedule_restart(name, now)
            return process
        if now < restart_at:
            return process
        self._clear_restart_pending(name)
        return self._launch(command)

    def _restart_state(self, name: str) -> tuple[bool, float]:
        if name == "control":
            return self._control_restart_pending, self._control_restart_at
        return self._data_restart_pending, self._data_restart_at

    def _schedule_restart(self, name: str, now: float) -> None:
        if name == "control":
            self._control_failures += 1
            self._control_restart_pending = True
            self._control_restart_at = now + self._backoff(self._control_failures)
            return
        self._data_failures += 1
        self._data_restart_pending = True
        self._data_restart_at = now + self._backoff(self._data_failures)

    def _clear_restart_pending(self, name: str) -> None:
        if name == "control":
            self._control_restart_pending = False
            return
        self._data_restart_pending = False

    def _backoff(self, failures: int) -> float:
        return min(
            self._restart_base_seconds * (2.0 ** (failures - 1)),
            self._restart_max_seconds,
        )

    @staticmethod
    def _running(process: subprocess.Popen[bytes] | None) -> bool:
        return process is not None and process.poll() is None

    @classmethod
    def _pid_if_running(cls, process: subprocess.Popen[bytes] | None) -> int | None:
        if process is None or not cls._running(process):
            return None
        return process.pid

    @staticmethod
    def _launch(command: Sequence[str]) -> subprocess.Popen[bytes]:
        return subprocess.Popen(  # noqa: S603 - commands come from the local package supervisor.
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    @staticmethod
    def _terminate_group(process: subprocess.Popen[bytes]) -> None:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()

    @staticmethod
    def _kill_group(process: subprocess.Popen[bytes]) -> None:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
