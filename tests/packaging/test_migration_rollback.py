from pathlib import Path

import pytest

from deploy.scripts import migrate, rollback_check, upgrade_check


def test_migration_dry_run_never_applies() -> None:
    applied: list[str] = []
    result = migrate.run_migration(
        current_revision="0001_control_plane",
        target_revision="0002_connections",
        apply=False,
        upgrade=lambda target: applied.append(target),
    )
    assert result == "migration_required"
    assert applied == []


def test_migration_apply_reaches_exact_head() -> None:
    applied: list[str] = []
    result = migrate.run_migration(
        current_revision="0001_control_plane",
        target_revision="0002_connections",
        apply=True,
        upgrade=lambda target: applied.append(target),
    )
    assert result == "migration_applied"
    assert applied == ["0002_connections"]


def test_unknown_or_newer_schema_fails_closed() -> None:
    with pytest.raises(migrate.MigrationError, match="schema_revision_unsupported"):
        migrate.run_migration(
            current_revision="unexpected",
            target_revision="0002_connections",
            apply=True,
            upgrade=lambda _target: None,
        )


def test_upgrade_requires_verified_backup_and_exact_version() -> None:
    with pytest.raises(upgrade_check.UpgradeCheckError, match="verified_backup_required"):
        upgrade_check.check(
            current="0.1.0", target="0.2.0", verified_backup=None, supported_from={"0.1.0"}
        )
    marker = Path("/tmp/verified-backup")
    assert upgrade_check.check(
        current="0.1.0", target="0.2.0", verified_backup=marker, supported_from={"0.1.0"}
    ) == "upgrade_allowed"


def test_rollback_rejects_schema_downgrade_without_explicit_support() -> None:
    with pytest.raises(rollback_check.RollbackCheckError, match="schema_rollback_unsupported"):
        rollback_check.check(
            current_revision="0002_connections",
            target_revision="0001_control_plane",
            supported_pairs=set(),
        )
    assert rollback_check.check(
        current_revision="0002_connections",
        target_revision="0002_connections",
        supported_pairs=set(),
    ) == "application_rollback_allowed"

