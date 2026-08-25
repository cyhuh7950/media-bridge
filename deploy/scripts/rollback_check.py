"""Reject application rollback when the database schema is incompatible."""

from __future__ import annotations


class RollbackCheckError(RuntimeError):
    pass


def check(
    *, current_revision: str, target_revision: str, supported_pairs: set[tuple[str, str]]
) -> str:
    if current_revision == target_revision:
        return "application_rollback_allowed"
    if (current_revision, target_revision) not in supported_pairs:
        raise RollbackCheckError("schema_rollback_unsupported")
    return "schema_rollback_allowed"

