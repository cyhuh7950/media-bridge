from __future__ import annotations

import os
import runpy
import subprocess
import sys
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


def test_runtime_build_ignores_git_gnu_tar_precedence_on_windows(tmp_path: Path) -> None:
    if sys.platform != "win32":
        return
    git_tar_directory = Path(r"C:\Program Files\Git\usr\bin")
    if not (git_tar_directory / "tar.exe").is_file():
        return

    fake_python = tmp_path / "fake-python.cmd"
    fake_python.write_text(
        """@echo off
if "%1"=="-c" exit /b 0
set "DIST="
:parse
if "%~1"=="" goto build
if not "%~1"=="--distpath" goto next
shift
set "DIST=%~1"
:next
shift
goto parse
:build
mkdir "%DIST%\\media-bridge-runtime"
>"%DIST%\\media-bridge-runtime\\media-bridge-runtime.exe" echo fixture
exit /b 0
""",
        encoding="utf-8",
    )
    output = tmp_path / "output"
    work = tmp_path / "work"
    env = os.environ.copy()
    env["PATH"] = f"{git_tar_directory}{os.pathsep}{env.get('PATH', '')}"

    result = subprocess.run(
        [
            "pwsh", "-NoProfile", "-File", str(BUILD_SCRIPT),
            "-Python", str(fake_python),
            "-Version", "0.1.0",
            "-OutputDirectory", str(output),
            "-WorkDirectory", str(work),
            "-BaseUrl", "http://127.0.0.1:18080",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    artifact = output / "media-bridge-runtime-0.1.0-win32-x64.tar.gz"
    assert artifact.is_file()
    listed = subprocess.run(
        [str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"), "-tzf", str(artifact)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "bin/media-bridge-runtime.exe" in listed.stdout.replace("\\", "/")
