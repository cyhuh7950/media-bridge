from __future__ import annotations

import os
from collections.abc import Iterator
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


@pytest.fixture(scope="session")
def postgres_url() -> str:
    value = os.environ.get(
        "MEDIA_BRIDGE_TEST_DATABASE_URL",
        "postgresql+psycopg://media_bridge_test:media_bridge_test_only@127.0.0.1:55432/"
        "media_bridge_test",
    )
    parsed = urlparse(value.replace("postgresql+psycopg", "postgresql", 1))
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        pytest.fail("P1 PostgreSQL tests require a loopback-only database")
    if parsed.path != "/media_bridge_test":
        pytest.fail("P1 PostgreSQL tests require the isolated media_bridge_test database")
    return value


@pytest.fixture()
def clean_postgres(postgres_url: str) -> Iterator[str]:
    engine = create_engine(postgres_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    yield postgres_url


@pytest.fixture()
def migrated_postgres(clean_postgres: str) -> str:
    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    config = Config(str(root / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", clean_postgres)
    command.upgrade(config, "head")
    return clean_postgres
