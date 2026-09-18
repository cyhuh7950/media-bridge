from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from media_bridge_control.bootstrap import ControlPlaneError, ControlPlaneService
from media_bridge_control.db import Database
from media_bridge_control.models import User
from media_bridge_control.security import SecurityContext


@pytest.fixture()
def service(migrated_postgres: str) -> tuple[ControlPlaneService, Database]:
    database = Database(migrated_postgres)
    control = ControlPlaneService(
        database=database,
        security=SecurityContext(pepper=b"a" * 32),
        now=lambda: datetime(2026, 9, 18, tzinfo=UTC),
    )
    yield control, database
    database.close()


def test_default_admin_is_created_with_fixed_credentials_and_totp_pending(service) -> None:
    control, database = service

    result = control.ensure_default_admin()

    assert result.username == "admin"
    assert result.totp_required is True
    with database.session() as session:
        user = session.scalar(select(User).where(User.username == "admin"))
        assert user is not None
        assert user.password_hash.startswith("$argon2id$")
        assert user.password_hash != "admin"  # noqa: S105


def test_default_admin_cannot_change_password_or_be_disabled(service) -> None:
    control, _ = service
    user = control.ensure_default_admin()

    with pytest.raises(ControlPlaneError, match="default_admin_protected"):
        control.update_user(
            user_id=user.user_id,
            password="another password",  # noqa: S106
            role=None,
            is_active=None,
        )

    with pytest.raises(ControlPlaneError, match="default_admin_protected"):
        control.update_user(
            user_id=user.user_id,
            password=None,
            role=None,
            is_active=False,
        )
