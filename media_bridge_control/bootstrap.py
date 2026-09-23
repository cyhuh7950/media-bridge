"""Bootstrap, administrator authentication, and session service."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, update

from media_bridge_control.db import Database
from media_bridge_control.models import (
    AdminSession,
    BootstrapToken,
    RecoveryCode,
    Role,
    User,
)
from media_bridge_control.security import LoginRateLimiter, SecurityContext
from media_bridge_control.totp import TotpError, generate_secret, provisioning_uri, verify_code


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
class SessionResult:
    principal: Principal
    csrf_token: str


@dataclass(frozen=True, slots=True)
class DefaultAdminResult:
    user_id: str
    username: str
    totp_required: bool


@dataclass(frozen=True, slots=True)
class TotpEnrollment:
    user_id: str
    secret: str
    provisioning_uri: str


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
        recovery_mailer: Callable[[str, str], None] | None = None,
    ) -> None:
        self.database = database
        self.security = security
        self._now = now
        self._login_limiter = login_limiter or LoginRateLimiter(
            limit=5,
            window=timedelta(minutes=5),
        )
        self._recovery_mailer = recovery_mailer

    def now(self) -> datetime:
        return self._now()

    def ensure_default_admin(self, *, recovery_email: str | None = None) -> DefaultAdminResult:
        with self.database.session() as session:
            user = session.scalar(select(User).where(User.username == "admin").with_for_update())
            if user is None:
                user = User(
                    username="admin",
                    password_hash=self.security.passwords.hash(
                        "admin", allow_system_default=True
                    ),
                    role=Role.ADMIN.value,
                    is_active=True,
                    totp_required=True,
                )
                session.add(user)
                session.flush()
            else:
                user.password_hash = self.security.passwords.hash(
                    "admin", allow_system_default=True
                )
                user.role = Role.ADMIN.value
                user.is_active = True
            user.totp_required = True
            if recovery_email is not None:
                user.recovery_email = recovery_email
            return DefaultAdminResult(
                user_id=str(user.id),
                username=user.username,
                totp_required=user.totp_secret_ciphertext is None,
            )

    def begin_totp_enrollment(self, *, user_id: str) -> TotpEnrollment:
        secret = generate_secret()
        with self.database.session() as session:
            user = session.scalar(select(User).where(User.id == user_id).with_for_update())
            if user is None or not user.is_active:
                raise ControlPlaneError("user_not_found")
            user.totp_secret_ciphertext = self.security.encrypt_secret(secret)
            session.flush()
            return TotpEnrollment(
                user_id=str(user.id),
                secret=secret,
                provisioning_uri=provisioning_uri(
                    secret=secret,
                    account=user.username,
                    issuer="Media Bridge",
                ),
            )

    def begin_totp_enrollment_with_password(
        self, *, username: str, password: str
    ) -> TotpEnrollment:
        normalized = self._username(username)
        with self.database.session() as session:
            user = session.scalar(select(User).where(User.username == normalized).with_for_update())
            if (
                user is None
                or not user.is_active
                or not self.security.passwords.verify(user.password_hash, password)
            ):
                raise AuthenticationError("invalid_credentials")
            user_id = str(user.id)
        return self.begin_totp_enrollment(user_id=user_id)

    def confirm_totp_enrollment(self, *, user_id: str, code: str) -> None:
        with self.database.session() as session:
            user = session.scalar(select(User).where(User.id == user_id).with_for_update())
            if user is None or not user.totp_secret_ciphertext:
                raise AuthenticationError("totp_not_enrolled")
            try:
                verify_code(
                    self.security.decrypt_secret(user.totp_secret_ciphertext),
                    code,
                    at=self._now(),
                )
            except (TotpError, ValueError) as error:
                raise AuthenticationError("totp_invalid") from error

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
            if user.totp_required and user.totp_secret_ciphertext is None:
                raise AuthenticationError("totp_required")
            if user.totp_secret_ciphertext is not None:
                raise AuthenticationError("totp_required")
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
    def login_with_totp(
        self, *, username: str, password: str, code: str, client_key: str
    ) -> LoginResult:
        now = self._now()
        try:
            normalized = self._username(username)
        except ControlPlaneError as error:
            raise AuthenticationError("invalid_credentials") from error
        with self.database.session() as session:
            user = session.scalar(select(User).where(User.username == normalized))
            if (
                user is None
                or not user.is_active
                or not self.security.passwords.verify(user.password_hash, password)
                or user.totp_secret_ciphertext is None
            ):
                raise AuthenticationError("invalid_credentials")
            try:
                verify_code(
                    self.security.decrypt_secret(user.totp_secret_ciphertext),
                    code,
                    at=now,
                )
            except (TotpError, ValueError) as error:
                raise AuthenticationError("totp_invalid") from error
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
        return LoginResult(
            session_token=session_token.raw,
            csrf_token=csrf_token,
            username=normalized,
            role=role,
        )

    def request_recovery_code(self, *, username: str, client_key: str) -> None:
        if self._recovery_mailer is None:
            raise AuthenticationError("smtp_not_configured")
        normalized = self._username(username)
        now = self._now()
        rate_key = f"recovery-request:{client_key}:{normalized}"
        if not self._login_limiter.allow(rate_key, now=now):
            raise AuthenticationError("recovery_rate_limited")
        raw_code = secrets.token_urlsafe(18)
        with self.database.session() as session:
            user = session.scalar(select(User).where(User.username == normalized).with_for_update())
            if user is None or not user.is_active or not user.recovery_email:
                raise AuthenticationError("recovery_unavailable")
            session.add(
                RecoveryCode(
                    user_id=user.id,
                    code_digest=self.security.digest(raw_code, purpose="recovery"),
                )
            )
            address = user.recovery_email
        self._recovery_mailer(address, raw_code)
        self._login_limiter.clear(rate_key)

    def login_with_recovery_code(
        self, *, username: str, password: str, recovery_code: str, client_key: str
    ) -> LoginResult:
        normalized = self._username(username)
        now = self._now()
        rate_key = f"recovery-login:{client_key}:{normalized}"
        if not self._login_limiter.allow(rate_key, now=now):
            raise AuthenticationError("recovery_rate_limited")
        with self.database.session() as session:
            user = session.scalar(select(User).where(User.username == normalized).with_for_update())
            codes = [] if user is None else list(
                session.scalars(
                    select(RecoveryCode).where(
                        RecoveryCode.user_id == user.id,
                        RecoveryCode.used_at.is_(None),
                    ).with_for_update()
                )
            )
            match = next(
                (
                    item
                    for item in codes
                    if self.security.matches(recovery_code, item.code_digest, purpose="recovery")
                ),
                None,
            )
            if (
                user is None
                or not user.is_active
                or not self.security.passwords.verify(user.password_hash, password)
                or match is None
            ):
                self._login_limiter.record_failure(rate_key, now=now)
                raise AuthenticationError("recovery_rejected")
            match.used_at = now
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

    def update_user(
        self,
        *,
        user_id: str,
        password: str | None,
        role: str | None,
        is_active: bool | None,
    ) -> Principal:
        if role is not None and role not in {item.value for item in Role}:
            raise ControlPlaneError("invalid_input")
        try:
            password_hash = (
                self.security.passwords.hash(password) if password is not None else None
            )
            with self.database.session() as session:
                user = session.scalar(
                    select(User).where(User.id == user_id).with_for_update()
                )
                if user is None:
                    raise ControlPlaneError("user_not_found")
                if user.username == "admin" and (password is not None or is_active is False):
                    raise ControlPlaneError("default_admin_protected")
                next_role = role if role is not None else user.role
                next_active = is_active if is_active is not None else user.is_active
                if user.role == Role.ADMIN.value and user.is_active and (
                    next_role != Role.ADMIN.value or not next_active
                ):
                    active_admins = session.scalar(
                        select(func.count()).select_from(User).where(
                            User.role == Role.ADMIN.value,
                            User.is_active.is_(True),
                        )
                    )
                    if int(active_admins or 0) <= 1:
                        raise ControlPlaneError("last_admin_required")
                user.role = next_role
                user.is_active = next_active
                if password_hash is not None:
                    user.password_hash = password_hash
                session.flush()
                return Principal(
                    user_id=str(user.id),
                    username=user.username,
                    role=user.role,
                    session_selector="",
                )
        except ValueError as error:
            raise ControlPlaneError("invalid_input") from error

    def recover_password(
        self,
        *,
        username: str,
        recovery_code: str,
        new_password: str,
        client_key: str,
    ) -> None:
        now = self._now()
        try:
            normalized = self._username(username)
            password_hash = self.security.passwords.hash(new_password)
        except (ControlPlaneError, ValueError) as error:
            raise AuthenticationError("recovery_rejected") from error
        rate_key = f"recovery:{client_key}:{normalized}"
        if not self._login_limiter.allow(rate_key, now=now):
            raise AuthenticationError("recovery_rate_limited")
        with self.database.session() as session:
            user = session.scalar(
                select(User).where(User.username == normalized).with_for_update()
            )
            codes = []
            if user is not None and user.is_active:
                codes = list(
                    session.scalars(
                        select(RecoveryCode)
                        .where(
                            RecoveryCode.user_id == user.id,
                            RecoveryCode.used_at.is_(None),
                        )
                        .with_for_update()
                    )
                )
            matches = [
                code
                for code in codes
                if self.security.matches(
                    recovery_code,
                    code.code_digest,
                    purpose="recovery",
                )
            ]
            if user is None or len(matches) != 1:
                self._login_limiter.record_failure(rate_key, now=now)
                raise AuthenticationError("recovery_rejected")
            matches[0].used_at = now
            user.password_hash = password_hash
            session.execute(
                update(AdminSession)
                .where(
                    AdminSession.user_id == user.id,
                    AdminSession.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
        self._login_limiter.clear(rate_key)

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
            if stored is None:
                raise AuthenticationError("csrf_rejected")
            valid_digests = (stored.csrf_digest, stored.previous_csrf_digest)
            if not any(
                digest is not None
                and self.security.matches(csrf_token, digest, purpose="csrf")
                for digest in valid_digests
            ):
                raise AuthenticationError("csrf_rejected")
        return principal

    def refresh_csrf(self, session_token: str) -> SessionResult:
        """Issue a fresh in-memory CSRF token for an existing session."""
        principal = self.authenticate(session_token)
        csrf_token = secrets.token_urlsafe(32)
        with self.database.session() as session:
            stored = session.scalar(
                select(AdminSession)
                .where(AdminSession.selector == principal.session_selector)
                .with_for_update()
            )
            if stored is None:
                raise AuthenticationError("unauthorized")
            stored.previous_csrf_digest = stored.csrf_digest
            stored.csrf_digest = self.security.digest(csrf_token, purpose="csrf")
        return SessionResult(principal=principal, csrf_token=csrf_token)

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
