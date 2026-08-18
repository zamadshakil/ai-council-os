"""Durable scheduler, council executor, publisher, and outbox worker."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import hmac
import json
import logging
import os
import socket
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from src.core import database as db
from src.core.audit import record_audit
from src.core.jobs import JobClaim, JobService, OutboxClaim, OutboxService
from src.core.integration_context import use_integration_configuration
from src.core.integration_credentials import (
    WORKFLOW_REQUIRED_ENV,
    workflow_credential_fingerprint,
)
from src.core.integration_models import WorkflowIntegrationModel
from src.core.integration_vault import (
    VaultConfigurationError,
    decrypted_provider_env,
    workflow_environment,
    workflow_connections_verified,
)
from src.core.models import (
    ApprovalModel,
    CouncilRunModel,
    CouncilStepModel,
    KillSwitchModel,
    OutboxEventModel,
    PublicationAttemptModel,
    TaskModel,
    WorkflowDefinitionModel,
    WorkflowRunModel,
    utcnow,
)
from src.core.repositories import DurableTaskRepository

logger = logging.getLogger("council.worker")
JobHandler = Callable[[dict[str, Any], JobClaim], dict[str, Any] | Awaitable[dict[str, Any]]]

WORKFLOW_HANDLERS = {
    "workflow.youtube_comments": "youtube_comments",
    "workflow.reddit_prospector": "reddit_prospector",
    "workflow.youtube_descriptions": "youtube_descriptions",
    "workflow.content_engine": "content_engine",
    "workflow.instagram_comments": "instagram_comments",
}


class DurableWorker:
    def __init__(
        self,
        *,
        worker_id: str | None = None,
        job_service: JobService | None = None,
        outbox_service: OutboxService | None = None,
        poll_interval: float = 2.0,
        task_repository: DurableTaskRepository | None = None,
    ) -> None:
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.jobs = job_service or JobService()
        self.outbox = outbox_service or OutboxService()
        self.poll_interval = max(0.1, poll_interval)
        self.task_repository = task_repository or DurableTaskRepository()
        self.handlers: dict[str, JobHandler] = {}
        self._stopping = asyncio.Event()
        self._last_schedule_check = 0.0
        self._last_reconcile_check = 0.0
        self._telegram_started = False

    def register(self, job_type: str, handler: JobHandler) -> None:
        if not job_type or job_type in self.handlers:
            raise ValueError(f"Job handler is empty or already registered: {job_type!r}")
        self.handlers[job_type] = handler

    def register_production_handlers(self) -> None:
        from src.workflows.registry import run_workflow_job

        for job_type, registry_name in WORKFLOW_HANDLERS.items():
            async def workflow_handler(
                payload: dict[str, Any], claim: JobClaim, *, _name: str = registry_name
            ) -> dict[str, Any]:
                return await run_workflow_job(_name, payload, self.task_repository)

            self.register(job_type, workflow_handler)

        self.register("council.run", self._run_council)
        self.register("publish.youtube_comment", self._publish_youtube_comment)
        self.register("publish.youtube_description", self._publish_youtube_description)
        self.register("publish.social", self._publish_social)
        self.register("publish.instagram_comment", self._publish_instagram_comment)
        self.register("blender.template_repair", self._run_blender_template_job)
        for provider in ("telegram", "youtube", "meta"):
            self.register(f"webhook.{provider}", self._accept_webhook)

    async def run_once(self) -> bool:
        await self._ensure_telegram_control()
        await self._reconcile_abandoned_publications()
        await self._enqueue_due_schedules()
        claim = await self.jobs.claim(self.worker_id)
        if claim:
            await self._execute_claim(claim)
            return True
        outbox_claim = await self.outbox.claim(self.worker_id)
        if outbox_claim:
            await self._execute_outbox(outbox_claim)
            return True
        return False

    async def _execute_claim(self, claim: JobClaim) -> None:
        allowed, reason = await self._execution_allowed(claim)
        if not allowed:
            logger.info("Releasing job %s: %s", claim.id, reason)
            await self.jobs.release(claim.id, self.worker_id, timedelta(minutes=1))
            return
        handler = self.handlers.get(claim.job_type)
        if not handler:
            await self.jobs.fail(claim.id, self.worker_id, f"No handler registered for {claim.job_type!r}")
            return

        heartbeat = asyncio.create_task(self._heartbeat_loop(claim))
        try:
            configuration = await self._claim_integration_environment(claim)
            with use_integration_configuration(configuration):
                result = handler(claim.payload, claim)
                if inspect.isawaitable(result):
                    result = await result
            if not isinstance(result, dict):
                raise TypeError("Job handler must return a dictionary")
            await self.jobs.complete(claim.id, self.worker_id, result)
        except asyncio.CancelledError:
            await self.jobs.release(claim.id, self.worker_id, timedelta(seconds=5))
            raise
        except Exception as exc:
            logger.exception("Job %s failed", claim.id)
            await self.jobs.fail(claim.id, self.worker_id, str(exc))
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def _claim_integration_environment(self, claim: JobClaim) -> dict[str, str]:
        """Resolve verified portal connections without copying secrets into jobs."""
        if not os.getenv("INTEGRATION_ENCRYPTION_KEY", "").strip():
            # Local development and the initial environment-only bootstrap do
            # not require integration-vault tables. Production readiness
            # rejects a missing key before any worker is launched.
            return {}
        try:
            if claim.job_type == "council.run":
                return await decrypted_provider_env("openrouter")
            if claim.job_type == "blender.template_repair":
                return await decrypted_provider_env("runpod")
            configuration = await workflow_environment(claim.workflow_id)
            if claim.job_type.startswith("workflow."):
                try:
                    configuration.update(await workflow_environment("telegram_control"))
                except VaultConfigurationError:
                    pass
            return configuration
        except VaultConfigurationError:
            # Environment credentials remain supported for the initial server
            # bootstrap. If a workflow has portal links, its DB verification
            # gate will already have stopped unverified execution.
            return {}

    async def _heartbeat_loop(self, claim: JobClaim) -> None:
        interval = max(5.0, self.jobs.lease_duration.total_seconds() / 3)
        while True:
            await asyncio.sleep(interval)
            await self.jobs.heartbeat(claim.id, self.worker_id)

    @staticmethod
    async def _credentials_current(session, definition: WorkflowDefinitionModel) -> bool:
        if definition.credential_status != "verified":
            return False
        if definition.id not in WORKFLOW_REQUIRED_ENV:
            return True
        if (
            not os.getenv("INTEGRATION_ENCRYPTION_KEY", "").strip()
            and os.getenv("APP_ENV", "development").lower() not in {"production", "prod", "staging"}
        ):
            return True
        linked = (await session.execute(
            select(WorkflowIntegrationModel.provider).where(
                WorkflowIntegrationModel.workflow_id == definition.id
            )
        )).scalars().first()
        if linked:
            return await workflow_connections_verified(definition.id)
        stored = str((definition.settings or {}).get("credential_fingerprint", ""))
        current = workflow_credential_fingerprint(definition.id)
        return bool(stored and current and hmac.compare_digest(stored, current))

    async def _execute_outbox(self, claim: OutboxClaim) -> None:
        async with self.jobs.sessions() as session:
            definition = await session.get(WorkflowDefinitionModel, "telegram_control")
            switch = await session.get(KillSwitchModel, 1)
            allowed = bool(
                definition
                and definition.is_enabled
                and not definition.is_paused
                and await self._credentials_current(session, definition)
                and not (switch and switch.is_active)
            )
        if not allowed:
            await self.outbox.release(claim.id, self.worker_id, timedelta(minutes=1))
            return
        try:
            configuration = await workflow_environment("telegram_control")
            from src.integrations.telegram_bot import configure_telegram_runtime

            configure_telegram_runtime(configuration)
            with use_integration_configuration(configuration):
                if claim.topic == "telegram.approval":
                    from src.integrations.telegram_bot import send_draft_for_approval

                    await self._assert_write_allowed("telegram_control")
                    await send_draft_for_approval(**claim.payload)
                elif claim.topic == "telegram.publish_success":
                    from src.integrations.telegram_bot import notify_publish_success

                    await self._assert_write_allowed("telegram_control")
                    await notify_publish_success(**claim.payload)
                elif claim.topic == "telegram.error":
                    from src.integrations.telegram_bot import notify_workflow_error

                    await self._assert_write_allowed("telegram_control")
                    await notify_workflow_error(**claim.payload)
                else:
                    raise ValueError(f"Unsupported outbox topic {claim.topic!r}")
            await self.outbox.mark_published(claim.id, self.worker_id)
        except Exception as exc:
            logger.exception("Outbox event %s failed", claim.id)
            await self.outbox.mark_failed(claim.id, self.worker_id, str(exc))

    async def _ensure_telegram_control(self) -> None:
        async with self.jobs.sessions() as session:
            definition = await session.get(WorkflowDefinitionModel, "telegram_control")
            should_run = bool(
                definition
                and definition.is_enabled
                and not definition.is_paused
                and await self._credentials_current(session, definition)
            )
        if should_run and not self._telegram_started:
            try:
                from src.integrations.telegram_bot import (
                    configure_telegram_runtime,
                    start_telegram_bot_async,
                )

                configuration = await workflow_environment("telegram_control")
                configure_telegram_runtime(configuration)
                with use_integration_configuration(configuration):
                    await start_telegram_bot_async()
                self._telegram_started = True
            except Exception:
                logger.exception("Telegram control bot failed to start")
        elif not should_run and self._telegram_started:
            from src.integrations.telegram_bot import stop_telegram_bot_async

            await stop_telegram_bot_async()
            self._telegram_started = False

    async def _execution_allowed(self, claim: JobClaim) -> tuple[bool, str]:
        async with self.jobs.sessions() as session:
            switch = await session.get(KillSwitchModel, 1)
            if switch and switch.is_active and not claim.job_type.startswith("webhook."):
                return False, "global kill switch is active"
            if claim.job_type == "council.run" or claim.job_type.startswith("webhook."):
                return True, ""
            if claim.job_type == "blender.template_repair":
                try:
                    await decrypted_provider_env("runpod")
                except VaultConfigurationError:
                    return False, "RunPod credentials are not verified"
                return True, ""
            definition = await session.get(WorkflowDefinitionModel, claim.workflow_id)
            if not definition:
                return False, "workflow is not configured"
            if not definition.is_enabled:
                return False, "workflow is disabled"
            if definition.is_paused:
                return False, "workflow is paused"
            if not await self._credentials_current(session, definition):
                return False, "workflow credentials are not verified"
            return True, ""

    async def _enqueue_due_schedules(self) -> None:
        now_monotonic = time.monotonic()
        if now_monotonic - self._last_schedule_check < 15:
            return
        self._last_schedule_check = now_monotonic
        now_epoch = int(time.time())
        now_utc = utcnow()
        async with self.jobs.sessions() as session:
            result = await session.execute(
                select(WorkflowDefinitionModel).where(
                    WorkflowDefinitionModel.is_enabled.is_(True),
                    WorkflowDefinitionModel.is_paused.is_(False),
                    WorkflowDefinitionModel.credential_status == "verified",
                )
            )
            definitions = result.scalars().all()
        for definition in definitions:
            async with self.jobs.sessions() as session:
                attached = await session.get(WorkflowDefinitionModel, definition.id)
                if not attached or not await self._credentials_current(session, attached):
                    continue
            schedule = definition.schedule or {}
            schedule_type = schedule.get("type")
            if schedule_type == "interval":
                seconds = max(60, int(schedule.get("seconds", 0) or 0))
                bucket = now_epoch // seconds
            elif schedule_type == "cron":
                from croniter import croniter

                expression = str(schedule.get("expression", ""))
                if not croniter.is_valid(expression) or not croniter.match(expression, now_utc):
                    continue
                # One durable job per UTC cron minute, even with repeated polls.
                bucket = int(now_utc.timestamp()) // 60
            else:
                continue
            job_type = f"workflow.{definition.id}"
            if job_type not in self.handlers:
                continue
            await self.jobs.enqueue(
                workflow_id=definition.id,
                job_type=job_type,
                payload={
                    **{
                        key: value
                        for key, value in (definition.settings or {}).items()
                        if key != "selected_document_hashes"
                    },
                    "scheduled": True,
                    "scheduled_bucket": bucket,
                },
                idempotency_key=f"schedule:{definition.id}:{bucket}",
            )

    async def _run_council(self, payload: dict[str, Any], claim: JobClaim) -> dict[str, Any]:
        from src.councils import run_council

        task_id = str(payload["task_id"])
        run_id = str(payload["run_id"])
        async with self.jobs.sessions() as session:
            task = await session.get(TaskModel, task_id)
            run = await session.get(CouncilRunModel, run_id)
            if not task or not run:
                raise ValueError("Council task or run no longer exists")
            if task.status == "cancelled":
                run.status = "cancelled"
                run.version += 1
                await session.commit()
                return {"task_id": task_id, "run_id": run_id, "status": "cancelled"}
            if task.status in {"awaiting_approval", "needs_manual_review", "approved", "rejected"} and run.final_output:
                return {"task_id": task_id, "run_id": run_id, "status": task.status, "recovered": True}
            task.status = run.status = "running"
            task.version += 1
            run.version += 1
            await session.commit()

        try:
            result = await run_council(
                str(payload["council"]), str(payload["task_description"]),
                context=payload.get("context") or {},
                priority=str(payload.get("priority") or "normal"), task_id=task_id,
            )
        except Exception as exc:
            async with self.jobs.sessions() as session:
                task = await session.get(TaskModel, task_id)
                run = await session.get(CouncilRunModel, run_id)
                approval = (await session.execute(select(ApprovalModel).where(
                    ApprovalModel.resource_type == "task",
                    ApprovalModel.resource_id == task_id,
                ))).scalar_one_or_none()
                if task and task.status != "cancelled":
                    task.status, task.error, task.version = "failed", str(exc)[:8000], task.version + 1
                if run and run.status != "cancelled":
                    run.status, run.error, run.version = "failed", str(exc)[:8000], run.version + 1
                if approval and approval.status != "cancelled":
                    approval.status = "failed"
                    approval.action = ""
                    approval.version += 1
                await session.commit()
            raise

        async with self.jobs.sessions() as session:
            task = await session.get(TaskModel, task_id)
            run = await session.get(CouncilRunModel, run_id)
            assert task is not None and run is not None
            if task.status == "cancelled":
                run.status = "cancelled"
                run.version += 1
                await session.commit()
                return {"task_id": task_id, "run_id": run_id, "status": "cancelled"}
            context = {
                **(task.context or {}),
                "structured_output": result.structured_output,
                "warnings": result.warnings,
                "cost_metrics_complete": result.cost_metrics_complete,
                "input_tokens": result.total_input_tokens,
                "output_tokens": result.total_output_tokens,
            }
            task.status = result.status.value
            task.final_output = result.final_output
            task.confidence_score = result.confidence_score
            task.iterations = result.draft_count
            task.total_cost_usd = result.total_cost_usd
            task.debate_history = result.debate_history
            task.context = context
            task.error = result.error
            task.version += 1
            task.updated_at = utcnow()

            run.status = result.status.value
            run.final_output = {"content": result.final_output, "structured_output": result.structured_output}
            run.confidence_score = result.confidence_score
            run.total_input_tokens = result.total_input_tokens
            run.total_output_tokens = result.total_output_tokens
            run.total_cost_usd = result.total_cost_usd
            run.warning = "\n".join(result.warnings)
            run.error = result.error
            run.version += 1
            run.updated_at = utcnow()

            existing_steps = (await session.execute(
                select(CouncilStepModel).where(CouncilStepModel.run_id == run_id)
            )).scalars().all()
            if not existing_steps:
                for sequence, message in enumerate(result.debate_history, start=1):
                    structured = message.get("structured_output") or {}
                    session.add(CouncilStepModel(
                        run_id=run_id,
                        sequence=sequence,
                        role=str(message.get("role", "")),
                        model_id=str(message.get("model_used", "")),
                        prompt=json.dumps(message.get("prompt_messages") or [], ensure_ascii=False),
                        output={"content": message.get("content", ""), "structured_output": structured},
                        score_breakdown=structured.get("category_scores") or {},
                        input_tokens=int(message.get("input_tokens") or 0),
                        output_tokens=int(message.get("output_tokens") or 0),
                        cost_usd=float(message.get("cost_usd") or 0.0),
                    ))

            approval_result = await session.execute(select(ApprovalModel).where(
                ApprovalModel.resource_type == "task", ApprovalModel.resource_id == task_id,
            ))
            approval = approval_result.scalar_one_or_none()
            if approval is None:
                approval = ApprovalModel(
                    resource_type="task", resource_id=task_id,
                    status="awaiting_approval", version=1,
                )
                session.add(approval)
                await session.flush()
            elif (
                approval.status != "awaiting_approval"
                or approval.action
                or approval.decided_at is not None
            ):
                # A transient council failure can move the durable job into an
                # automatic retry while leaving its approval in ``failed``.
                # A successful retry produces a new draft, so the same approval
                # resource must become a fresh, undecided approval with a new
                # optimistic version before the operator can approve/reject it.
                approval.status = "awaiting_approval"
                approval.action = ""
                approval.actor_user_id = None
                approval.notes = ""
                approval.edited_output = {}
                approval.decided_at = None
                approval.version += 1
                approval.updated_at = utcnow()
            approval_version = approval.version
            outbox_result = await session.execute(select(OutboxEventModel).where(
                OutboxEventModel.idempotency_key
                == f"telegram:approval:{task_id}:v{approval_version}"
            ))
            if outbox_result.scalar_one_or_none() is None:
                session.add(OutboxEventModel(
                    topic="telegram.approval",
                    payload={"task_id": task_id,
                             "workflow_name": f"{result.council.title()} Council",
                             "draft_text": result.final_output,
                             "context_summary": task.task_description,
                             "confidence": result.confidence_score,
                             "council": result.council},
                    idempotency_key=f"telegram:approval:{task_id}:v{approval_version}",
                ))
            await record_audit(
                session, action="council_run.completed", resource_type="task", resource_id=task_id,
                details={"run_id": run_id, "status": result.status.value,
                         "draft_count": result.draft_count,
                         "cost_metrics_complete": result.cost_metrics_complete},
            )
            await session.commit()
        return {"task_id": task_id, "run_id": run_id, "status": result.status.value,
                "confidence_score": result.confidence_score, "draft_count": result.draft_count}

    async def _assert_write_allowed(self, workflow_id: str) -> None:
        async with self.jobs.sessions() as session:
            switch = await session.get(KillSwitchModel, 1)
            definition = await session.get(WorkflowDefinitionModel, workflow_id)
            if switch and switch.is_active:
                raise RuntimeError("Global kill switch activated before external write")
            if not definition or not definition.is_enabled or definition.is_paused:
                raise RuntimeError("Workflow disabled or paused before external write")
            if not await self._credentials_current(session, definition):
                raise RuntimeError("Workflow credentials are not verified")

    async def _begin_publication(self, payload: dict[str, Any], workflow_id: str) -> None:
        await self._assert_write_allowed(workflow_id)
        async with self.jobs.sessions() as session:
            task = await session.get(TaskModel, payload["task_id"])
            attempt = await session.get(PublicationAttemptModel, payload["publication_attempt_id"])
            if not task or not attempt:
                raise ValueError("Publication task or attempt does not exist")
            if attempt.status == "published":
                return
            task.status = "publishing"
            task.version += 1
            attempt.status = "publishing"
            await session.commit()

    async def _finish_publication(
        self, payload: dict[str, Any], response: dict[str, Any], external_id: str = ""
    ) -> dict[str, Any]:
        async with self.jobs.sessions() as session:
            task = await session.get(TaskModel, payload["task_id"])
            attempt = await session.get(PublicationAttemptModel, payload["publication_attempt_id"])
            assert task is not None and attempt is not None
            task.status = "published"
            task.version += 1
            attempt.status = "published"
            attempt.response_payload = response
            attempt.external_id = external_id
            session.add(OutboxEventModel(
                topic="telegram.publish_success",
                payload={"workflow_name": (task.context or {}).get("workflow", "Publishing"),
                         "platform": payload.get("platform", ""),
                         "details": f"Task: {task.task_id}"},
                idempotency_key=f"telegram:published:{attempt.id}",
            ))
            await record_audit(
                session, action="publication.succeeded", resource_type="task",
                resource_id=task.task_id,
                details={"platform": payload.get("platform", ""), "attempt_id": attempt.id},
            )
            await session.commit()
        return {"task_id": payload["task_id"], "status": "published", "external_id": external_id}

    async def _fail_publication(self, payload: dict[str, Any], error: Exception) -> None:
        """Persist a terminal reconciliation state for an ambiguous provider write.

        These jobs deliberately have one attempt because the supported provider
        APIs do not offer a portable idempotency key.  A timeout or worker crash
        may therefore mean that the provider accepted the write even though the
        application did not receive confirmation.  The state must never expose
        the generic council ``Retry`` action, which could duplicate a post.
        """
        async with self.jobs.sessions() as session:
            task = await session.get(TaskModel, payload["task_id"])
            attempt = await session.get(
                PublicationAttemptModel, payload["publication_attempt_id"]
            )
            message = str(error)[:8000]
            if task:
                context = dict(task.context or {})
                context.update({
                    "publication_state": "reconciliation_required",
                    "publication_attempt_id": payload["publication_attempt_id"],
                    "publication_retry_allowed": False,
                })
                task.context = context
                task.status = "needs_manual_review"
                task.error = message
                task.version += 1
            if attempt:
                attempt.status = "reconciliation_required"
                attempt.error = message
            if task and attempt:
                outbox_key = f"telegram:publication-failed:{attempt.id}"
                existing_outbox = (await session.execute(
                    select(OutboxEventModel).where(
                        OutboxEventModel.idempotency_key == outbox_key
                    )
                )).scalar_one_or_none()
                if existing_outbox is None:
                    session.add(OutboxEventModel(
                        topic="telegram.error",
                        payload={
                            "workflow_name": (task.context or {}).get("workflow", "Publishing"),
                            "error": message,
                        },
                        idempotency_key=outbox_key,
                    ))
                await record_audit(
                    session,
                    action="publication.reconciliation_required",
                    resource_type="task",
                    resource_id=task.task_id,
                    details={"attempt_id": attempt.id, "error": message},
                )
            await session.commit()

    async def _reconcile_abandoned_publications(self) -> None:
        """Make a crashed one-shot write visible without risking a duplicate post."""
        now_monotonic = time.monotonic()
        if now_monotonic - self._last_reconcile_check < 30:
            return
        self._last_reconcile_check = now_monotonic
        candidates: list[dict[str, Any]] = []
        async with self.jobs.sessions() as session:
            jobs = (await session.execute(
                select(WorkflowRunModel)
                .where(
                    WorkflowRunModel.status == "dead_letter",
                    WorkflowRunModel.job_type.in_((
                        "publish.youtube_comment",
                        "publish.youtube_description",
                        "publish.social",
                        "publish.instagram_comment",
                    )),
                )
                .order_by(WorkflowRunModel.finished_at.desc())
                .limit(100)
            )).scalars().all()
            for job in jobs:
                payload = job.payload or {}
                attempt_id = payload.get("publication_attempt_id")
                if not attempt_id:
                    continue
                attempt = await session.get(PublicationAttemptModel, attempt_id)
                if attempt and attempt.status == "publishing":
                    candidates.append(payload)
        for payload in candidates:
            await self._fail_publication(
                payload,
                RuntimeError(
                    "Publication outcome is unknown because the worker stopped during the "
                    "one allowed external-write attempt; automatic replay was blocked"
                ),
            )

    async def _publish_youtube_comment(self, payload: dict[str, Any], _: JobClaim) -> dict[str, Any]:
        try:
            await self._begin_publication(payload, "youtube_comments")
            from src.integrations.youtube import post_comment_reply

            context = payload.get("context") or {}
            # Re-check at the last application-controlled instant before the
            # provider call.  The earlier begin gate protects the state change;
            # this gate protects against a pause/kill racing with that change.
            await self._assert_write_allowed("youtube_comments")
            result = await asyncio.to_thread(post_comment_reply, context["comment_id"], payload["content"])
            if not result:
                raise RuntimeError("YouTube did not confirm the comment reply")
            return await self._finish_publication(payload, result, str(result.get("id", "")))
        except Exception as exc:
            await self._fail_publication(payload, exc)
            raise

    async def _publish_youtube_description(self, payload: dict[str, Any], _: JobClaim) -> dict[str, Any]:
        try:
            await self._begin_publication(payload, "youtube_descriptions")
            from src.integrations.youtube import update_video_description

            context = payload.get("context") or {}
            await self._assert_write_allowed("youtube_descriptions")
            result = await asyncio.to_thread(update_video_description, context["video_id"], payload["content"])
            if not result:
                raise RuntimeError("YouTube did not confirm the description update")
            return await self._finish_publication(payload, result, str(result.get("id", "")))
        except Exception as exc:
            await self._fail_publication(payload, exc)
            raise

    async def _publish_social(self, payload: dict[str, Any], _: JobClaim) -> dict[str, Any]:
        try:
            await self._begin_publication(payload, "content_engine")
            from src.integrations.publisher import publish_to_platforms

            platform = "twitter" if payload.get("platform") == "x" else payload.get("platform")
            await self._assert_write_allowed("content_engine")
            result = await publish_to_platforms(payload["content"], [str(platform)], (payload.get("context") or {}).get("media_url"))
            if result.get("fail_count") or result.get("success_count") != 1:
                raise RuntimeError(f"Publishing failed: {result}")
            platform_result = (result.get("results") or {}).get(platform, {}).get("data") or {}
            external_id = str(platform_result.get("id") or platform_result.get("post_id") or "")
            return await self._finish_publication(payload, result, external_id)
        except Exception as exc:
            await self._fail_publication(payload, exc)
            raise

    async def _publish_instagram_comment(self, payload: dict[str, Any], _: JobClaim) -> dict[str, Any]:
        try:
            await self._begin_publication(payload, "instagram_comments")
            from src.integrations.instagram_comments import post_public_reply

            context = payload.get("context") or {}
            await self._assert_write_allowed("instagram_comments")
            result = await post_public_reply(str(context["comment_id"]), payload["content"])
            return await self._finish_publication(payload, result, str(result.get("id", "")))
        except Exception as exc:
            await self._fail_publication(payload, exc)
            raise

    async def _accept_webhook(self, payload: dict[str, Any], claim: JobClaim) -> dict[str, Any]:
        return {"accepted": True, "provider": claim.job_type.removeprefix("webhook."), **payload}

    async def _run_blender_template_job(
        self,
        payload: dict[str, Any],
        claim: JobClaim,
    ) -> dict[str, Any]:
        """Resume a selected pod, run the idempotent GPU job, and capture proof."""
        from src.integrations.runpod import (
            cancel_blender_job,
            get_blender_job,
            list_pods,
            resume_pod,
            stop_pod,
            submit_blender_job,
            verify_blender_agent,
        )

        pod_id = str(payload["pod_id"])
        source_path = str(payload["source_path"])
        output_name = str(payload["output_name"])
        auto_stop = bool(payload.get("auto_stop", True))
        stopped = False

        async def progress(stage: str, **values: Any) -> None:
            await self.jobs.progress(
                claim.id,
                self.worker_id,
                {"stage": stage, **values},
            )

        try:
            await progress("checking_pod")
            pods = await list_pods()
            pod = next((item for item in pods if item.get("id") == pod_id), None)
            if pod is None:
                raise RuntimeError("The selected RunPod pod no longer exists")
            if pod.get("desired_status") != "RUNNING":
                await progress("starting_pod")
                await resume_pod(pod_id)
                deadline = asyncio.get_running_loop().time() + 600
                while asyncio.get_running_loop().time() < deadline:
                    await asyncio.sleep(8)
                    pods = await list_pods()
                    pod = next((item for item in pods if item.get("id") == pod_id), None)
                    if pod and pod.get("desired_status") == "RUNNING":
                        break
                else:
                    raise RuntimeError("The RunPod pod did not become ready within ten minutes")

            await progress("checking_blender_agent")
            health = await verify_blender_agent(pod_id)
            await progress("submitting_gpu_job", agent_health=health)
            state = await submit_blender_job(
                pod_id,
                job_id=claim.id,
                source_path=source_path,
                output_name=output_name,
                frame=int(payload.get("frame", 1)),
                samples=int(payload.get("samples", 64)),
                resolution_percent=int(payload.get("resolution_percent", 25)),
            )
            deadline = asyncio.get_running_loop().time() + 6 * 60 * 60
            while state.get("status") in {"queued", "running"}:
                if asyncio.get_running_loop().time() >= deadline:
                    raise RuntimeError("The Blender template job exceeded the six-hour safety limit")
                switch = await db.get_kill_switch_db()
                if switch["is_active"]:
                    raise RuntimeError("The Blender job was stopped by the global kill switch")
                await progress(
                    str(state.get("stage") or "gpu_job_running"),
                    agent_status=str(state.get("status") or "running"),
                    log_tail=list(state.get("log_tail") or [])[-40:],
                )
                await asyncio.sleep(5)
                state = await get_blender_job(pod_id, claim.id)
            if state.get("status") != "completed":
                raise RuntimeError(str(state.get("error") or "The Blender agent did not complete the job"))
            report = state.get("report") if isinstance(state.get("report"), dict) else {}
            if not report.get("gpu_engaged"):
                raise RuntimeError("Blender completed without proof that Cycles used a GPU")
            return {
                "stage": "completed",
                "agent_status": "completed",
                "output_path": str(state.get("output_path", "")),
                "preview_path": str(state.get("preview_path", "")),
                "report": report,
                "log_tail": list(state.get("log_tail") or [])[-80:],
                "source_unchanged": True,
            }
        except Exception:
            try:
                await cancel_blender_job(pod_id, claim.id)
            except Exception:
                logger.warning(
                    "Could not cancel Blender agent job %s during failure handling",
                    claim.id,
                )
            raise
        finally:
            if auto_stop:
                try:
                    await stop_pod(pod_id)
                    stopped = True
                except Exception:
                    logger.exception("Could not auto-stop RunPod pod %s after Blender job %s", pod_id, claim.id)
            if stopped:
                logger.info("Stopped RunPod pod %s after Blender job %s", pod_id, claim.id)

    async def run_forever(self) -> None:
        logger.info("Worker %s started", self.worker_id)
        try:
            while not self._stopping.is_set():
                worked = await self.run_once()
                if not worked:
                    try:
                        await asyncio.wait_for(self._stopping.wait(), timeout=self.poll_interval)
                    except TimeoutError:
                        pass
        finally:
            if self._telegram_started:
                from src.integrations.telegram_bot import stop_telegram_bot_async

                await stop_telegram_bot_async()
                self._telegram_started = False

    def stop(self) -> None:
        self._stopping.set()


async def _main() -> None:
    parser = argparse.ArgumentParser(description="AI Council OS durable worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--worker-id", default=None)
    args = parser.parse_args()
    await db.init_db()
    worker = DurableWorker(worker_id=args.worker_id, poll_interval=args.poll_interval)
    worker.register_production_handlers()
    if args.once:
        await worker.run_once()
    else:
        await worker.run_forever()


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(_main())
