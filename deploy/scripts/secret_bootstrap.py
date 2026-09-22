"""Create deployment system Secrets once, without rotating existing values."""

from __future__ import annotations

import argparse
import base64
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

SECRET_NAMES = (
    "db-password.secret",
    "control-database-url.secret",
    "control-security-pepper.secret",
    "snapshot-private-key.pem",
    "snapshot-public-key.secret",
    "receipt-secret.secret",
)
ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


class SecretBootstrapError(RuntimeError):
    """A deployment Secret set is incomplete, invalid, or unsafe to initialize."""


def _openssl_public_key(private_key: bytes, openssl: str) -> bytes:
    with tempfile.TemporaryDirectory(prefix="media-bridge-key-") as directory:
        private_path = Path(directory) / "snapshot-private-key.pem"
        private_path.write_bytes(private_key)
        private_path.chmod(0o600)
        result = subprocess.run(  # noqa: S603 - absolute OpenSSL binary and fixed args
            [openssl, "pkey", "-in", str(private_path), "-pubout", "-outform", "DER"],
            check=False,
            capture_output=True,
        )
    if result.returncode != 0:
        raise SecretBootstrapError("snapshot_key_invalid")
    der = result.stdout
    if len(der) != len(ED25519_SPKI_PREFIX) + 32 or not der.startswith(ED25519_SPKI_PREFIX):
        raise SecretBootstrapError("snapshot_key_invalid")
    return der[-32:]


def _generate_keypair(openssl: str) -> tuple[bytes, bytes]:
    with tempfile.TemporaryDirectory(prefix="media-bridge-key-") as directory:
        private_path = Path(directory) / "snapshot-private-key.pem"
        generated = subprocess.run(  # noqa: S603 - absolute OpenSSL binary and fixed args
            [openssl, "genpkey", "-algorithm", "Ed25519", "-out", str(private_path)],
            check=False,
            capture_output=True,
        )
        if generated.returncode != 0 or not private_path.is_file():
            raise SecretBootstrapError("snapshot_key_generation_failed")
        private_key = private_path.read_bytes()
    public_key = _openssl_public_key(private_key, openssl)
    public_secret = base64.urlsafe_b64encode(public_key).rstrip(b"=") + b"\n"
    return private_key, public_secret


def _generated_values(openssl: str) -> dict[str, bytes]:
    db_password = secrets.token_hex(32)
    private_key, public_key = _generate_keypair(openssl)
    return {
        "db-password.secret": f"{db_password}\n".encode("ascii"),
        "control-database-url.secret": (
            f"postgresql+psycopg://media_bridge:{db_password}@media-bridge-db:5432/media_bridge\n"
        ).encode("ascii"),
        "control-security-pepper.secret": f"{secrets.token_hex(32)}\n".encode("ascii"),
        "snapshot-private-key.pem": private_key,
        "snapshot-public-key.secret": public_key,
        "receipt-secret.secret": f"{secrets.token_hex(32)}\n".encode("ascii"),
    }


def _validate_existing(
    secrets_dir: Path,
    *,
    owner_ids: tuple[int, int] | None,
    openssl: str,
) -> None:
    paths = {name: secrets_dir / name for name in SECRET_NAMES}
    for name, path in paths.items():
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise SecretBootstrapError("secret_set_invalid")
        if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != 0o400:
            raise SecretBootstrapError("secret_permissions_invalid")
        if owner_ids is not None:
            expected_uid = owner_ids[1] if name == "db-password.secret" else owner_ids[0]
            if path.stat().st_uid != expected_uid:
                raise SecretBootstrapError("secret_owner_invalid")

    db_password = paths["db-password.secret"].read_bytes().strip()
    pepper = paths["control-security-pepper.secret"].read_bytes().strip()
    receipt_secret = paths["receipt-secret.secret"].read_bytes().strip()
    if not re.fullmatch(rb"[0-9a-f]{64}", db_password):
        raise SecretBootstrapError("secret_set_invalid")
    expected_url = (
        b"postgresql+psycopg://media_bridge:" + db_password + b"@media-bridge-db:5432/media_bridge"
    )
    if paths["control-database-url.secret"].read_bytes().strip() != expected_url:
        raise SecretBootstrapError("secret_set_invalid")
    if len(pepper) < 32 or len(receipt_secret) < 32:
        raise SecretBootstrapError("secret_set_invalid")
    try:
        public_key = base64.urlsafe_b64decode(
            paths["snapshot-public-key.secret"].read_bytes().strip() + b"="
        )
    except (ValueError, base64.binascii.Error) as error:
        raise SecretBootstrapError("secret_set_invalid") from error
    if (
        len(public_key) != 32
        or _openssl_public_key(paths["snapshot-private-key.pem"].read_bytes(), openssl)
        != public_key
    ):
        raise SecretBootstrapError("secret_set_invalid")


