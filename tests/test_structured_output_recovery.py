from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel, Field

from src.core import llm_router
from src.core.jobs import JobClaim, JobService, OutboxService
from src.core.models import ApprovalModel, CouncilRunModel, TaskModel, utcnow
from src.worker import DurableWorker


class TinyOutput(BaseModel):
    title: str
    code: str = Field(max_length=3)


def completion(content: str, *, prompt: int, output: int, cost: float, request_id: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=prompt,
            completion_tokens=output,
            cost=cost,
        ),
        model="google/gemini-3.7-flash",
        id=request_id,
    )


@pytest.mark.asyncio
async def test_structured_call_repairs_once_and_accounts_for_both_calls(monkeypatch):
    responses = iter(
        [
            completion(
                '{"title":"Useful","code":"TOO-LONG"}',
                prompt=10,
                output=4,
                cost=0.001,
                request_id="initial",
            ),
            completion(
                '{"title":"Useful","code":"OK"}',
                prompt=18,
                output=3,
                cost=0.002,
                request_id="repair",
            ),
        ]
    )
    calls: list[dict] = []

    async def fake_completion(**kwargs):
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr(llm_router, "_create_completion", fake_completion)

    parsed, metrics = await llm_router.call_llm_structured(
        messages=[{"role": "user", "content": "Create it"}],
        model_id="google/gemini-3.7-flash",
        output_model=TinyOutput,
    )

    assert parsed == TinyOutput(title="Useful", code="OK")
    assert len(calls) == 2
    assert calls[1]["temperature"] == 0.0
    assert metrics["schema_repair_attempted"] is True
    assert metrics["input_tokens"] == 28
    assert metrics["output_tokens"] == 7
    assert metrics["cost_usd"] == 0.003
    assert metrics["provider_request_id"] == "repair"


@pytest.mark.asyncio
async def test_structured_call_stops_after_one_invalid_repair(monkeypatch):
    responses = iter(
        [
            completion("not-json", prompt=3, output=1, cost=0.001, request_id="initial"),
            completion("still-not-json", prompt=6, output=1, cost=0.001, request_id="repair"),
        ]
    )
    calls = 0

    async def fake_completion(**_kwargs):
        nonlocal calls
        calls += 1
        return next(responses)

    monkeypatch.setattr(llm_router, "_create_completion", fake_completion)

    with pytest.raises(llm_router.StructuredOutputError, match="bounded repair attempt"):
        await llm_router.call_llm_structured(
            messages=[{"role": "user", "content": "Create it"}],
            model_id="google/gemini-3.7-flash",
            output_model=TinyOutput,
        )

    assert calls == 2


@pytest.mark.asyncio
async def test_worker_recovers_latest_valid_draft_for_manual_review(
    session_factory, monkeypatch
):
    async with session_factory() as session:
        session.add(
            TaskModel(
                task_id="recoverable-task",
                council="content",
                status="queued",
                task_description="Create six platform posts",
                context={
                    "run_id": "recoverable-run",
                    "latest_valid_draft": '{"twitter":"Ready"}',
                    "latest_valid_structured_output": {"twitter": "Ready"},
                },
            )
        )
        await session.flush()
        session.add_all(
            [
                CouncilRunModel(
                    id="recoverable-run",
                    task_id="recoverable-task",
                    council="content",
                    status="queued",
                    prompt="Create six platform posts",
                    context={},
                ),
                ApprovalModel(
                    id="recoverable-approval",
                    resource_type="task",
                    resource_id="recoverable-task",
                    status="failed",
                    version=2,
                ),
            ]
        )
        await session.commit()

    async def fail_after_progress(*_args, **_kwargs):
        raise llm_router.StructuredOutputError("later revision failed validation")

    monkeypatch.setattr("src.councils.run_council", fail_after_progress)
    worker = DurableWorker(
        job_service=JobService(session_factory=session_factory),
        outbox_service=OutboxService(session_factory=session_factory),
    )
    claim = JobClaim(
        id="recoverable-job",
        workflow_id="content_council",
        job_type="council.run",
        payload={},
        priority=0,
        attempts=1,
        max_attempts=3,
        lease_owner="worker",
        leased_until=utcnow(),
    )

    result = await worker._run_council(
        {
            "task_id": "recoverable-task",
            "run_id": "recoverable-run",
            "council": "content",
            "task_description": "Create six platform posts",
        },
        claim,
    )

    assert result["recovered_last_valid_draft"] is True
    async with session_factory() as session:
        task = await session.get(TaskModel, "recoverable-task")
        run = await session.get(CouncilRunModel, "recoverable-run")
        approval = await session.get(ApprovalModel, "recoverable-approval")

    assert task is not None and run is not None and approval is not None
    assert task.status == "needs_manual_review"
    assert task.final_output == '{"twitter":"Ready"}'
    assert task.context["recovered_after_validation_failure"] is True
    assert run.status == "needs_manual_review"
    assert approval.status == "awaiting_approval"
