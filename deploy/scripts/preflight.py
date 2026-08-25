"""Static preflight for a checked-out self-hosted distribution."""

from __future__ import annotations

from pathlib import Path


class PreflightError(RuntimeError):
    pass


def check_layout(root: Path) -> None:
    required = (
        root / "deploy" / "compose.yaml",
        root / "deploy" / "versions.env",
        root / "requirements.lock",
        root / "migrations" / "alembic.ini",
    )
    if any(path.is_symlink() or not path.is_file() for path in required):
        raise PreflightError("distribution_layout_invalid")

