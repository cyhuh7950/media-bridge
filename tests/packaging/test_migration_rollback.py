from pathlib import Path

import pytest

from deploy.scripts import migrate, rollback_check, upgrade_check


def test_migration_dry_run_never_applies() -> None:
    applied: list[str] = []
    result = migrate.run_migration(
        current_revision="0001_control_plane",
        target_revision="0005_routing_profiles",
        apply=False,
        upgrade=lambda target: applied.append(target),
    )
    assert result == "migration_required"
    assert applied == []


def test_migration_apply_reaches_exact_head() -> None:
    applied: list[str] = []
    result = migrate.run_migration(
        current_revision="0001_control_plane",
        target_revision="0005_routing_profiles",
        apply=True,
        upgrade=lambda target: applied.append(target),
    )
    assert result == "migration_applied"
    assert applied == ["0005_routing_profiles"]


def test_unknown_or_newer_schema_fails_closed() -> None:
    with pytest.raises(migrate.MigrationError, match="schema_revision_unsupported"):
        migrate.run_migration(
            current_revision="unexpected",
            target_revision="0005_routing_profiles",
            apply=True,
            upgrade=lambda _target: None,
        )


@pytest.mark.parametrize(
    "current_revision",
    [
        "0001_control_plane",
        "0002_connections",
        "0003_deployment_auth",
        "0004_managed_provider_catalog",
        "0005_routing_profiles",
        "0006_provider_api_keys",
        "0007_provider_models",
        "0008_model_provider",
    ],
)
def test_supported_schemas_can_plan_upgrade_to_reasoning_head(current_revision: str) -> None:
    applied: list[str] = []
    result = migrate.run_migration(
        current_revision=current_revision,
        target_revision="0009_provider_reasoning_effort",
        apply=False,
        upgrade=lambda target: applied.append(target),
    )
    assert result == "migration_required"
    assert applied == []


def test_deployment_migration_applies_and_verifies_reasoning_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revisions = iter(("0008_model_provider", "0011_public_model_routing"))
    applied: list[str] = []

    class FakeConfig:
        def set_main_option(self, _key: str, _value: str) -> None:
            pass

    monkeypatch.setattr(migrate, "current_revision", lambda _url: next(revisions))
    monkeypatch.setattr(migrate, "Config", lambda _path: FakeConfig())
    monkeypatch.setattr(
        migrate.command,
        "upgrade",
        lambda _config, target: applied.append(target),
    )

    result = migrate.apply_database_migration(
        database_url="postgresql+psycopg://user:password@localhost/database",
        alembic_ini=Path("migrations/alembic.ini"),
        apply=True,
    )

    assert result == "migration_applied"
    assert applied == ["0011_public_model_routing"]


def test_upgrade_requires_verified_backup_and_exact_version(tmp_path: Path) -> None:
    with pytest.raises(upgrade_check.UpgradeCheckError, match="verified_backup_required"):
        upgrade_check.check(
            current="0.1.0", target="0.2.0", verified_backup=None, supported_from={"0.1.0"}
        )
    marker = tmp_path / "verified-backup"
    assert upgrade_check.check(
        current="0.1.0", target="0.2.0", verified_backup=marker, supported_from={"0.1.0"}
    ) == "upgrade_allowed"


def test_rollback_rejects_schema_downgrade_without_explicit_support() -> None:
    with pytest.raises(rollback_check.RollbackCheckError, match="schema_rollback_unsupported"):
        rollback_check.check(
            current_revision="0003_deployment_auth",
            target_revision="0001_control_plane",
            supported_pairs=set(),
        )
    assert rollback_check.check(
        current_revision="0003_deployment_auth",
        target_revision="0003_deployment_auth",
        supported_pairs=set(),
    ) == "application_rollback_allowed"
