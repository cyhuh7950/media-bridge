from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"


def _dockerfile(service: str) -> str:
    return (DEPLOY / "images" / service / "Dockerfile").read_text(encoding="utf-8")


def test_images_use_exact_digest_and_locked_install() -> None:
    versions = (DEPLOY / "versions.env").read_text(encoding="utf-8")
    assert "PRODUCT_VERSION=0.1.0" in versions
    assert re.search(r"PYTHON_IMAGE=python:3\.12-slim@sha256:[0-9a-f]{64}", versions)

    for service in ("data", "control"):
        source = _dockerfile(service)
        assert re.search(r"^FROM python:3\.12-slim@sha256:[0-9a-f]{64} AS build$", source, re.M)
        assert re.search(r"^FROM python:3\.12-slim@sha256:[0-9a-f]{64}$", source, re.M)
        assert "requirements.lock" in source
        assert "--no-cache-dir" in source
        assert "nonvision_media_bridge-0.1.0-py3-none-any.whl" in source
        assert ":latest" not in source


def test_build_context_is_explicitly_bounded() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    required = {".git", ".env", ".env.*", ".venv", "**/__pycache__", "tests", "docs"}
    assert required.issubset(set(ignored))

