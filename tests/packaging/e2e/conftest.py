from __future__ import annotations

import http.client
import ipaddress
import json
import os
import shutil
import ssl
import subprocess
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILES = (ROOT / "deploy/compose.yaml", ROOT / "deploy/compose.test.yaml")
PROJECT = os.environ.get("MEDIA_BRIDGE_PACKAGING_PROJECT", "media-bridge-p5-e2e")
ENV_FILE = os.environ.get("MEDIA_BRIDGE_PACKAGING_ENV_FILE")
CONTROL_PORT = int(os.environ.get("MEDIA_BRIDGE_TEST_CONTROL_PORT", "18081"))
DATA_PORT = int(os.environ.get("MEDIA_BRIDGE_TEST_DATA_PORT", "18001"))
ORIGIN = "https://127.0.0.1"
_DATA_CREDENTIAL: str | None = None


def require_e2e() -> None:
    if os.environ.get("MEDIA_BRIDGE_PACKAGING_E2E") != "1" or not ENV_FILE:
        pytest.skip("PACKAGING_E2E_NOT_ENABLED")


def compose(
    *arguments: str,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = ["docker", "compose", "--project-name", PROJECT, "--env-file", ENV_FILE or ""]
    for compose_file in COMPOSE_FILES:
        command.extend(("-f", str(compose_file)))
    command.extend(arguments)
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(  # noqa: S603
        command,
        check=check,
        capture_output=True,
        text=True,
        env=merged_env,
    )


def docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("docker")
    assert executable is not None
    return subprocess.run(  # noqa: S603
        [executable, *arguments],
        check=check,
        capture_output=True,
        text=True,
    )


def _certificate(directory: Path) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
        .sign(key, hashes.SHA256())
    )
    key_path = directory / "tls.key"
    certificate_path = directory / "tls.crt"
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.chmod(0o600)
    return certificate_path, key_path


class _ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _forward(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length) if length else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower()
            not in {
                "connection",
                "content-length",
                "host",
                "origin",
                "x-forwarded-proto",
            }
        }
        headers.update({"Host": "127.0.0.1", "Origin": ORIGIN, "X-Forwarded-Proto": "https"})
        connection = http.client.HTTPConnection("127.0.0.1", CONTROL_PORT, timeout=10)
        connection.request(self.command, self.path, body=body, headers=headers)
        response = connection.getresponse()
        payload = response.read()
        self.send_response(response.status)
        for key, value in response.getheaders():
            if key.lower() not in {"connection", "content-length", "transfer-encoding"}:
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        connection.close()

    def do_DELETE(self) -> None:  # noqa: N802
        self._forward()

    def do_GET(self) -> None:  # noqa: N802
        self._forward()

    def do_PATCH(self) -> None:  # noqa: N802
        self._forward()

    def do_POST(self) -> None:  # noqa: N802
        self._forward()

    def log_message(self, _format: str, *args: Any) -> None:
        return


@pytest.fixture(scope="session")
def control_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[httpx.Client]:
    require_e2e()
    directory = tmp_path_factory.mktemp("local-tls")
    certificate, key = _certificate(directory)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProxyHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client_context = ssl.create_default_context(cafile=str(certificate))
        with httpx.Client(
            base_url=f"https://127.0.0.1:{server.server_port}",
            verify=client_context,
            headers={"Origin": ORIGIN},
            timeout=15,
        ) as client:
            yield client
    finally:
        server.shutdown()
        thread.join(timeout=5)


def issue_bootstrap_token() -> str:
    result = compose(
        "run",
        "--rm",
        "--no-deps",
        "media-bridge-control",
        "python",
        "/opt/media-bridge/deploy/scripts/bootstrap_token.py",
    )
    for line in reversed(result.stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        token = value.get("bootstrap_token")
        if isinstance(token, str):
            return token
    raise AssertionError("bootstrap token was not emitted")


def login(client: httpx.Client) -> str:
    response = client.post(
        "/admin/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["csrf_token"])


def set_data_credential(value: str) -> None:
    global _DATA_CREDENTIAL
    _DATA_CREDENTIAL = value


def data_authorization() -> dict[str, str]:
    assert _DATA_CREDENTIAL is not None, "fresh-install test must create the data credential"
    return {"Authorization": f"Bearer {_DATA_CREDENTIAL}"}
