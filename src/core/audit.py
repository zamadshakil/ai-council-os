"""Append-only audit helpers."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import AuditEventModel


async def record_audit(
    session: AsyncSession,
    *,
    action: str,
    resource_type: str,
    resource_id: str,
    actor_type: str = "system",
    actor_id: str = "",
    details: dict | None = None,
    request_id: str = "",
) -> AuditEventModel:
    """Append an event inside the caller's transaction; never commits itself."""
    event = AuditEventModel(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_type=actor_type,
        actor_id=actor_id,
        details=details or {},
        request_id=request_id,
    )
    session.add(event)
    await session.flush()
    return event
