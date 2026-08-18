from __future__ import annotations

import pytest

from src.core.jobs import JobService
from src.core.models import WorkflowDefinitionModel, WorkflowRunModel
from src.worker import DurableWorker


@pytest.mark.asyncio
async def test_worker_processes_only_enabled_verified_workflow(session_factory):
    async with session_factory() as session:
        session.add(
            WorkflowDefinitionModel(
                id="test-workflow",
                display_name="Test",
                is_enabled=True,
                credential_status="verified",
            )
        )
        await session.commit()

    jobs = JobService(session_factory=session_factory)
    queued = await jobs.enqueue(
        workflow_id="test-workflow",
        job_type="test-job",
        payload={"value": 4},
        idempotency_key="worker:test:1",
    )
    worker = DurableWorker(worker_id="test-worker", job_service=jobs)

    async def handler(payload, claim):
        return {"value": payload["value"] * 2, "attempt": claim.attempts}

    worker.register("test-job", handler)
    assert await worker.run_once() is True

    async with session_factory() as session:
        saved = await session.get(WorkflowRunModel, queued.id)
        assert saved.status == "completed"
        assert saved.result == {"value": 8, "attempt": 1}


@pytest.mark.asyncio
async def test_worker_policy_gate_does_not_consume_retry(session_factory):
    async with session_factory() as session:
        session.add(
            WorkflowDefinitionModel(
                id="paused-workflow",
                display_name="Paused",
                is_enabled=True,
                is_paused=True,
                credential_status="verified",
            )
        )
        await session.commit()

    jobs = JobService(session_factory=session_factory)
    queued = await jobs.enqueue(
        workflow_id="paused-workflow",
        job_type="test-job",
        payload={},
        idempotency_key="worker:paused:1",
    )
    worker = DurableWorker(worker_id="test-worker", job_service=jobs)
    worker.register("test-job", lambda payload, claim: {"unexpected": True})
    assert await worker.run_once() is True

    async with session_factory() as session:
        saved = await session.get(WorkflowRunModel, queued.id)
        assert saved.status == "queued"
        assert saved.attempts == 0
