from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[3]


def _config(database_url: str) -> Config:
    config = Config(str(ROOT / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_connection_migration_is_reversible_and_contains_no_raw_credential_column(
    clean_postgres: str,
) -> None:
    config = _config(clean_postgres)
    command.upgrade(config, "head")

    engine = create_engine(clean_postgres)
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("connections")}
    assert {
        "id",
        "name",
        "gateway_url",
        "credential_secret_ref_kind",
        "credential_secret_ref_identifier",
        "enabled",
        "status",
        "last_success_at",
        "last_error_code",
        "created_by",
        "created_at",
        "updated_at",
        "revoked_at",
    } <= columns
    assert not columns & {"credential", "token", "secret", "password", "api_key"}
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0002_connections"
        )
    engine.dispose()

    command.downgrade(config, "0001_control_plane")
    engine = create_engine(clean_postgres)
    assert "connections" not in inspect(engine).get_table_names()
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(clean_postgres)
    assert "connections" in inspect(engine).get_table_names()
    engine.dispose()
