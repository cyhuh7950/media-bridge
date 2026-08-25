import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"


def test_packaging_files_do_not_embed_secret_values() -> None:
    forbidden = re.compile(r"(?i)(sk-[a-z0-9_-]{16,}|mbc_[a-z0-9_-]{16,}|BEGIN PRIVATE KEY)")
    for path in DEPLOY.rglob("*"):
        if path.is_file():
            assert forbidden.search(path.read_text(encoding="utf-8")) is None, path


def test_dockerfiles_never_accept_secret_build_args_or_env_values() -> None:
    for service in ("data", "control"):
        source = (DEPLOY / "images" / service / "Dockerfile").read_text(encoding="utf-8")
        assert re.search(r"^(ARG|ENV) .*?(SECRET|TOKEN|PASSWORD|PRIVATE_KEY)", source, re.M) is None


def test_secret_value_files_are_ignored() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "deploy/secrets/*.secret" in ignored
    assert "deploy/secrets/*.pem" in ignored
