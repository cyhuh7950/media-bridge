"""Ephemeral HTTPS Control Plane for local Playwright verification only."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import shutil
import stat
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import uvicorn
from alembic import command
from alembic.config import Config
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import create_engine, text

from media_bridge_control.runtime import build_control_runtime
from media_bridge_control.secrets import GatewaySecretResolver
from media_bridge_control.settings import ControlSettings

TEST_DATABASE = (
    "postgresql+psycopg://media_bridge_test:media_bridge_test_only@127.0.0.1:55432/"
    "media_bridge_test"
)
E2E_GATEWAY_REFERENCE = "MEDIA_BRIDGE_E2E_GATEWAY_CREDENTIAL"
E2E_GATEWAY_VALUE = "mbc_e2e_only_browser_gateway_credential"


class _NoCostGatewayClient:
    """Exercise the real Admin BFF without network or provider cost."""

    async def status(self, *, base_url: str, credential: str) -> dict[str, object]:
        self._validate(base_url, credential)
        return {"status": "ready", "snapshot_version": 1}

    async def upload(
        self,
        *,
        base_url: str,
        credential: str,
        data: bytes,
        filename: str | None,
        declared_mime: str,
    ) -> str:
        self._validate(base_url, credential)
        if not data or declared_mime not in {"image/png", "application/pdf"}:
            raise RuntimeError("e2e_media_invalid")
        return "ast_0123456789ABCDEFGHJKMNPQRS"

    async def prepare(
        self,
        *,
        base_url: str,
        credential: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        self._validate(base_url, credential)
        return {
            "action": "converted",
            "target_model": "vendor/text-model",
            "contains_image": True,
            "target_supports_vision": False,
            "sanitized_text": "E2E SAFE OCR",
            "original_image_removed": True,
            "error": None,
        }

    async def responses(
        self,
        *,
        base_url: str,
        credential: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        self._validate(base_url, credential)
        return {"id": "resp_e2e_no_provider_cost", "output": []}

    async def delete(
        self,
        *,
        base_url: str,
        credential: str,
        asset_id: str,
    ) -> None:
        self._validate(base_url, credential)
        if not asset_id.startswith("ast_"):
            raise RuntimeError("e2e_asset_invalid")

    @staticmethod
    def _validate(base_url: str, credential: str) -> None:
        if base_url != "https://gateway.invalid" or credential != E2E_GATEWAY_VALUE:
            raise RuntimeError("e2e_gateway_boundary_invalid")


def _reset_isolated_database(database_url: str) -> None:
    parsed = urlparse(database_url.replace("postgresql+psycopg", "postgresql", 1))
    if (
        parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.port != 55432
        or parsed.path != "/media_bridge_test"
    ):
        raise RuntimeError("e2e_database_not_isolated")
    engine = create_engine(database_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def _snapshot_private_key() -> bytes:
    return ed25519.Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _tls_files(directory: Path) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1")), x509.DNSName("localhost")]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    key_path = directory / "tls-key.pem"
    certificate_path = directory / "tls-certificate.pem"
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.chmod(0o600)
    certificate_path.chmod(0o600)
    return key_path, certificate_path


def _write_state_once(path: Path, bootstrap_token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        status = path.lstat()
        if not stat.S_ISREG(status.st_mode) or status.st_uid != os.getuid():
            raise RuntimeError("e2e_state_path_unsafe")
        path.unlink()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, json.dumps({"bootstrap_token": bootstrap_token}).encode("utf-8"))
    finally:
        os.close(descriptor)


def _prepare_runtime_directory(path: Path, state_file: Path) -> None:
    parent = state_file.parent
    if (
        not path.is_absolute()
        or path.parent != parent
        or path.name != "e2e-runtime"
        or path.is_symlink()
        or parent != Path(tempfile.gettempdir()) / "media_bridge_p2a_tools_01a02e88"
        or parent.is_symlink()
    ):
        raise RuntimeError("e2e_runtime_path_unsafe")
    parent.mkdir(mode=0o700, exist_ok=True)
    parent_status = parent.stat()
    if not stat.S_ISDIR(parent_status.st_mode) or parent_status.st_uid != os.getuid():
        raise RuntimeError("e2e_runtime_path_unsafe")
    if path.exists():
        status = path.lstat()
        if not stat.S_ISDIR(status.st_mode) or status.st_uid != os.getuid():
            raise RuntimeError("e2e_runtime_path_unsafe")
        shutil.rmtree(path)
    path.mkdir(mode=0o700)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static-root", type=Path, required=True)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18_443)
    args = parser.parse_args()
    static_root = args.static_root.resolve(strict=True)
    state_file = args.state_file.resolve(strict=False)
    temp_root = args.runtime_dir.resolve(strict=False)
    if args.port != 18_443 or state_file.is_symlink():
        raise RuntimeError("e2e_boundary_invalid")

    database_url = os.environ.get("MEDIA_BRIDGE_E2E_DATABASE_URL", TEST_DATABASE)
    _reset_isolated_database(database_url)
    _prepare_runtime_directory(temp_root, state_file)
    runtime = None
    try:
        key_path, certificate_path = _tls_files(temp_root)
        settings = ControlSettings(
            database_url=database_url,
            security_pepper=os.urandom(64),
            snapshot_private_key_pem=_snapshot_private_key(),
            snapshot_key_id="p2a-e2e-key",
            snapshot_path=temp_root / "active-snapshot.json",
            allowed_origin="https://127.0.0.1:18443",
            allowed_host="127.0.0.1",
            console_static_root=static_root,
        )
        os.environ[E2E_GATEWAY_REFERENCE] = E2E_GATEWAY_VALUE
        runtime = build_control_runtime(
            settings,
            gateway_client=_NoCostGatewayClient(),
            secret_resolver=GatewaySecretResolver(),
        )
        _write_state_once(state_file, runtime.service.issue_bootstrap_token())
        uvicorn.run(
            runtime.app,
            host="127.0.0.1",
            port=args.port,
            ssl_keyfile=str(key_path),
            ssl_certfile=str(certificate_path),
            access_log=False,
            server_header=False,
            log_level="warning",
        )
    finally:
        if runtime is not None:
            runtime.close()
        if state_file.is_file() and not state_file.is_symlink():
            state_file.unlink()
        if temp_root.is_dir() and not temp_root.is_symlink():
            shutil.rmtree(temp_root)
        os.environ.pop(E2E_GATEWAY_REFERENCE, None)


if __name__ == "__main__":
    main()
