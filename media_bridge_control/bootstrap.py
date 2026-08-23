"""Bootstrap, administrator authentication, and session service."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select

from media_bridge_control.db import Database
from media_bridge_control.models import (
    AdminSession,
    BootstrapToken,
    RecoveryCode,
    Role,
    User,
)
from media_bridge_control.security import LoginRateLimiter, SecurityContext


class ControlPlaneError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class BootstrapError(ControlPlaneError):
    pass


class AuthenticationError(ControlPlaneError):
    pass


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    user_id: str
    role: str
    recovery_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LoginResult:
    session_token: str
    csrf_token: str
    username: str
    role: str


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str
    username: str
    role: str
    session_selector: str


class ControlPlaneService:
    BOOTSTRAP_TTL = timedelta(minutes=15)
    SESSION_TTL = timedelta(hours=8)

    def __init__(
        self,
        *,
        database: Database,
        security: SecurityContext,
        now: Callable[[], datetime],
        login_limiter: LoginRateLimiter | None = None,
    ) -> None:
        self.database = database
        self.security = security
        self._now = now
        self._login_limiter = login_limiter or LoginRateLimiter(
            limit=5,
            window=timedelta(minutes=5),
        )

    def now(self) -> datetime:
        return self._now()

    @staticmethod
    def _username(value: str) -> str:
        normalized = value.strip().lower()
        if not normalized or len(normalized) > 128:
            raise ControlPlaneError("invalid_input")
        if not all(
            character.isascii() and (character.isalnum() or character in "._-")
            for character in normalized
        ):
            raise ControlPlaneError("invalid_input")
        return normalized

    def issue_bootstrap_token(self) -> str:
        now = self._now()
        token = self.security.issue_token(prefix="mbb", purpose="bootstrap")
        with self.database.session() as session:
            if session.scalar(select(func.count()).select_from(User)):
                raise BootstrapError("already_initialized")
            active = session.scalar(
                select(BootstrapToken).where(
                    BootstrapToken.used_at.is_(None),
                    BootstrapToken.expires_at > now,
                )
            )
            if active is not None:
                raise BootstrapError("bootstrap_token_exists")
            session.add(
                BootstrapToken(
                    selector=token.selector,
                    token_digest=token.digest,
                    expires_at=now + self.BOOTSTRAP_TTL,
                )
            )
        return token.raw

    def complete_bootstrap(self, *, token: str, username: str, password: str) -> BootstrapResult:
        now = self._now()
        selector = self.security.selector(token, prefix="mbb")
        if selector is None:
            raise BootstrapError("bootstrap_token_invalid")
        normalized = self._username(username)
        try:
            password_hash = self.security.passwords.hash(password)
        except ValueError as error:
            raise BootstrapError("invalid_input") from error
        raw_recovery = tuple(secrets.token_urlsafe(18) for _ in range(8))
        with self.database.session() as session:
            stored = session.scalar(
                select(BootstrapToken)
                .where(BootstrapToken.selector == selector)
                .with_for_update()
            )
            initialized = bool(session.scalar(select(func.count()).select_from(User)))
            if (
                stored is None
                or initialized
                or stored.used_at is not None
                or stored.expires_at <= now
                or not self.security.matches(
                    token,
                    stored.token_digest,
                    purpose="bootstrap",
                )
            ):
                raise BootstrapError("bootstrap_token_invalid")
            user = User(
                username=normalized,
                password_hash=password_hash,
                role=Role.ADMIN.value,
                is_active=True,
            )
            session.add(user)
            session.flush()
            for raw in raw_recovery:
                session.add(
                    RecoveryCode(
                        user_id=user.id,
                        code_digest=self.security.digest(raw, purpose="recovery"),
                    )
                )
            stored.used_at = now
            user_id = str(user.id)
        return BootstrapResult(
            user_id=user_id,
            role=Role.ADMIN.value,
            recovery_codes=raw_recovery,
        )

    def login(self, *, username: str, password: str, client_key: str) -> LoginResult:
        now = self._now()
        try:
            normalized = self._username(username)
        except ControlPlaneError as error:
            raise AuthenticationError("invalid_credentials") from error
        rate_key = f"{client_key}:{normalized}"
        if not self._login_limiter.allow(rate_key, now=now):
            raise AuthenticationError("login_rate_limited")
        with self.database.session() as session:
            user = session.scalar(select(User).where(User.username == normalized))
            if (
                user is None
                or not user.is_active
                or not self.security.passwords.verify(user.password_hash, password)
            ):
                self._login_limiter.record_failure(rate_key, now=now)
                raise AuthenticationError("invalid_credentials")
            session_token = self.security.issue_token(prefix="mbs", purpose="session")
            csrf_token = secrets.token_urlsafe(32)
            session.add(
                AdminSession(
                    selector=session_token.selector,
                    session_digest=session_token.digest,
                    csrf_digest=self.security.digest(csrf_token, purpose="csrf"),
                    user_id=user.id,
                    expires_at=now + self.SESSION_TTL,
                )
            )
            role = user.role
        self._login_limiter.clear(rate_key)
        return LoginResult(
            session_token=session_token.raw,
            csrf_token=csrf_token,
            username=normalized,
            role=role,
        )

    def create_user(self, *, username: str, password: str, role: str) -> Principal:
        if role not in {item.value for item in Role}:
            raise ControlPlaneError("invalid_input")
        normalized = self._username(username)
        try:
            password_hash = self.security.passwords.hash(password)
            with self.database.session() as session:
                user = User(
                    username=normalized,
                    password_hash=password_hash,
                    role=role,
                    is_active=True,
                )
                session.add(user)
                session.flush()
                return Principal(
                    user_id=str(user.id),
                    username=user.username,
                    role=user.role,
                    session_selector="",
                )
        except ValueError as error:
            raise ControlPlaneError("invalid_input") from error

    def authenticate(self, session_token: str) -> Principal:
        now = self._now()
        selector = self.security.selector(session_token, prefix="mbs")
        if selector is None:
            raise AuthenticationError("unauthorized")
        with self.database.session() as session:
            stored = session.get(AdminSession, selector)
            if (
                stored is None
                or stored.revoked_at is not None
                or stored.expires_at <= now
                or not self.security.matches(
                    session_token,
                    stored.session_digest,
                    purpose="session",
                )
            ):
                raise AuthenticationError("unauthorized")
            user = session.get(User, stored.user_id)
            if user is None or not user.is_active:
                raise AuthenticationError("unauthorized")
            return Principal(
                user_id=str(user.id),
                username=user.username,
                role=user.role,
                session_selector=stored.selector,
            )

    def authenticate_with_csrf(self, *, session_token: str, csrf_token: str) -> Principal:
        principal = self.authenticate(session_token)
        with self.database.session() as session:
            stored = session.get(AdminSession, principal.session_selector)
            if stored is None or not self.security.matches(
                csrf_token,
                stored.csrf_digest,
                purpose="csrf",
            ):
                raise AuthenticationError("csrf_rejected")
        return principal

    def logout(self, *, session_token: str, csrf_token: str) -> None:
        principal = self.authenticate_with_csrf(
            session_token=session_token,
            csrf_token=csrf_token,
        )
        now = self._now()
        with self.database.session() as session:
            stored = session.scalar(
                select(AdminSession)
                .where(AdminSession.selector == principal.session_selector)
                .with_for_update()
            )
            if stored is None:
                raise AuthenticationError("unauthorized")
            stored.revoked_at = now
