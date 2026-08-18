from __future__ import annotations

import pytest

from src.core.approvals import ApprovalConflict, ApprovalInvalidAction, ApprovalService
from src.core.models import AuditEventModel, TaskModel
from sqlalchemy import select


@pytest.mark.asyncio
async def test_telegram_service_actor_and_idempotent_replay(session_factory):
    async with session_factory() as session:
        session.add(TaskModel(task_id="task-1", council="sales", status="awaiting_approval"))
        await session.commit()

    approvals = ApprovalService(session_factory=session_factory)
    pending = await approvals.create_pending("task", "task-1")
    result = await approvals.act(
        pending.id,
        action="approve",
        expected_version=1,
        idempotency_key="telegram:update:100",
        actor_user_id=None,
        actor_type="service",
        actor_id="telegram:admin-chat",
    )
    replay = await approvals.act(
        pending.id,
        action="approve",
        expected_version=1,
        idempotency_key="telegram:update:100",
        actor_user_id=None,
        actor_type="service",
        actor_id="telegram:admin-chat",
    )
    assert result.resource["status"] == "approved"
    assert replay.replayed is True
    assert replay.audit_event_id == result.audit_event_id

    async with session_factory() as session:
        task = await session.get(TaskModel, "task-1")
        assert task.status == "approved"
        audit = await session.execute(
            select(AuditEventModel).where(AuditEventModel.id == result.audit_event_id)
        )
        assert audit.scalar_one().actor_type == "service"


@pytest.mark.asyncio
async def test_stale_version_and_invalid_terminal_transition_are_rejected(session_factory):
    async with session_factory() as session:
        session.add(TaskModel(task_id="task-2", council="grant", status="awaiting_approval"))
        await session.commit()
    approvals = ApprovalService(session_factory=session_factory)
    pending = await approvals.create_pending("task", "task-2")

    with pytest.raises(ApprovalConflict):
        await approvals.act(
            pending.id, action="approve", expected_version=99,
            idempotency_key="browser:stale", actor_type="user", actor_id="admin",
        )

    await approvals.act(
        pending.id, action="reject", expected_version=1,
        idempotency_key="browser:reject", actor_type="user", actor_id="admin",
    )
    with pytest.raises(ApprovalInvalidAction):
        await approvals.act(
            pending.id, action="approve", expected_version=2,
            idempotency_key="browser:approve-after-reject", actor_type="user", actor_id="admin",
        )
