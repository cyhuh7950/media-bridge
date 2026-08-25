from __future__ import annotations

import hmac
import json
import os
import socket
import ssl
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

MAX_BODY = 4 * 1024 * 1024


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _secret(name: str) -> bytes:
    path = Path(_required(name))
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 16_384:
        raise RuntimeError(f"{name} is invalid")
    value = path.read_bytes().strip()
    if not value:
        raise RuntimeError(f"{name} is empty")
    return value


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    counters: ClassVar[dict[str, int]] = {"ocr": 0, "vision": 0, "downstream": 0}
    lock: ClassVar[threading.Lock] = threading.Lock()
    keys: ClassVar[dict[str, bytes]] = {}

    def _json(self, status: int, value: object) -> None:
        payload = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _authorized(self, key_name: str) -> bool:
        supplied = self.headers.get("Authorization", "").encode()
        expected = b"Bearer " + self.keys[key_name]
        return hmac.compare_digest(supplied, expected)

    def _discard(self) -> bool:
        raw = self.headers.get("Content-Length", "")
        try:
            length = int(raw)
        except ValueError:
            self._json(411, {"error": "length_required"})
            return False
        if length < 1 or length > MAX_BODY:
            self._json(413, {"error": "size_rejected"})
            return False
        remaining = length
        while remaining:
            chunk = self.rfile.read(min(remaining, 64 * 1024))
            if not chunk:
                self._json(400, {"error": "body_incomplete"})
                return False
            remaining -= len(chunk)
        return True

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"status": "ok", "kind": "synthetic"})
            return
        if self.path == "/metrics":
            with self.lock:
                counters = dict(self.counters)
            self._json(200, {"kind": "synthetic", "calls": counters})
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        route = {
            "/v1/document-digitization": "ocr",
            "/v1/chat/completions": "vision",
            "/v1/responses": "downstream",
        }.get(self.path)
        if route is None:
            self._json(404, {"error": "not_found"})
            return
        if not self._authorized(route):
            self._json(401, {"error": "authentication"})
            return
        if not self._discard():
            return
        with self.lock:
            self.counters[route] += 1
            sequence = self.counters[route]
        if route == "ocr":
            self._json(200, {"text": "Synthetic OCR result for staging acceptance."})
        elif route == "vision":
            self._json(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": "Synthetic visual description for staging acceptance."
                            }
                        }
                    ]
                },
            )
        else:
            self._json(200, {"id": f"resp_synthetic_{sequence}", "output": []})

    def log_message(self, _format: str, *args: object) -> None:
        return


def _health() -> int:
    host = "127.0.0.1"
    port = int(_required("MOCK_BIND_PORT"))
    context = ssl.create_default_context(cafile=_required("MOCK_TLS_CERTIFICATE_FILE"))
    try:
        with (
            socket.create_connection((host, port), timeout=2) as raw,
            context.wrap_socket(raw, server_hostname="media-bridge-staging-mock"),
        ):
            return 0
    except OSError:
        return 1


def main() -> int:
    if sys.argv[1:] == ["--health"]:
        return _health()
    Handler.keys = {
        "ocr": _secret("MOCK_OCR_KEY_FILE"),
        "vision": _secret("MOCK_VISION_KEY_FILE"),
        "downstream": _secret("MOCK_DOWNSTREAM_KEY_FILE"),
    }
    host = _required("MOCK_BIND_HOST")
    port = int(_required("MOCK_BIND_PORT"))
    server = ThreadingHTTPServer((host, port), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(
        _required("MOCK_TLS_CERTIFICATE_FILE"),
        _required("MOCK_TLS_PRIVATE_KEY_FILE"),
    )
    server.socket = context.wrap_socket(server.socket, server_side=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
