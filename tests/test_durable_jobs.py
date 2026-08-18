from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from src.core.jobs import JobLeaseError, JobService, OutboxService
from src.core.models import OutboxEventModel, WorkflowRunModel, utcnow


@pytest.mark.asyncio
async def test_enqueue_claim_complete_and_idempotency(session_factory):
    jobs = JobService(session_factory=session_factory)
    first = await jobs.enqueue(
        workflow_id="reddit", job_type="scan", payload={"page": 1}, idempotency_key="scan:1"
    )
    duplicate = await jobs.enqueue(
        workflow_id="reddit", job_type="scan", payload={"page": 999}, idempotency_key="scan:1"
    )
    assert duplicate.id == first.id
    assert duplicate.payload == {"page": 1}

    claim = await jobs.claim("worker-a")
    assert claim and claim.id == first.id and claim.attempts == 1
    with pytest.raises(JobLeaseError):
        await jobs.complete(first.id, "worker-b", {})
    await jobs.complete(first.id, "worker-a", {"processed": 3})

    async with session_factory() as session:
        saved = await session.get(WorkflowRunModel, first.id)
        assert saved.status == "completed"
        assert saved.result == {"processed": 3}


@pytest.mark.asyncio
async def test_atomic_external_dedup_and_expired_lease_recovery(session_factory):
    jobs = JobService(session_factory=session_factory, lease_duration=timedelta(seconds=30))
    first = await jobs.stage_external_job(
        source="youtube_comment", external_id="comment-1", workflow_id="youtube-comments",
        job_type="draft_reply", payload={"body": "hello"}, idempotency_key="yt:comment-1",
    )
    duplicate = await jobs.stage_external_job(
        source="youtube_comment", external_id="comment-1", workflow_id="youtube-comments",
        job_type="draft_reply", payload={"body": "changed"}, idempotency_key="yt:comment-1:other",
    )
    assert first.created is True
    assert duplicate.created is False
    assert duplicate.job_id == first.job_id

    claim = await jobs.claim("worker-crashed")
    async with session_factory() as session:
        result = await session.execute(
            select(WorkflowRunModel).where(WorkflowRunModel.id == claim.id)
        )
        row = result.scalar_one()
        row.leased_until = utcnow() - timedelta(seconds=1)
        await session.commit()

    recovered = await jobs.claim("worker-recovery")
    assert recovered and recovered.id == claim.id
    assert recovered.attempts == 2


@pytest.mark.asyncio
async def test_retry_dead_letter_and_outbox(session_factory):
    jobs = JobService(
        session_factory=session_factory,
        retry_base=timedelta(seconds=0),
        retry_cap=timedelta(seconds=0),
    )
    job = await jobs.enqueue(
        workflow_id="content", job_type="publish", payload={},
        idempotency_key="publish:1", max_attempts=2,
    )
    first = await jobs.claim("worker")
    assert await jobs.fail(first.id, "worker", "temporary") == "retry"
    second = await jobs.claim("worker")
    assert await jobs.fail(second.id, "worker", "permanent") == "dead_letter"

    outbox = OutboxService(session_factory=session_factory)
    event = await outbox.enqueue(topic="telegram.alert", payload={"job_id": job.id}, idempotency_key="alert:1")
    duplicate = await outbox.enqueue(topic="telegram.alert", payload={}, idempotency_key="alert:1")
    assert duplicate.id == event.id
    claimed = await outbox.claim("notifier")
    await outbox.mark_published(claimed.id, "notifier")


@pytest.mark.asyncio
async def test_expired_final_lease_is_not_replayed(session_factory):
    jobs = JobService(session_factory=session_factory, lease_duration=timedelta(seconds=1))
    job = await jobs.enqueue(
        workflow_id="youtube-comments",
        job_type="publish.youtube_comment",
        payload={},
        idempotency_key="external-write:one-shot",
        max_attempts=1,
    )
    assert await jobs.claim("crashed-worker")
    async with session_factory() as session:
        saved = await session.get(WorkflowRunModel, job.id)
        saved.leased_until = utcnow() - timedelta(seconds=1)
        await session.commit()

    assert await jobs.claim("replacement-worker") is None
    async with session_factory() as session:
        saved = await session.get(WorkflowRunModel, job.id)
        assert saved.status == "dead_letter"
        assert saved.attempts == 1

    outbox = OutboxService(
        session_factory=session_factory, lease_duration=timedelta(seconds=1)
    )
    event = await outbox.enqueue(
        topic="telegram.publish_success",
        payload={},
        idempotency_key="outbox:one-shot",
        max_attempts=1,
    )
    assert await outbox.claim("crashed-notifier")
    async with session_factory() as session:
        saved_event = await session.get(OutboxEventModel, event.id)
        saved_event.leased_until = utcnow() - timedelta(seconds=1)
        await session.commit()
    assert await outbox.claim("replacement-notifier") is None
    async with session_factory() as session:
        saved_event = await session.get(OutboxEventModel, event.id)
        assert saved_event.status == "dead_letter"
        assert saved_event.attempts == 1
