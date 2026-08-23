from __future__ import annotations

from pathlib import Path

from media_bridge_control.settings import ControlSettings
from tests.control.snapshot_helpers import private_key_pem


def test_control_secrets_load_only_from_exact_environment_or_secret_files(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    from _pytest.monkeypatch import MonkeyPatch

    assert isinstance(monkeypatch, MonkeyPatch)
    database_file = tmp_path / "database-url"
    pepper_file = tmp_path / "security-pepper"
    signing_file = tmp_path / "snapshot-signing-key"
    database_file.write_text(
        "postgresql+psycopg://control:test@127.0.0.1/media_bridge",
        encoding="utf-8",
    )
    pepper_file.write_text("p" * 64, encoding="utf-8")
    signing_file.write_bytes(private_key_pem())
    monkeypatch.setenv("MEDIA_BRIDGE_CONTROL_DATABASE_URL_FILE", str(database_file))
    monkeypatch.setenv("MEDIA_BRIDGE_CONTROL_SECURITY_PEPPER_FILE", str(pepper_file))
    monkeypatch.setenv("MEDIA_BRIDGE_SNAPSHOT_PRIVATE_KEY_FILE", str(signing_file))
    monkeypatch.setenv("MEDIA_BRIDGE_SNAPSHOT_KEY_ID", "test-key")
    monkeypatch.setenv("MEDIA_BRIDGE_SNAPSHOT_PATH", str(tmp_path / "active.json"))
    monkeypatch.setenv("MEDIA_BRIDGE_CONTROL_ORIGIN", "https://control.test")
    monkeypatch.setenv("MEDIA_BRIDGE_CONTROL_HOST", "control.test")
    console_root = tmp_path / "console"
    console_root.mkdir()
    monkeypatch.setenv("MEDIA_BRIDGE_CONSOLE_STATIC_ROOT", str(console_root))

    settings = ControlSettings.from_environment()

    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.snapshot_key_id == "test-key"
    assert settings.console_static_root == console_root
    rendered = repr(settings)
    assert "p" * 64 not in rendered
    assert "BEGIN PRIVATE KEY" not in rendered
