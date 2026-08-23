from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from media_bridge_control.static import build_console_app


def _admin_app() -> Starlette:
    async def health(_: object) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return Starlette(routes=[Route("/admin/v1/health", health)])


def _static_root(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(
        '<!doctype html><div id="root"></div><script src="/assets/app.js"></script>',
        encoding="utf-8",
    )
    (root / "assets" / "app.js").write_text("globalThis.mediaBridge = true;", encoding="utf-8")
    return root


def test_console_serves_spa_fallback_and_delegates_admin_api(tmp_path: Path) -> None:
    client = TestClient(
        build_console_app(admin_app=_admin_app(), static_root=_static_root(tmp_path)),
        base_url="https://control.test",
    )

    root = client.get("/")
    fallback = client.get("/providers")
    asset = client.get("/assets/app.js")
    health = client.get("/admin/v1/health")
    missing_admin = client.get("/admin/v1/not-implemented")

    assert {root.status_code, fallback.status_code, asset.status_code, health.status_code} == {200}
    assert '<div id="root"></div>' in root.text
    assert fallback.text == root.text
    assert "globalThis.mediaBridge" in asset.text
    assert health.json() == {"status": "ok"}
    assert missing_admin.status_code == 404
    assert '<div id="root"></div>' not in missing_admin.text
    assert root.headers["content-security-policy"] == (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    assert root.headers["x-content-type-options"] == "nosniff"
    assert root.headers["referrer-policy"] == "no-referrer"
    assert root.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert root.headers["cache-control"] == "no-store"
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_console_rejects_missing_or_incomplete_static_build(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()

    for root in (missing, incomplete):
        try:
            build_console_app(admin_app=_admin_app(), static_root=root)
        except ValueError as error:
            assert str(error) == "console_static_build_invalid"
        else:
            raise AssertionError("invalid static build was accepted")
