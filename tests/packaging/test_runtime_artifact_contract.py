from __future__ import annotations

import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import media_bridge_personal.npm_runtime

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = ROOT / "packaging" / "runtime"
ENTRYPOINT = RUNTIME_DIR / "entrypoint.py"
BUILD_SCRIPT = RUNTIME_DIR / "build-win32-x64.ps1"
LINUX_X64_BUILD_SCRIPT = RUNTIME_DIR / "build-linux-x64.sh"
LINUX_ARM64_BUILD_SCRIPT = RUNTIME_DIR / "build-linux-arm64.sh"
LINUX_X64_VERIFY_SCRIPT = RUNTIME_DIR / "verify-linux-x64.sh"
LINUX_ARM64_VERIFY_SCRIPT = RUNTIME_DIR / "verify-linux-arm64.sh"
BUILD_LOCK = RUNTIME_DIR / "requirements-build.lock"
VERIFY_SCRIPT = RUNTIME_DIR / "verify-win32-x64.ps1"
MANAGED_VERIFY_SCRIPT = RUNTIME_DIR / "verify-managed-runtime.cjs"
WORKFLOW = ROOT / ".github" / "workflows" / "build-runtime-win32-x64.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "publish-npm-runtime-release.yml"


def test_shell_build_scripts_are_pinned_to_lf_in_git() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert "*.sh text eol=lf" in attributes.splitlines()


def test_runtime_entrypoint_calls_personal_server(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        media_bridge_personal.npm_runtime,
        "run_personal_npm_runtime",
        lambda: calls.append("run_personal_npm_runtime"),
    )

    runpy.run_path(str(ENTRYPOINT), run_name="__main__")

    assert calls == ["run_personal_npm_runtime"]


