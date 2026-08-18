from __future__ import annotations

from datetime import timedelta

import pytest

from src.core.security import (
    AuthCSRFError,
    AuthInvalidCredentials,
    AuthLocked,
    AuthService,
    AuthSessionInvalid,
)


@pytest.mark.asyncio
async def test_server_side_session_csrf_and_revocation(session_factory):
    service = AuthService(session_factory=session_factory)
    await service.ensure_admin("Admin", "a-very-long-test-password")

    created = await service.authenticate(
        "admin", "a-very-long-test-password", client_ip="127.0.0.1", user_agent="pytest"
    )
    principal = await service.validate_session(
        created.session_token, csrf_token=created.csrf_token, require_csrf=True
    )
    assert principal.username == "admin"
    assert created.user["role"] == "admin"

    with pytest.raises(AuthCSRFError):
        await service.validate_session(
            created.session_token, csrf_token="incorrect", require_csrf=True
        )

    await service.revoke_session(created.session_token)
    with pytest.raises(AuthSessionInvalid):
        await service.validate_session(created.session_token)


@pytest.mark.asyncio
async def test_failed_logins_are_persistently_throttled(session_factory):
    service = AuthService(
        session_factory=session_factory,
        max_failed_attempts=2,
        throttle_window=timedelta(minutes=10),
    )
    await service.ensure_admin("admin", "a-very-long-test-password")

    for _ in range(2):
        with pytest.raises(AuthInvalidCredentials):
            await service.authenticate("admin", "wrong-password", client_ip="10.0.0.1")

    with pytest.raises(AuthLocked) as error:
        await service.authenticate("admin", "a-very-long-test-password", client_ip="10.0.0.1")
    assert error.value.retry_after_seconds > 0

    # Throttling is scoped to the username/client pair.
    created = await service.authenticate(
        "admin", "a-very-long-test-password", client_ip="10.0.0.2"
    )
    assert created.session_token
