from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


def _free_port() -> int:
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def _wait_for_web(url: str) -> httpx.Response:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=0.2)
        except httpx.HTTPError:
            time.sleep(0.02)
            continue
        if response.status_code == 200:
            return response
        time.sleep(0.02)
    raise AssertionError("personal web process did not become ready")


def _wait_for_port_closed(port: int) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        with socket.socket() as handle:
            if handle.connect_ex(("127.0.0.1", port)) != 0:
                return
        time.sleep(0.02)
    raise AssertionError("personal web process port remained open")


def test_web_process_serves_first_run_and_persists_settings(tmp_path: Path) -> None:
    port = _free_port()
    process = subprocess.Popen(  # noqa: S603 - fixed local test command, no shell.
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; "
                "from media_bridge_personal.web_entrypoint import run_personal_web; "
                f"run_personal_web(profile_root=Path({str(tmp_path)!r}), port={port})"
            ),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        response = _wait_for_web(f"http://127.0.0.1:{port}/")
        assert 'value="2000"' in response.text
        saved = httpx.post(
            f"http://127.0.0.1:{port}/settings",
            json={"solar_rpm": 100, "solar_tpm": 5000},
            timeout=1,
        )
        assert saved.status_code == 200
        assert saved.json()["status"] == "saved"
    finally:
        process.terminate()
        process.wait(timeout=2)

    _wait_for_port_closed(port)
