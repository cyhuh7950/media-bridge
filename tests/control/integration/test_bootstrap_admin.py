from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from media_bridge_control.bootstrap import BootstrapError, ControlPlaneService
from media_bridge_control.db import Database
from media_bridge_control.models import BootstrapToken, RecoveryCode, User
from media_bridge_control.security import SecurityContext


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 24, 1, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


@pytest.fixture()
def service(migrated_postgres: str) -> tuple[ControlPlaneService, Database, MutableClock]:
    database = Database(migrated_postgres)
    clock = MutableClock()
    control = ControlPlaneService(
        database=database,
        security=SecurityContext(pepper=b"p" * 32),
        now=clock.now,
    )
    yield control, database, clock
    database.close()


def test_bootstrap_token_expires_and_plaintext_is_not_persisted(
    service: tuple[ControlPlaneService, Database, MutableClock],
) -> None:
    control, database, clock = service
    token = control.issue_bootstrap_token()

    with database.session() as session:
        stored = session.scalar(select(BootstrapToken))
        assert stored is not None
        assert token not in stored.token_digest
        assert token != stored.token_digest

    clock.value += timedelta(minutes=16)
    with pytest.raises(BootstrapError) as failure:
        control.complete_bootstrap(
            token=token,
            username="admin",
            password="correct horse battery staple",
        )
    assert failure.value.code == "bootstrap_token_invalid"


def test_bootstrap_is_single_use_and_password_recovery_values_are_hashed(
    service: tuple[ControlPlaneService, Database, MutableClock],
) -> None:
    control, database, _ = service
    token = control.issue_bootstrap_token()
    result = control.complete_bootstrap(
        token=token,
        username="admin",
        password="correct horse battery staple",
    )

    assert result.role == "admin"
    assert len(result.recovery_codes) == 8
    with database.session() as session:
        user = session.scalar(select(User))
        codes = list(session.scalars(select(RecoveryCode)))
        stored = session.scalar(select(BootstrapToken))
        assert user is not None
        assert user.password_hash.startswith("$argon2id$")
        assert "correct horse battery staple" not in user.password_hash
        assert len(codes) == 8
        assert all(raw not in item.code_digest for raw in result.recovery_codes for item in codes)
        assert stored is not None and stored.used_at is not None

    with pytest.raises(BootstrapError) as reused:
        control.complete_bootstrap(
            token=token,
            username="second",
            password="correct horse battery staple",
        )
    assert reused.value.code == "bootstrap_token_invalid"

    with pytest.raises(BootstrapError) as reissued:
        control.issue_bootstrap_token()
    assert reissued.value.code == "already_initialized"
