from __future__ import annotations

import base64
import re
import subprocess
from pathlib import Path

import pytest

from deploy.scripts import secret_bootstrap


def test_first_deployment_creates_the_complete_secret_set(tmp_path: Path) -> None:
    result = secret_bootstrap.ensure_secrets(tmp_path, database_volume_exists=False, owner_ids=None)

    assert result == "created"
    assert {path.name for path in tmp_path.iterdir()} == {
        "db-password.secret",
        "control-database-url.secret",
        "control-security-pepper.secret",
        "snapshot-private-key.pem",
        "snapshot-public-key.secret",
        "receipt-secret.secret",
    }
    db_password = (tmp_path / "db-password.secret").read_text().strip()
    assert re.fullmatch(r"[0-9a-f]{64}", db_password)
    assert (tmp_path / "control-database-url.secret").read_text() == (
        f"postgresql+psycopg://media_bridge:{db_password}@media-bridge-db:5432/media_bridge\n"
    )
    assert len((tmp_path / "control-security-pepper.secret").read_bytes().strip()) >= 32
    assert (tmp_path / "receipt-secret.secret").read_text().strip() != db_password
    assert (
        (tmp_path / "snapshot-private-key.pem")
        .read_text()
        .startswith("-----BEGIN PRIVATE KEY-----")
    )
    public_key = (tmp_path / "snapshot-public-key.secret").read_text().strip()
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", public_key)
    assert len(base64.urlsafe_b64decode(public_key + "=")) == 32


def test_redeployment_preserves_existing_secret_bytes(tmp_path: Path) -> None:
    secret_bootstrap.ensure_secrets(tmp_path, database_volume_exists=False, owner_ids=None)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    result = secret_bootstrap.ensure_secrets(tmp_path, database_volume_exists=True, owner_ids=None)

    assert result == "preserved"
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_existing_database_without_secrets_fails_without_creating_new_keys(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        secret_bootstrap.SecretBootstrapError,
        match="secret_set_missing_for_existing_database",
    ):
        secret_bootstrap.ensure_secrets(tmp_path, database_volume_exists=True, owner_ids=None)

    assert list(tmp_path.iterdir()) == []


def test_partial_secret_set_fails_closed_without_generating_missing_files(
    tmp_path: Path,
) -> None:
    original = b"existing-value-must-not-be-replaced\n"
    (tmp_path / "control-security-pepper.secret").write_bytes(original)

    with pytest.raises(secret_bootstrap.SecretBootstrapError, match="secret_set_incomplete"):
        secret_bootstrap.ensure_secrets(tmp_path, database_volume_exists=False, owner_ids=None)

    assert (tmp_path / "control-security-pepper.secret").read_bytes() == original
    assert list(tmp_path.iterdir()) == [tmp_path / "control-security-pepper.secret"]


def test_invalid_complete_secret_set_is_not_overwritten(tmp_path: Path) -> None:
    expected = {
        "db-password.secret",
        "control-database-url.secret",
        "control-security-pepper.secret",
        "snapshot-private-key.pem",
        "snapshot-public-key.secret",
        "receipt-secret.secret",
    }
    for name in expected:
        path = tmp_path / name
        path.write_text("invalid\n")
        path.chmod(0o400)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    with pytest.raises(secret_bootstrap.SecretBootstrapError, match="secret_set_invalid"):
        secret_bootstrap.ensure_secrets(tmp_path, database_volume_exists=False, owner_ids=None)

    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


@pytest.mark.parametrize(
    ("returncode", "stderr", "expected"),
    [
        (0, "", True),
        (1, "Error response from daemon: no such volume", False),
    ],
)
def test_database_volume_probe_recognizes_existing_and_missing_volume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stderr: str,
    expected: bool,
) -> None:
    monkeypatch.setattr(
        secret_bootstrap.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["docker"], returncode=returncode, stdout="", stderr=stderr
        ),
    )

    assert secret_bootstrap._database_volume_exists(str(tmp_path / "docker.exe")) is expected


def test_database_volume_probe_fails_closed_when_docker_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        secret_bootstrap.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["docker"], returncode=1, stdout="", stderr="Cannot connect to daemon"
        ),
    )

    with pytest.raises(
        secret_bootstrap.SecretBootstrapError,
        match="docker_volume_inspection_failed",
    ):
        secret_bootstrap._database_volume_exists(str(tmp_path / "docker.exe"))
