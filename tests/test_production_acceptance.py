"""Focused production acceptance tests for durable, approval-gated behavior.

These tests deliberately use the isolated SQLite fixture and replace every
external write with a local failure stub.  They are regression tests for the
cross-module guarantees that matter most in production.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from src.api import server
from src.core.approvals import ApprovalService
from src.core.jobs import JobService, OutboxService
from src.core.models import (
    ApprovalModel,
    CouncilRunModel,
    OutboxEventModel,
    PublicationAttemptModel,
    TaskModel,
    WorkflowDefinitionModel,
    WorkflowRunModel,
)
from src.worker import DurableWorker
from src.workflows.config.reddit_config import SUBREDDITS


@pytest.mark.asyncio
async def test_durable_claims_highest_priority_job_first(session_factory):
    jobs = JobService(session_factory=session_factory)
    low = await jobs.enqueue(
        workflow_id="content_engine",
        job_type="workflow.content_engine",
        payload={"label": "low"},
        idempotency_key="acceptance:priority:low",
        priority=0,
    )
    high = await jobs.enqueue(
        workflow_id="content_engine",
        job_type="workflow.content_engine",
        payload={"label": "high"},
        idempotency_key="acceptance:priority:high",
        priority=100,
    )

    first = await jobs.claim("priority-worker")

    assert first is not None
    assert first.id == high.id
    assert first.payload == {"label": "high"}
    await jobs.complete(first.id, "priority-worker", {"ok": True})

    second = await jobs.claim("priority-worker")
    assert second is not None
    assert second.id == low.id


@pytest.mark.asyncio
async def test_retry_creates_one_fresh_run_and_job_on_same_task(
    session_factory, monkeypatch
):
    monkeypatch.setattr(server, "async_session", session_factory)
    approvals = ApprovalService(session_factory=session_factory)

    async with session_factory() as session:
        task = TaskModel(
            task_id="retry-task",
            council="grant",
            status="awaiting_approval",
            task_description="Draft an EU grant impact section",
            final_output="Original draft",
            confidence_score=86,
            iterations=3,
            context={"run_id": "original-run", "priority": "high"},
        )
        original_run = CouncilRunModel(
            id="original-run",
            task_id=task.task_id,
            council="grant",
            status="needs_manual_review",
            priority="high",
            prompt=task.task_description,
            context={"run_id": "original-run", "priority": "high"},
            final_output={"content": "Original draft"},
        )
        approval = ApprovalModel(
            id="retry-approval",
            resource_type="task",
            resource_id=task.task_id,
            status="awaiting_approval",
            version=1,
        )
        session.add_all([task, original_run, approval])
        await session.commit()

    result = await approvals.act(
        "retry-approval",
        action="retry",
        expected_version=1,
        idempotency_key="acceptance:retry:one",
        actor_type="user",
        actor_id="admin",
    )
    async with session_factory() as session:
        current_task = await session.get(TaskModel, "retry-task")
        current_approval = await session.get(ApprovalModel, "retry-approval")
    assert current_task is not None and current_approval is not None
    await server._queue_after_approval(current_task, current_approval, "retry")

    replay = await approvals.act(
        "retry-approval",
        action="retry",
        expected_version=1,
        idempotency_key="acceptance:retry:one",
        actor_type="user",
        actor_id="admin",
    )
    async with session_factory() as session:
        replay_task = await session.get(TaskModel, "retry-task")
        replay_approval = await session.get(ApprovalModel, "retry-approval")
    assert replay_task is not None and replay_approval is not None
    await server._queue_after_approval(replay_task, replay_approval, "retry")

    assert result.replayed is False
    assert replay.replayed is True
    async with session_factory() as session:
        runs = (
            await session.execute(
                select(CouncilRunModel)
                .where(CouncilRunModel.task_id == "retry-task")
                .order_by(CouncilRunModel.created_at)
            )
        ).scalars().all()
        jobs = (
            await session.execute(
                select(WorkflowRunModel).where(
                    WorkflowRunModel.idempotency_key
                    == "retry:retry-approval:2"
                )
            )
        ).scalars().all()
        saved_task = await session.get(TaskModel, "retry-task")

    assert len(runs) == 2
    fresh_run = next(run for run in runs if run.id != "original-run")
    assert fresh_run.task_id == "retry-task"
    assert fresh_run.status == "queued"
    assert len(jobs) == 1
    assert jobs[0].payload["task_id"] == "retry-task"
    assert jobs[0].payload["run_id"] == fresh_run.id
    assert jobs[0].priority == 10
    assert saved_task is not None
    assert saved_task.context["run_id"] == fresh_run.id
    assert saved_task.context["retry_of_run_id"] == "original-run"


@pytest.mark.asyncio
async def test_duplicate_approve_stages_only_one_publication_attempt_and_job(
    session_factory, monkeypatch
):
    monkeypatch.setattr(server, "async_session", session_factory)
    approvals = ApprovalService(session_factory=session_factory)

    async with session_factory() as session:
        session.add_all(
            [
                TaskModel(
                    task_id="publish-task",
                    council="content",
                    status="awaiting_approval",
                    task_description="Reply to a YouTube comment",
                    final_output="Thanks for your question.",
                    context={
                        "workflow": "youtube_comments",
                        "comment_id": "comment-123",
                    },
                ),
                ApprovalModel(
                    id="publish-approval",
                    resource_type="task",
                    resource_id="publish-task",
                    status="awaiting_approval",
                    version=1,
                ),
            ]
        )
        await session.commit()

    result = await approvals.act(
        "publish-approval",
        action="approve",
        expected_version=1,
        idempotency_key="acceptance:approve:one",
        actor_type="user",
        actor_id="admin",
    )
    async with session_factory() as session:
        task = await session.get(TaskModel, "publish-task")
        approval = await session.get(ApprovalModel, "publish-approval")
    assert task is not None and approval is not None
    await server._queue_after_approval(task, approval, "approve")

    replay = await approvals.act(
        "publish-approval",
        action="approve",
        expected_version=1,
        idempotency_key="acceptance:approve:one",
        actor_type="user",
        actor_id="admin",
    )
    async with session_factory() as session:
        replay_task = await session.get(TaskModel, "publish-task")
        replay_approval = await session.get(ApprovalModel, "publish-approval")
    assert replay_task is not None and replay_approval is not None
    await server._queue_after_approval(replay_task, replay_approval, "approve")
    await server._queue_after_approval(replay_task, replay_approval, "approve")

    assert result.replayed is False
    assert replay.replayed is True
    async with session_factory() as session:
        attempt_count = await session.scalar(
            select(func.count(PublicationAttemptModel.id)).where(
                PublicationAttemptModel.approval_id == "publish-approval"
            )
        )
        jobs = (
            await session.execute(
                select(WorkflowRunModel).where(
                    WorkflowRunModel.idempotency_key
                    == "publish:publish-approval:2"
                )
            )
        ).scalars().all()
        attempts = (
            await session.execute(
                select(PublicationAttemptModel).where(
                    PublicationAttemptModel.approval_id == "publish-approval"
                )
            )
        ).scalars().all()

    assert attempt_count == 1
    assert len(attempts) == 1
    assert len(jobs) == 1
    assert jobs[0].payload["publication_attempt_id"] == attempts[0].id
    assert jobs[0].job_type == "publish.youtube_comment"
    assert jobs[0].max_attempts == 1


@pytest.mark.asyncio
async def test_worker_publication_failure_requires_manual_reconciliation(
    session_factory, monkeypatch
):
    def reject_external_write(comment_id: str, content: str):
        raise RuntimeError(f"simulated YouTube outage for {comment_id}: {content}")

    monkeypatch.setattr(
        "src.integrations.youtube.post_comment_reply", reject_external_write
    )

    async with session_factory() as session:
        task = TaskModel(
            task_id="failed-publish-task",
            council="content",
            status="approved",
            task_description="Approved YouTube reply",
            final_output="Approved response",
            context={"workflow": "youtube_comments", "comment_id": "comment-fail"},
        )
        approval = ApprovalModel(
            id="failed-publish-approval",
            resource_type="task",
            resource_id=task.task_id,
            status="approved",
            action="approve",
            version=2,
        )
        attempt = PublicationAttemptModel(
            id="failed-publication-attempt",
            approval_id=approval.id,
            platform="youtube",
            status="queued",
            idempotency_key="publish:failed-publish-approval:2",
            request_payload={"task_id": task.task_id},
        )
        session.add_all(
            [
                WorkflowDefinitionModel(
                    id="youtube_comments",
                    display_name="YouTube Comment Replies",
                    is_enabled=True,
                    credential_status="verified",
                ),
                task,
                approval,
                attempt,
            ]
        )
        await session.commit()

    jobs = JobService(session_factory=session_factory)
    queued = await jobs.enqueue(
        workflow_id="youtube_comments",
        job_type="publish.youtube_comment",
        payload={
            "task_id": "failed-publish-task",
            "approval_id": "failed-publish-approval",
            "publication_attempt_id": "failed-publication-attempt",
            "platform": "youtube",
            "content": "Approved response",
            "context": {"workflow": "youtube_comments", "comment_id": "comment-fail"},
        },
        idempotency_key="publish:failed-publish-approval:2",
        max_attempts=1,
    )
    worker = DurableWorker(
        worker_id="publication-failure-worker",
        job_service=jobs,
        outbox_service=OutboxService(session_factory=session_factory),
    )
    worker.register("publish.youtube_comment", worker._publish_youtube_comment)

    assert await worker.run_once() is True

    async with session_factory() as session:
        saved_task = await session.get(TaskModel, "failed-publish-task")
        saved_attempt = await session.get(
            PublicationAttemptModel, "failed-publication-attempt"
        )
        saved_job = await session.get(WorkflowRunModel, queued.id)
        error_events = (
            await session.execute(
                select(OutboxEventModel).where(
                    OutboxEventModel.idempotency_key
                    == "telegram:publication-failed:failed-publication-attempt"
                )
            )
        ).scalars().all()

    assert saved_task is not None and saved_attempt is not None
    assert saved_job is not None
    assert saved_task.status == "needs_manual_review"
    assert saved_task.context["publication_state"] == "reconciliation_required"
    assert saved_task.context["publication_retry_allowed"] is False
    assert saved_attempt.status == "reconciliation_required"
    assert "simulated YouTube outage" in saved_task.error
    assert "simulated YouTube outage" in saved_attempt.error
    assert saved_job.status == "dead_letter"
    assert saved_job.attempts == 1
    assert len(error_events) == 1


def test_reddit_prospector_has_exactly_45_unique_configured_sources():
    normalized = [name.strip().casefold() for name in SUBREDDITS]

    assert len(SUBREDDITS) == 45
    assert len(set(normalized)) == 45
    assert all(name and "/" not in name and not name.startswith("r/") for name in normalized)
