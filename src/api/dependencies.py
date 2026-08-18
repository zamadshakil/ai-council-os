"""FastAPI authentication dependencies shared by all protected routes."""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, HTTPException, Request, status

from src.core.security import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    AuthCSRFError,
    AuthService,
    AuthSessionInvalid,
    SessionPrincipal,
)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
auth_service = AuthService()


def allowed_browser_origins() -> set[str]:
    """Return the exact browser origins permitted to use cookie sessions.

    Production stays strictly bound to ``APP_ORIGIN``. During local
    development both conventional loopback spellings are accepted so opening
    the dashboard as ``127.0.0.1`` does not break sign-out or other CSRF
    protected mutations when ``APP_ORIGIN`` was left at its localhost default.
    """
    configured = {
        value.strip().rstrip("/")
        for value in os.getenv("APP_ORIGIN", "http://localhost:3000").split(",")
        if value.strip()
    }
    if os.getenv("ENVIRONMENT", "development").lower() != "production":
        configured.update({"http://localhost:3000", "http://127.0.0.1:3000"})
    return configured


@dataclass(frozen=True)
class RequestActor:
    actor_type: str
    actor_id: str
    user_id: str | None = None
    username: str = ""
    role: str = ""
    session_id: str = ""


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _validate_origin(request: Request) -> None:
    """Reject cross-origin cookie mutations before CSRF validation."""
    if request.method.upper() in SAFE_METHODS:
        return
    origin = request.headers.get("origin", "").rstrip("/")
    allowed = allowed_browser_origins()
    production = os.getenv("ENVIRONMENT", "development").lower() == "production"
    if production and not origin:
        raise _error(status.HTTP_403_FORBIDDEN, "ORIGIN_REQUIRED", "Origin header is required")
    if origin and origin not in allowed:
        raise _error(status.HTTP_403_FORBIDDEN, "ORIGIN_REJECTED", "Request origin is not allowed")


async def require_actor(
    request: Request,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    csrf_cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE_NAME),
    csrf_header: str | None = Header(default=None, alias="X-CSRF-Token"),
    service_token: str | None = Header(default=None, alias="X-Service-Token"),
    service_actor: str | None = Header(default=None, alias="X-Service-Actor"),
) -> RequestActor:
    """Accept an administrator session or a configured internal service token."""
    expected_service_token = os.getenv("INTERNAL_SERVICE_TOKEN", "").strip()
    if service_token:
        if not expected_service_token or len(expected_service_token) < 32:
            raise _error(status.HTTP_503_SERVICE_UNAVAILABLE, "SERVICE_AUTH_UNAVAILABLE", "Service authentication is not configured")
        if not hmac.compare_digest(service_token, expected_service_token):
            raise _error(status.HTTP_401_UNAUTHORIZED, "INVALID_SERVICE_TOKEN", "Service token is invalid")
        actor = (service_actor or "internal-service").strip().lower()[:100]
        if actor not in {"telegram", "worker", "scheduler", "internal-service"}:
            actor = "internal-service"
        return RequestActor(actor_type="service", actor_id=actor)

    _validate_origin(request)
    require_csrf = request.method.upper() not in SAFE_METHODS
    if require_csrf and (not csrf_header or not csrf_cookie or not hmac.compare_digest(csrf_header, csrf_cookie)):
        raise _error(status.HTTP_403_FORBIDDEN, "INVALID_CSRF_TOKEN", "CSRF token is missing or invalid")
    try:
        principal: SessionPrincipal = await auth_service.validate_session(
            session_token or "",
            csrf_token=csrf_header,
            require_csrf=require_csrf,
        )
    except AuthCSRFError as exc:
        raise _error(status.HTTP_403_FORBIDDEN, exc.code, str(exc)) from exc
    except AuthSessionInvalid as exc:
        raise _error(status.HTTP_401_UNAUTHORIZED, exc.code, str(exc)) from exc
    return RequestActor(
        actor_type="user",
        actor_id=principal.username,
        user_id=principal.user_id,
        username=principal.username,
        role=principal.role,
        session_id=principal.session_id,
    )


async def require_admin(actor: RequestActor = Depends(require_actor)) -> RequestActor:
    if actor.actor_type == "service":
        raise _error(
            status.HTTP_403_FORBIDDEN,
            "SERVICE_SCOPE_DENIED",
            "This internal service is not permitted to access the requested route",
        )
    if actor.actor_type != "user" or actor.role != "admin":
        raise _error(status.HTTP_403_FORBIDDEN, "ADMIN_REQUIRED", "Administrator access is required")
    return actor


async def require_admin_or_telegram(
    actor: RequestActor = Depends(require_actor),
) -> RequestActor:
    """Allow only the dashboard administrator or the Telegram control service."""
    if actor.actor_type == "user" and actor.role == "admin":
        return actor
    if actor.actor_type == "service" and actor.actor_id == "telegram":
        return actor
    raise _error(
        status.HTTP_403_FORBIDDEN,
        "OPERATOR_REQUIRED",
        "Administrator or Telegram operator access is required",
    )
