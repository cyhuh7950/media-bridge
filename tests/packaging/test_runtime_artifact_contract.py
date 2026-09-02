from __future__ import annotations

import runpy
import subprocess
from pathlib import Path

import media_bridge.entrypoints


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = ROOT / "packaging" / "runtime"
ENTRYPOINT = RUNTIME_DIR / "entrypoint.py"
BUILD_SCRIPT = RUNTIME_DIR / "build-win32-x64.ps1"
BUILD_LOCK = RUNTIME_DIR / "requirements-build.lock"
WORKFLOW = ROOT / ".github" / "workflows" / "build-runtime-win32-x64.yml"


def test_runtime_entrypoint_calls_http_server(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(media_bridge.entrypoints, "run_http", lambda: calls.append("run_http"))

    runpy.run_path(str(ENTRYPOINT), run_name="__main__")

    assert calls == ["run_http"]


def test_runtime_build_dependency_is_exactly_pinned() -> None:
    requirements = [
        line.strip()
        for line in BUILD_LOCK.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert requirements == ["pyinstaller==6.22.2"]


def test_runtime_build_script_rejects_invalid_version_before_build(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(BUILD_SCRIPT),
            "-Python",
            "missing-python.exe",
            "-Version",
            "latest",
            "-OutputDirectory",
            str(tmp_path / "output"),
            "-WorkDirectory",
            str(tmp_path / "work"),
            "-BaseUrl",
            "http://127.0.0.1:18080",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Version must use x.y.z" in f"{result.stdout}\n{result.stderr}"
    assert list(tmp_path.iterdir()) == []


def test_runtime_workflow_builds_without_public_release_commands() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "runs-on: windows-2022" in workflow
    assert "packaging/runtime/requirements-build.lock" in workflow
    assert "packaging/runtime/build-win32-x64.ps1" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "gh release" not in workflow
    assert "npm publish" not in workflow
