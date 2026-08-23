from pathlib import Path

from starlette.testclient import TestClient

from media_bridge_control.runtime import build_control_runtime
from media_bridge_control.settings import ControlSettings
from tests.control.snapshot_helpers import private_key_pem


def test_control_runtime_uses_injected_secrets_and_migrated_postgres(
    migrated_postgres: str,
    tmp_path: Path,
) -> None:
    settings = ControlSettings(
        database_url=migrated_postgres,
        security_pepper=b"runtime-pepper-value-at-least-32-bytes",
        snapshot_private_key_pem=private_key_pem(),
        snapshot_key_id="runtime-test-key",
        snapshot_path=tmp_path / "active-snapshot.json",
        allowed_origin="https://control.test",
        allowed_host="control.test",
    )
    runtime = build_control_runtime(settings)
    try:
        client = TestClient(runtime.app, base_url="https://control.test")
        assert client.get("/admin/v1/health").json() == {"status": "ok"}
        token = runtime.service.issue_bootstrap_token()
        assert token not in repr(runtime)
        assert migrated_postgres not in repr(settings)
        assert "PRIVATE KEY" not in repr(settings)
    finally:
        runtime.close()


def test_control_runtime_optionally_serves_same_origin_console(
    migrated_postgres: str,
    tmp_path: Path,
) -> None:
    console_root = tmp_path / "console"
    (console_root / "assets").mkdir(parents=True)
    (console_root / "index.html").write_text('<div id="root"></div>', encoding="utf-8")
    settings = ControlSettings(
        database_url=migrated_postgres,
        security_pepper=b"runtime-pepper-value-at-least-32-bytes",
        snapshot_private_key_pem=private_key_pem(),
        snapshot_key_id="runtime-test-key",
        snapshot_path=tmp_path / "active-snapshot.json",
        allowed_origin="https://control.test",
        allowed_host="control.test",
        console_static_root=console_root,
    )

    runtime = build_control_runtime(settings)
    try:
        client = TestClient(runtime.app, base_url="https://control.test")
        assert '<div id="root"></div>' in client.get("/").text
        assert client.get("/admin/v1/health").json() == {"status": "ok"}
    finally:
        runtime.close()
