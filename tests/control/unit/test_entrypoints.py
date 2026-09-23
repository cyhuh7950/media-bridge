from unittest.mock import MagicMock

from media_bridge_control import entrypoints


def test_control_entrypoint_accepts_latest_alembic_revision(monkeypatch) -> None:
    database = MagicMock()
    database.engine.connect.return_value.__enter__.return_value.scalar.return_value = (
        "0010_previous_csrf_digest"
    )
    monkeypatch.setattr(entrypoints, "Database", lambda _url: database)

    entrypoints.require_migration_head("postgresql+psycopg://unused")

    database.close.assert_called_once_with()
