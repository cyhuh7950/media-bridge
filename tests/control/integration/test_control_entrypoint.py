import pytest

from media_bridge_control.entrypoints import MigrationStateError, require_migration_head


def test_control_entrypoint_accepts_expected_migration_head(
    migrated_postgres: str,
) -> None:
    require_migration_head(migrated_postgres)


def test_control_entrypoint_rejects_empty_database(clean_postgres: str) -> None:
    with pytest.raises(MigrationStateError) as failure:
        require_migration_head(clean_postgres)
    assert str(failure.value) == "control_plane_migration_required"