def test_runtime_build_dependency_is_exactly_pinned() -> None:
    requirements = [
        line.strip()
        for line in BUILD_LOCK.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert requirements == ["pyinstaller==6.22.2"]


def test_all_runtime_builds_add_the_repository_source_root_to_pyinstaller() -> None:
    windows = BUILD_SCRIPT.read_text(encoding="utf-8")
    linux_x64 = LINUX_X64_BUILD_SCRIPT.read_text(encoding="utf-8")
    linux_arm64 = LINUX_ARM64_BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "$sourceRoot" in windows
    assert "--paths $sourceRoot" in windows
    for script in (linux_x64, linux_arm64):
        assert 'source_root="$(cd "$script_dir/../.."' in script
        assert '--paths "$source_root"' in script


def test_win32_verifier_provisions_the_personal_runtime_contract() -> None:
    verifier = VERIFY_SCRIPT.read_text(encoding="utf-8")

    assert "MEDIA_BRIDGE_CONFIG_FILE" in verifier
    assert "config.json" in verifier
    assert "MEDIA_BRIDGE_RUNTIME_MODE" in verifier
    assert "MEDIA_BRIDGE_SOLAR_MODEL" in verifier
    assert "MEDIA_BRIDGE_SOLAR_ENDPOINT" in verifier
    assert "MEDIA_BRIDGE_SOLAR_CREDENTIAL_ENV" in verifier
    assert "MEDIA_BRIDGE_OCR_CREDENTIAL_ENV" in verifier
    assert "/v1/document-digitization" in verifier
    managed_verifier = MANAGED_VERIFY_SCRIPT.read_text(encoding="utf-8")
    assert "packageVersion: sourceManifest.packageVersion" in managed_verifier


def test_linux_verifiers_provision_the_personal_runtime_contract() -> None:
    for verifier_path in (LINUX_X64_VERIFY_SCRIPT, LINUX_ARM64_VERIFY_SCRIPT):
        verifier = verifier_path.read_text(encoding="utf-8")
        assert "MEDIA_BRIDGE_CONFIG_FILE" in verifier
        assert "config.json" in verifier
        assert "MEDIA_BRIDGE_RUNTIME_MODE='personal'" in verifier
        assert "MEDIA_BRIDGE_SOLAR_MODEL='solar-pro4'" in verifier
        assert "MEDIA_BRIDGE_SOLAR_ENDPOINT='https://127.0.0.1:9/v1/chat/completions'" in verifier
        assert "MEDIA_BRIDGE_SOLAR_CREDENTIAL_ENV='SOLAR_API_KEY'" in verifier
        assert "MEDIA_BRIDGE_OCR_CREDENTIAL_ENV='SOLAR_API_KEY'" in verifier
        assert "/v1/document-digitization" in verifier


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell is not installed")
def test_runtime_build_script_rejects_invalid_version_before_build(tmp_path: Path) -> None:
    result = subprocess.run(  # noqa: S603 - fixed local PowerShell test command
        [  # noqa: S607 - pwsh is intentionally resolved from the test environment
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


def test_runtime_build_rejects_conda_python_before_pyinstaller(tmp_path: Path) -> None:
    if sys.platform != "win32":
        return

    probe_state = tmp_path / "probe-state.txt"
    pyinstaller_marker = tmp_path / "pyinstaller-invoked.txt"
    fake_python = tmp_path / "fake-conda-python.cmd"
    fake_python.write_text(
        f"""@echo off
if not "%~1"=="-c" goto pyinstaller
if exist "{probe_state}" goto conda
>"{probe_state}" echo architecture-checked
exit /b 0
:conda
exit /b 86
:pyinstaller
>"{pyinstaller_marker}" echo invoked
exit /b 0
""",
        encoding="utf-8",
    )

    result = subprocess.run(  # noqa: S603 - fixed local PowerShell test command
        [  # noqa: S607 - pwsh is intentionally resolved from the test environment
            "pwsh", "-NoProfile", "-File", str(BUILD_SCRIPT),
            "-Python", str(fake_python),
            "-Version", "0.1.0",
            "-OutputDirectory", str(tmp_path / "output"),
            "-WorkDirectory", str(tmp_path / "work"),
            "-BaseUrl", "http://127.0.0.1:18080",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    combined_output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode != 0
    assert "official CPython" in combined_output
    assert not pyinstaller_marker.exists()
    assert not (tmp_path / "output").exists()
    assert not (tmp_path / "work").exists()


def test_runtime_workflow_builds_without_public_release_commands() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "runs-on: windows-2022" in workflow
    assert "packaging/runtime/requirements-build.lock" in workflow
    assert "packaging/runtime/build-win32-x64.ps1" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "gh release" not in workflow
    assert "npm publish" not in workflow


def test_runtime_release_workflow_uses_verified_run_artifacts_without_local_gh() -> None:
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "33838863554" in workflow
    assert "33838880214" in workflow
    assert "33838897611" in workflow
    assert workflow.count("actions/download-artifact@v4") == 3
    assert "runtime-manifest.json" in workflow
    assert "manifest.packageVersion !== version" in workflow
    assert "manifest.version !== version" not in workflow
    assert "createRelease" in workflow
    assert "uploadReleaseAsset" in workflow
    assert "gh release" not in workflow
    assert "npm publish" not in workflow


def test_runtime_verifier_is_wired_to_private_workflow_evidence() -> None:
    verifier = VERIFY_SCRIPT.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "Get-FileHash" in verifier
    assert "runtime-manifest.json" in verifier
    assert "System32\\tar.exe" in verifier
    assert "/health" in verifier
    assert "verification-result.json" in verifier
    assert "sourceCommit" in verifier
    assert "MEDIA_BRIDGE_SERVICE_TOKEN" in verifier
    assert "packaging/runtime/verify-win32-x64.ps1" in workflow
    assert "-SourceCommit '${{ github.sha }}'" in workflow
    assert "RUNTIME_OUTPUT" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "retention-days: 14" in workflow


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell is not installed")
def test_runtime_verifier_rejects_relative_artifact_directory(tmp_path: Path) -> None:
    result = subprocess.run(  # noqa: S603 - fixed local PowerShell test command
        [  # noqa: S607 - pwsh is intentionally resolved from the test environment
            "pwsh",
            "-NoProfile",
            "-File",
            str(VERIFY_SCRIPT),
            "-ArtifactDirectory",
            "relative-output",
            "-TestRoot",
            str(tmp_path / "verify"),
            "-SourceCommit",
            "a" * 40,
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    assert result.returncode != 0
    assert "ArtifactDirectory must be an absolute path" in f"{result.stdout}\n{result.stderr}"
    assert not (tmp_path / "verify").exists()


def test_runtime_verifier_checks_actual_managed_install_and_rollback() -> None:
    verifier = VERIFY_SCRIPT.read_text(encoding="utf-8")
    managed_verifier = MANAGED_VERIFY_SCRIPT.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "resolveRuntime" in managed_verifier
    assert "checksum mismatch" in managed_verifier
    assert "rollbackPreserved" in managed_verifier
    assert "verify-managed-runtime.cjs" in verifier
    assert "managedInstall" in verifier
    assert "managedRollbackPreserved" in verifier
    assert "actions/setup-node@v4" in workflow
    assert "node-version: '22'" in workflow


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

    result = subprocess.run(  # noqa: S603 - fixed local PowerShell test command
        [  # noqa: S607 - pwsh is intentionally resolved from the test environment
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
    system_tar = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "tar.exe"
    listed = subprocess.run(  # noqa: S603 - fixed local Windows system executable
        [str(system_tar), "-tzf", str(artifact)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "bin/media-bridge-runtime.exe" in listed.stdout.replace("\\", "/")