def ensure_secrets(
    secrets_dir: Path,
    *,
    database_volume_exists: bool,
    owner_ids: tuple[int, int] | None = (10001, 999),
    openssl: str | None = None,
) -> str:
    """Create the full set for a new DB, or validate and preserve an existing set.

    ``owner_ids`` is (application UID, database UID). Passing ``None`` is intended
    for cross-platform tests; production must use the service UIDs from Compose.
    """
    if secrets_dir.is_symlink() or not secrets_dir.is_dir():
        raise SecretBootstrapError("secret_directory_invalid")
    openssl_path = openssl or shutil.which("openssl")
    if not openssl_path or not Path(openssl_path).is_absolute():
        raise SecretBootstrapError("openssl_unavailable")

    lock_path = secrets_dir / ".secret-bootstrap.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise SecretBootstrapError("secret_bootstrap_in_progress") from error

    try:
        paths = [secrets_dir / name for name in SECRET_NAMES]
        present = [path.exists() or path.is_symlink() for path in paths]
        if all(present):
            _validate_existing(
                secrets_dir,
                owner_ids=owner_ids,
                openssl=openssl_path,
            )
            return "preserved"
        if any(present):
            raise SecretBootstrapError("secret_set_incomplete")
        if database_volume_exists:
            raise SecretBootstrapError("secret_set_missing_for_existing_database")
        if owner_ids is not None and os.name != "nt" and os.geteuid() != 0:
            raise SecretBootstrapError("secret_bootstrap_requires_root")

        values = _generated_values(openssl_path)
        staged: list[Path] = []
        try:
            for name in SECRET_NAMES:
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=".secret-bootstrap-", dir=secrets_dir
                )
                temporary = Path(temporary_name)
                staged.append(temporary)
                with os.fdopen(descriptor, "wb") as secret_file:
                    secret_file.write(values[name])
                    secret_file.flush()
                    os.fsync(secret_file.fileno())
                if owner_ids is not None:
                    uid = owner_ids[1] if name == "db-password.secret" else owner_ids[0]
                    os.chown(temporary, uid, uid)
                os.chmod(temporary, 0o400)

            for name, temporary in zip(SECRET_NAMES, staged, strict=True):
                os.link(temporary, secrets_dir / name)
            for temporary in staged:
                os.chmod(temporary, 0o600)
                temporary.unlink()
            for name in SECRET_NAMES:
                os.chmod(secrets_dir / name, 0o400)
            return "created"
        except FileExistsError as error:
            raise SecretBootstrapError("secret_set_changed_during_bootstrap") from error
        finally:
            for temporary in staged:
                temporary.unlink(missing_ok=True)
    finally:
        os.close(lock_fd)
        lock_path.unlink(missing_ok=True)


def _database_volume_exists(docker: str) -> bool:
    if not Path(docker).is_absolute():
        raise SecretBootstrapError("docker_unavailable")
    result = subprocess.run(  # noqa: S603 - absolute Docker CLI and fixed read-only command
        [docker, "volume", "inspect", "media-bridge_database"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    if "no such volume" in result.stderr.lower():
        return False
    raise SecretBootstrapError("docker_volume_inspection_failed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize Media Bridge deployment Secrets once")
    parser.add_argument(
        "--secrets-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "secrets",
    )
    arguments = parser.parse_args()
    if os.name != "nt" and os.geteuid() != 0:
        raise SecretBootstrapError("run_with_sudo_to_set_service_owners")
    docker = shutil.which("docker")
    if not docker:
        raise SecretBootstrapError("docker_unavailable")
    result = ensure_secrets(
        arguments.secrets_dir,
        database_volume_exists=_database_volume_exists(docker),
        owner_ids=(10001, 999),
    )
    print(f"deployment_secrets_{result}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SecretBootstrapError as error:
        raise SystemExit(str(error)) from error
