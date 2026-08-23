"""PostgreSQL transaction boundary for the Control Plane."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


class Database:
    """Own a PostgreSQL engine and short-lived sessions."""

    def __init__(self, database_url: str) -> None:
        if not database_url.startswith("postgresql+psycopg://"):
            raise ValueError("Control Plane requires PostgreSQL through psycopg")
        self.engine: Engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
        )
        self._sessions = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            autoflush=False,
        )

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._sessions()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def close(self) -> None:
        self.engine.dispose()
