from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


ROOT = Path(__file__).resolve().parents[3]
EXPECTED_TABLES = {
    "admin_sessions",
    "audit_events",
    "bootstrap_tokens",
    "client_credentials",
    "config_drafts",
    "model_capabilities",
    "operational_events",
    "policies",
    "providers",
    "recovery_codes",
    "signing_keys",
    "snapshots",
    "users",
}


def _config(database_url: str) -> Config:
    config = Config(str(ROOT / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_fresh_upgrade_creates_control_plane_schema(clean_postgres: str) -> None:
    command.upgrade(_config(clean_postgres), "head")

    engine = create_engine(clean_postgres)
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    engine.dispose()
    assert revision == "0001_control_plane"


def test_migration_round_trip_is_reversible(clean_postgres: str) -> None:
    config = _config(clean_postgres)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(clean_postgres)
    assert set(inspect(engine).get_table_names()) == set()
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(clean_postgres)
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_user_identity_is_unique_and_snapshot_rows_are_immutable(clean_postgres: str) -> None:
    command.upgrade(_config(clean_postgres), "head")
    engine = create_engine(clean_postgres)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, username, password_hash, role, is_active) "
                "VALUES ('00000000-0000-0000-0000-000000000001', "
                "'admin', 'hash', 'admin', true)"
            )
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, username, password_hash, role, is_active) "
                    "VALUES ('00000000-0000-0000-0000-000000000002', "
                    "'admin', 'hash', 'viewer', true)"
                )
            )

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO signing_keys "
                "(key_id, algorithm, public_key) "
                "VALUES ('test-key', 'ed25519', 'public')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO snapshots "
                "(id, version, schema_version, body, digest, signature, key_id) "
                "VALUES ('00000000-0000-0000-0000-000000000010', 1, "
                "'media-bridge-config/v1', '{}'::jsonb, 'sha256:test', "
                "'ed25519:test', 'test-key')"
            )
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE snapshots SET digest = 'sha256:changed' WHERE version = 1")
            )
    engine.dispose()
