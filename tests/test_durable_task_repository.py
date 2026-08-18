from __future__ import annotations

import pytest
from sqlalchemy import select

from src.core.jobs import JobService
from src.core.models import ApprovalModel, ExternalItemModel, KillSwitchModel
from src.core.repositories import DurableTaskRepository
from src.core.workflow_contracts import (
    DuplicateExternalItem, PublicationPolicy, WorkflowTask, WorkflowTaskStatus,
)


def _task(task_id: str) -> WorkflowTask:
    return WorkflowTask(
        task_id=task_id,
        workflow="reddit_prospector",
        source="reddit",
        external_id="post-42",
        council="sales",
        status=WorkflowTaskStatus.AWAITING_APPROVAL,
        task_description="Draft a reply",
        final_output="A useful draft",
        structured_output={"reply": "A useful draft"},
        confidence_score=91,
        iterations=2,
        total_cost_usd=0.01,
        cost_metrics_complete=True,
        publication_policy=PublicationPolicy.MANUAL_ONLY,
    )


@pytest.mark.asyncio
async def test_repository_atomically_stages_task_and_external_dedupe(session_factory):
    repository = DurableTaskRepository(session_factory=session_factory)
    saved = await repository.stage_workflow_task(_task("task-a"))
    assert saved["status"] == "awaiting_approval"
    assert await repository.has_external_item("reddit", "post-42") is True
    async with session_factory() as session:
        result = await session.execute(
            select(ApprovalModel).where(ApprovalModel.resource_id == "task-a")
        )
        approval = result.scalar_one()
        assert approval.status == "awaiting_approval"

    with pytest.raises(DuplicateExternalItem):
        await repository.stage_workflow_task(_task("task-b"))
    assert await repository.get("task-b") is None

    updated = await repository.update(
        "task-a", {"status": "approved"}, expected_version=saved["version"]
    )
    assert updated["status"] == "approved"
    assert updated["version"] == saved["version"] + 1


@pytest.mark.asyncio
async def test_repository_attaches_task_to_job_reserved_external_item(session_factory):
    jobs = JobService(session_factory=session_factory)
    staged = await jobs.stage_external_job(
        source="reddit", external_id="post-42", workflow_id="reddit_prospector",
        job_type="reddit_prospector", payload={}, idempotency_key="reddit:post-42",
    )
    repository = DurableTaskRepository(session_factory=session_factory)
    assert await repository.has_external_item("reddit", "post-42") is False
    await repository.stage_workflow_task(_task("task-from-job"))

    async with session_factory() as session:
        item = await session.get(ExternalItemModel, staged.external_item_id)
        assert item.workflow_run_id == staged.job_id
        assert item.task_id == "task-from-job"


@pytest.mark.asyncio
async def test_repository_durably_dedupes_filtered_items_without_approval(session_factory):
    repository = DurableTaskRepository(session_factory=session_factory)
    assert await repository.record_external_item(
        "reddit", "low-intent", {"reason": "below_threshold", "score": 12}
    ) is True
    assert await repository.record_external_item(
        "reddit", "low-intent", {"reason": "duplicate"}
    ) is False
    assert await repository.has_external_item("reddit", "low-intent") is True

    async with session_factory() as session:
        approval_result = await session.execute(select(ApprovalModel))
        assert approval_result.scalars().all() == []


@pytest.mark.asyncio
async def test_repository_reads_database_kill_switch(session_factory):
    repository = DurableTaskRepository(session_factory=session_factory)
    assert await repository.is_kill_switch_active() is False
    async with session_factory() as session:
        session.add(KillSwitchModel(id=1, is_active=True, toggled_by="test"))
        await session.commit()
    assert await repository.is_kill_switch_active() is True
