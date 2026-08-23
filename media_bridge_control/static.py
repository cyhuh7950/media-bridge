"""Same-origin Web Console assets without changing the Admin API application."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
)


class _SpaStaticFiles(StaticFiles):
    def __init__(self, *, directory: Path, index_path: Path) -> None:
        super().__init__(directory=str(directory), check_dir=True)
        self.index_path = index_path

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != 404:
                raise
            response = Response(status_code=404)
        parts = PurePosixPath(path).parts
        safe_route = not any(part in {".", ".."} for part in parts)
        if (
            response.status_code == 404
            and scope["method"] in {"GET", "HEAD"}
            and PurePosixPath(path).suffix == ""
            and safe_route
        ):
            return FileResponse(self.index_path, media_type="text/html")
        return response


class _ConsoleRouter:
    def __init__(self, *, admin_app: ASGIApp, static_app: ASGIApp) -> None:
        self.admin_app = admin_app
        self.static_app = static_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] == "http" and (path == "/admin/v1" or path.startswith("/admin/v1/")):
            await self.admin_app(scope, receive, send)
            return
        await self.static_app(scope, receive, send)


class _SecurityHeaders:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                lower_names = {name.lower() for name, _ in headers}

                def add(name: bytes, value: bytes) -> None:
                    if name not in lower_names:
                        headers.append((name, value))

                add(b"content-security-policy", CONTENT_SECURITY_POLICY.encode("ascii"))
                add(b"x-content-type-options", b"nosniff")
                add(b"referrer-policy", b"no-referrer")
                add(b"permissions-policy", b"camera=(), microphone=(), geolocation=()")
                if scope.get("scheme") == "https":
                    add(b"strict-transport-security", b"max-age=31536000; includeSubDomains")
                path = scope.get("path", "")
                cache_value = (
                    b"public, max-age=31536000, immutable"
                    if path.startswith("/assets/")
                    else b"no-store"
                )
                if b"cache-control" not in lower_names:
                    headers.append((b"cache-control", cache_value))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


def build_console_app(*, admin_app: ASGIApp, static_root: Path) -> ASGIApp:
    """Compose immutable assets, SPA fallback, and untouched `/admin/v1` routing."""

    if not static_root.is_absolute() or static_root.is_symlink():
        raise ValueError("console_static_build_invalid")
    try:
        root = static_root.resolve(strict=True)
    except OSError as error:
        raise ValueError("console_static_build_invalid") from error
    index_path = root / "index.html"
    assets_path = root / "assets"
    if (
        not root.is_dir()
        or root.is_symlink()
        or not index_path.is_file()
        or index_path.is_symlink()
        or not assets_path.is_dir()
        or assets_path.is_symlink()
    ):
        raise ValueError("console_static_build_invalid")
    static_app = _SpaStaticFiles(directory=root, index_path=index_path)
    return _SecurityHeaders(_ConsoleRouter(admin_app=admin_app, static_app=static_app))
