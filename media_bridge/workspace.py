"""Restricted temporary workspace whose cleanup is part of gate success."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path


class CleanupError(RuntimeError):
    """Raised when temporary media cannot be proven deleted."""


def _remove_tree(path: Path) -> None:
    shutil.rmtree(path)


class TemporaryMediaWorkspace:
    """Materialize private media files and require verified cleanup."""

    def __init__(
        self,
        *,
        parent: Path | None = None,
        remove_tree: Callable[[Path], None] = _remove_tree,
    ) -> None:
        if parent is not None:
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="media-bridge-", dir=parent))
        self.root.chmod(0o700)
        self._remove_tree = remove_tree
        self.cleanup_verified = False

    def write_bytes(self, filename: str, data: bytes) -> Path:
        """Write one media object without permitting traversal or overwrite."""

        if not filename or filename in {".", ".."} or Path(filename).name != filename:
            raise ValueError("filename must be a single safe path component")
        destination = self.root / filename
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
        except BaseException:
            if destination.exists():
                destination.unlink()
            raise
        return destination

    def cleanup(self) -> None:
        """Remove the workspace and prove it no longer exists."""

        self.cleanup_verified = False
        try:
            self._remove_tree(self.root)
        except BaseException as error:
            raise CleanupError("temporary media cleanup failed") from error
        if self.root.exists():
            raise CleanupError("temporary media cleanup could not be verified")
        self.cleanup_verified = True

    def __enter__(self) -> TemporaryMediaWorkspace:
        return self

    def __exit__(self, *_exception: object) -> None:
        self.cleanup()
