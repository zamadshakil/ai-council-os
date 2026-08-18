"""Server-side session authentication, CSRF validation, and login throttling."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import delete, func, select

from src.core import database as db
from src.core.models import LoginAttemptModel, SessionModel, UserModel, utcnow

SESSION_COOKIE_NAME = "council_session"
CSRF_COOKIE_NAME = "council_csrf"
DEFAULT_SESSION_DAYS = 7


class AuthError(Exception):
    code = "AUTH_ERROR"


class AuthInvalidCredentials(AuthError):
    code = "INVALID_CREDENTIALS"


class AuthLocked(AuthError):
    code = "LOGIN_THROTTLED"

    def __init__(self, retry_after_seconds: int):
        super().__init__("Too many failed login attempts")
        self.retry_after_seconds = max(1, retry_after_seconds)


class AuthSessionInvalid(AuthError):
    code = "INVALID_SESSION"


class AuthCSRFError(AuthError):
    code = "INVALID_CSRF_TOKEN"


@dataclass(frozen=True)
class SessionPrincipal:
    user_id: str
    username: str
    role: str
    session_id: str
    expires_at: datetime


@dataclass(frozen=True)
class CreatedSession:
    session_token: str
    csrf_token: str
    expires_at: datetime
    user: dict[str, Any]


_password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Administrator password must contain at least 12 characters")
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class AuthService:
    """Authentication service designed for FastAPI cookie endpoints."""

    def __init__(
        self,
        *,
        session_factory=None,
        max_failed_attempts: int = 5,
        throttle_window: timedelta = timedelta(minutes=15),
        session_lifetime: timedelta = timedelta(days=DEFAULT_SESSION_DAYS),
    ) -> None:
        self._session_factory = session_factory
        self.max_failed_attempts = max_failed_attempts
        self.throttle_window = throttle_window
        self.session_lifetime = session_lifetime
        self._dummy_hash = hash_password(secrets.token_urlsafe(24))

    @property
    def sessions(self):
        return self._session_factory or db.async_session

    async def ensure_admin(
        self, username: str, password: str, *, rotate_password: bool = False
    ) -> UserModel:
        """Create the single administrator; rotate only when explicitly requested."""
        normalized = username.strip().lower()
        if not normalized:
            raise ValueError("Administrator username is required")
        async with self.sessions() as session:
            result = await session.execute(select(UserModel).where(UserModel.username == normalized))
            user = result.scalar_one_or_none()
            if user is None:
                user = UserModel(username=normalized, password_hash=hash_password(password), role="admin")
                session.add(user)
            elif rotate_password:
                user.password_hash = hash_password(password)
                user.updated_at = utcnow()
                await session.execute(
                    delete(SessionModel).where(SessionModel.user_id == user.id)
                )
            await session.commit()
            await session.refresh(user)
            return user

    async def authenticate(
        self,
        username: str,
        password: str,
        *,
        client_ip: str = "unknown",
        user_agent: str = "",
    ) -> CreatedSession:
        normalized = username.strip().lower()
        now = utcnow()
        cutoff = now - self.throttle_window
        client_ip = (client_ip or "unknown")[:64]

        async with self.sessions() as session:
            count_result = await session.execute(
                select(func.count(LoginAttemptModel.id)).where(
                    LoginAttemptModel.username == normalized,
                    LoginAttemptModel.client_ip == client_ip,
                    LoginAttemptModel.attempted_at >= cutoff,
                )
            )
            failed_count = int(count_result.scalar_one())
            if failed_count >= self.max_failed_attempts:
                oldest_result = await session.execute(
                    select(LoginAttemptModel.attempted_at)
                    .where(
                        LoginAttemptModel.username == normalized,
                        LoginAttemptModel.client_ip == client_ip,
                        LoginAttemptModel.attempted_at >= cutoff,
                    )
                    .order_by(LoginAttemptModel.attempted_at.asc())
                    .limit(1)
                )
                oldest = oldest_result.scalar_one()
                unlock_at = _as_utc(oldest) + self.throttle_window
                raise AuthLocked(int((unlock_at - now).total_seconds()) + 1)

            result = await session.execute(select(UserModel).where(UserModel.username == normalized))
            user = result.scalar_one_or_none()
            valid = verify_password(password, user.password_hash if user else self._dummy_hash)
            if not user or not user.is_active or not valid:
                session.add(LoginAttemptModel(username=normalized, client_ip=client_ip))
                await session.commit()
                raise AuthInvalidCredentials("Invalid username or password")

            await session.execute(
                delete(LoginAttemptModel).where(
                    LoginAttemptModel.username == normalized,
                    LoginAttemptModel.client_ip == client_ip,
                )
            )
            session_token = secrets.token_urlsafe(48)
            csrf_token = secrets.token_urlsafe(32)
            expires_at = now + self.session_lifetime
            auth_session = SessionModel(
                user_id=user.id,
                token_hash=_token_hash(session_token),
                csrf_token_hash=_token_hash(csrf_token),
                expires_at=expires_at,
                client_ip=client_ip,
                user_agent=(user_agent or "")[:512],
            )
            session.add(auth_session)
            await session.commit()
            return CreatedSession(
                session_token=session_token,
                csrf_token=csrf_token,
                expires_at=expires_at,
                user={"id": user.id, "username": user.username, "role": user.role},
            )

    async def validate_session(
        self,
        session_token: str,
        *,
        csrf_token: str | None = None,
        require_csrf: bool = False,
    ) -> SessionPrincipal:
        if not session_token:
            raise AuthSessionInvalid("Session cookie is missing")
        now = utcnow()
        async with self.sessions() as session:
            result = await session.execute(
                select(SessionModel, UserModel)
                .join(UserModel, UserModel.id == SessionModel.user_id)
                .where(SessionModel.token_hash == _token_hash(session_token))
            )
            row = result.one_or_none()
            if not row:
                raise AuthSessionInvalid("Session is invalid")
            auth_session, user = row
            if auth_session.revoked_at or _as_utc(auth_session.expires_at) <= now or not user.is_active:
                raise AuthSessionInvalid("Session is expired or revoked")
            if require_csrf:
                if not csrf_token or not hmac.compare_digest(
                    auth_session.csrf_token_hash, _token_hash(csrf_token)
                ):
                    raise AuthCSRFError("CSRF token is invalid")
            auth_session.last_seen_at = now
            await session.commit()
            return SessionPrincipal(
                user_id=user.id, username=user.username, role=user.role,
                session_id=auth_session.id, expires_at=_as_utc(auth_session.expires_at),
            )

    async def revoke_session(self, session_token: str) -> None:
        async with self.sessions() as session:
            result = await session.execute(
                select(SessionModel).where(SessionModel.token_hash == _token_hash(session_token))
            )
            auth_session = result.scalar_one_or_none()
            if auth_session and not auth_session.revoked_at:
                auth_session.revoked_at = utcnow()
                await session.commit()

    async def revoke_all_user_sessions(self, user_id: str) -> int:
        async with self.sessions() as session:
            result = await session.execute(
                select(SessionModel).where(
                    SessionModel.user_id == user_id, SessionModel.revoked_at.is_(None)
                )
            )
            sessions = result.scalars().all()
            now = utcnow()
            for auth_session in sessions:
                auth_session.revoked_at = now
            await session.commit()
            return len(sessions)
