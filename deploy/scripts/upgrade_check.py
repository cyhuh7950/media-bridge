"""Pre-upgrade guard requiring a separately verified backup."""

from __future__ import annotations

from pathlib import Path


class UpgradeCheckError(RuntimeError):
    pass


def check(
    *, current: str, target: str, verified_backup: Path | None, supported_from: set[str]
) -> str:
    if verified_backup is None:
        raise UpgradeCheckError("verified_backup_required")
    if current not in supported_from or current == target:
        raise UpgradeCheckError("upgrade_path_unsupported")
    return "upgrade_allowed"

