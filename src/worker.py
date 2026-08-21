"""Durable scheduler, council executor, publisher, and outbox worker."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
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

from sqlalchemy import func, select, update

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
    provider_linked_to_target,
    workflow_environment,
    workflow_connections_verified,
)
from src.core.models import (
    ApprovalModel,
    CouncilRunModel,
    CouncilStepModel,
    KillSwitchModel,
    KnowledgeDocumentModel,
    OutboxEventModel,
    PublicationAttemptModel,
    RenderFrameModel,
    RenderJobModel,
    RunKnowledgeUseModel,
    TaskModel,
    WorkflowDefinitionModel,
    WorkflowRunModel,
    utcnow,
)
from src.core.repositories import DurableTaskRepository

logger = logging.getLogger("council.worker")
JobHandler = Callable[
    [dict[str, Any], JobClaim], dict[str, Any] | Awaitable[dict[str, Any]]
]

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
        self.worker_id = (
            worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        )
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
            raise ValueError(
                f"Job handler is empty or already registered: {job_type!r}"
            )
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
        self.register("knowledge.ingest", self._ingest_knowledge)
        self.register("brain.maintenance", self._maintain_brain)
        self.register("brain.learn", self._learn_from_approval)
        self.register("publish.youtube_comment", self._publish_youtube_comment)
        self.register("publish.youtube_description", self._publish_youtube_description)
        self.register("publish.social", self._publish_social)
        self.register("publish.instagram_comment", self._publish_instagram_comment)
        self.register("crm.hubspot_sync", self._sync_hubspot_sales)
        self.register("blender.template_repair", self._run_blender_template_job)
        self.register("blender.render_stage", self._run_blender_render_stage)
        self.register("blender.flamenco_submit", self._run_flamenco_submit)
        self.register("blender.flamenco_monitor", self._run_flamenco_monitor)
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
            await self.jobs.fail(
                claim.id,
                self.worker_id,
                f"No handler registered for {claim.job_type!r}",
            )
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
            if claim.job_type in {
                "council.run",
                "knowledge.ingest",
                "brain.maintenance",
                "brain.learn",
            }:
                return await decrypted_provider_env("openrouter")
            if claim.job_type in {
                "blender.template_repair",
                "blender.render_stage",
                "blender.flamenco_submit",
                "blender.flamenco_monitor",
            }:
                return await decrypted_provider_env("runpod")
            if claim.job_type == "crm.hubspot_sync":
                return await decrypted_provider_env("hubspot")
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
    async def _credentials_current(
        session, definition: WorkflowDefinitionModel
    ) -> bool:
        if definition.credential_status != "verified":
            return False
        if definition.id not in WORKFLOW_REQUIRED_ENV:
            return True
        if not os.getenv("INTEGRATION_ENCRYPTION_KEY", "").strip() and os.getenv(
            "APP_ENV", "development"
        ).lower() not in {"production", "prod", "staging"}:
            return True
        linked = (
            (
                await session.execute(
                    select(WorkflowIntegrationModel.provider).where(
                        WorkflowIntegrationModel.workflow_id == definition.id
                    )
                )
            )
            .scalars()
            .first()
        )
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
            if (
                switch
                and switch.is_active
                and not claim.job_type.startswith("webhook.")
                and claim.job_type != "blender.flamenco_monitor"
            ):
                return False, "global kill switch is active"
            if claim.job_type in {
                "council.run",
                "knowledge.ingest",
                "brain.maintenance",
                "brain.learn",
            } or claim.job_type.startswith("webhook."):
                return True, ""
            if claim.job_type in {
                "blender.template_repair",
                "blender.render_stage",
                "blender.flamenco_submit",
                "blender.flamenco_monitor",
            }:
                try:
                    await decrypted_provider_env("runpod")
                except VaultConfigurationError:
                    return False, "RunPod credentials are not verified"
                return True, ""
            if claim.job_type == "crm.hubspot_sync":
                payload = claim.payload or {}
                linked = await provider_linked_to_target(
                    "hubspot",
                    workflow_id=(
                        str(payload.get("target_id") or "")
                        if payload.get("target_type") == "workflow"
                        else ""
                    ),
                    council_id=(
                        str(payload.get("target_id") or "")
                        if payload.get("target_type") == "council"
                        else ""
                    ),
                )
                if not linked:
                    return False, "HubSpot is no longer linked to this target"
                try:
                    await decrypted_provider_env("hubspot")
                except VaultConfigurationError:
                    return False, "HubSpot credentials are not verified"
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
        maintenance_bucket = now_utc.date().isoformat()
        await self.jobs.enqueue(
            workflow_id="brain",
            job_type="brain.maintenance",
            payload={"maintenance_date": maintenance_bucket},
            idempotency_key=f"brain.maintenance:{maintenance_bucket}",
            priority=-5,
            max_attempts=3,
        )
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
                if not attached or not await self._credentials_current(
                    session, attached
                ):
                    continue
            schedule = definition.schedule or {}
            schedule_type = schedule.get("type")
            if schedule_type == "interval":
                seconds = max(60, int(schedule.get("seconds", 0) or 0))
                bucket = now_epoch // seconds
            elif schedule_type == "cron":
                from croniter import croniter

                expression = str(schedule.get("expression", ""))
                if not croniter.is_valid(expression) or not croniter.match(
                    expression, now_utc
                ):
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
                        if key
                        not in {
                            "selected_document_hashes",
                            "selected_collection_ids",
                            "collection_ids",
                        }
                    },
                    "scheduled": True,
                    "scheduled_bucket": bucket,
                },
                idempotency_key=f"schedule:{definition.id}:{bucket}",
            )

    async def _ingest_knowledge(
        self, payload: dict[str, Any], _: JobClaim
    ) -> dict[str, Any]:
        from src.core.rag_engine import ingest_pending_document

        return await ingest_pending_document(str(payload["document_id"]))

    async def _maintain_brain(
        self, payload: dict[str, Any], _: JobClaim
    ) -> dict[str, Any]:
        from src.core.brain import run_maintenance
        from src.core.rag_engine import INDEX_VERSION

        maintenance_date = str(payload.get("maintenance_date") or "") or None
        result = await run_maintenance(maintenance_date)
        async with self.jobs.sessions() as session:
            candidates = (
                (
                    await session.execute(
                        select(KnowledgeDocumentModel)
                        .where(
                            KnowledgeDocumentModel.raw_content != b"",
                        )
                        .limit(500)
                    )
                )
                .scalars()
                .all()
            )
        recovery_documents = [
            document
            for document in candidates
            if document.indexing_version < INDEX_VERSION
            or (document.metadata_json or {}).get("graph_status") != "ready"
        ][:100]
        queued = 0
        recovery_bucket = maintenance_date or utcnow().date().isoformat()
        for document in recovery_documents:
            stale_index = document.indexing_version < INDEX_VERSION
            idempotency_key = (
                f"knowledge.background-reindex:{document.id}:v{INDEX_VERSION}"
                if stale_index
                else f"knowledge.graph-recovery:{document.id}:{recovery_bucket}"
            )
            job = await self.jobs.enqueue(
                workflow_id="knowledge",
                job_type="knowledge.ingest",
                payload={"document_id": document.id},
                idempotency_key=idempotency_key,
                max_attempts=4,
            )
            async with self.jobs.sessions() as session:
                persisted = await session.get(KnowledgeDocumentModel, document.id)
                if persisted and persisted.ingestion_job_id != job.id:
                    persisted.ingestion_job_id = job.id
                    persisted.version += 1
                    await session.commit()
            queued += 1
        return {
            **result,
            "knowledge_recovery_jobs_queued": queued,
            "reindex_jobs_queued": sum(
                document.indexing_version < INDEX_VERSION
                for document in recovery_documents
            ),
            "graph_recovery_jobs_queued": sum(
                document.indexing_version >= INDEX_VERSION
                for document in recovery_documents
            ),
        }

    async def _learn_from_approval(
        self, payload: dict[str, Any], _: JobClaim
    ) -> dict[str, Any]:
        from src.core.brain import (
            create_learning_suggestion,
            extract_approved_task_graph,
        )

        task_id = str(payload["task_id"])
        graph = await extract_approved_task_graph(task_id)
        suggestion = await create_learning_suggestion(task_id)
        return {"graph": graph, "learning": suggestion}

    async def _persist_council_progress(
        self, task_id: str, run_id: str, state: dict[str, Any]
    ) -> None:
        """Persist each completed generator/critic step while a run is active."""
        history = list(state.get("debate_history") or [])
        stage = str(state.get("progress_stage") or "running")
        warnings = list(state.get("warnings") or [])
        now = utcnow()
        async with self.jobs.sessions() as session:
            task = await session.get(TaskModel, task_id)
            run = await session.get(CouncilRunModel, run_id)
            if not task or not run or task.status == "cancelled":
                return

            current_context = dict(task.context or {})
            previous_progress = current_context.get("progress") or {}
            if (
                len(task.debate_history or []) == len(history)
                and previous_progress.get("stage") == stage
            ):
                return

            last_role = str(history[-1].get("role") or "") if history else ""
            current_context.update(
                {
                    "cost_metrics_complete": bool(
                        state.get("cost_metrics_complete", False)
                    ),
                    "input_tokens": int(state.get("total_input_tokens") or 0),
                    "output_tokens": int(state.get("total_output_tokens") or 0),
                    "warnings": warnings,
                    "progress": {
                        "stage": stage,
                        "step_count": len(history),
                        "draft_count": int(state.get("iteration") or 0),
                        "last_role": last_role,
                        "updated_at": now.isoformat(),
                    },
                }
            )
            task.status = "running"
            task.iterations = int(state.get("iteration") or 0)
            if any(str(message.get("role") or "") == "critic" for message in history):
                task.confidence_score = float(state.get("confidence_score") or 0)
            task.total_cost_usd = float(state.get("total_cost_usd") or 0.0)
            task.debate_history = history
            task.context = current_context
            task.version += 1
            task.updated_at = now

            run.status = "running"
            run.total_input_tokens = int(state.get("total_input_tokens") or 0)
            run.total_output_tokens = int(state.get("total_output_tokens") or 0)
            run.total_cost_usd = float(state.get("total_cost_usd") or 0.0)
            run.warning = "\n".join(warnings)
            run.context = {
                **(run.context or {}),
                "progress": current_context["progress"],
            }
            run.version += 1
            run.updated_at = now

            existing_sequences = set(
                (
                    await session.execute(
                        select(CouncilStepModel.sequence).where(
                            CouncilStepModel.run_id == run_id
                        )
                    )
                ).scalars()
            )
            for sequence, message in enumerate(history, start=1):
                if sequence in existing_sequences:
                    continue
                structured = message.get("structured_output") or {}
                session.add(
                    CouncilStepModel(
                        run_id=run_id,
                        sequence=sequence,
                        role=str(message.get("role", "")),
                        model_id=str(message.get("model_used", "")),
                        prompt=json.dumps(
                            message.get("prompt_messages") or [], ensure_ascii=False
                        ),
                        output={
                            "content": message.get("content", ""),
                            "structured_output": structured,
                        },
                        score_breakdown=structured.get("category_scores") or {},
                        input_tokens=int(message.get("input_tokens") or 0),
                        output_tokens=int(message.get("output_tokens") or 0),
                        cost_usd=float(message.get("cost_usd") or 0.0),
                    )
                )
            await session.commit()

    async def _run_council(
        self, payload: dict[str, Any], claim: JobClaim
    ) -> dict[str, Any]:
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
            if (
                task.status
                in {"awaiting_approval", "needs_manual_review", "approved", "rejected"}
                and run.final_output
            ):
                return {
                    "task_id": task_id,
                    "run_id": run_id,
                    "status": task.status,
                    "recovered": True,
                }
            task.status = run.status = "running"
            task.version += 1
            run.version += 1
            await session.commit()

        try:
            result = await run_council(
                str(payload["council"]),
                str(payload["task_description"]),
                context=payload.get("context") or {},
                priority=str(payload.get("priority") or "normal"),
                task_id=task_id,
                progress_callback=lambda state: self._persist_council_progress(
                    task_id, run_id, state
                ),
            )
        except Exception as exc:
            async with self.jobs.sessions() as session:
                task = await session.get(TaskModel, task_id)
                run = await session.get(CouncilRunModel, run_id)
                approval = (
                    await session.execute(
                        select(ApprovalModel).where(
                            ApprovalModel.resource_type == "task",
                            ApprovalModel.resource_id == task_id,
                        )
                    )
                ).scalar_one_or_none()
                if task and task.status != "cancelled":
                    task.status, task.error, task.version = (
                        "failed",
                        str(exc)[:8000],
                        task.version + 1,
                    )
                if run and run.status != "cancelled":
                    run.status, run.error, run.version = (
                        "failed",
                        str(exc)[:8000],
                        run.version + 1,
                    )
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
                "generated_output": result.final_output,
                "warnings": result.warnings,
                "cost_metrics_complete": result.cost_metrics_complete,
                "input_tokens": result.total_input_tokens,
                "output_tokens": result.total_output_tokens,
                "knowledge_snapshot": result.knowledge_snapshot,
                "skill_snapshot": result.skill_snapshot,
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
            run.final_output = {
                "content": result.final_output,
                "structured_output": result.structured_output,
            }
            run.confidence_score = result.confidence_score
            run.total_input_tokens = result.total_input_tokens
            run.total_output_tokens = result.total_output_tokens
            run.total_cost_usd = result.total_cost_usd
            run.warning = "\n".join(result.warnings)
            run.error = result.error
            run.version += 1
            run.updated_at = utcnow()

            existing_sequences = set(
                (
                    await session.execute(
                        select(CouncilStepModel.sequence).where(
                            CouncilStepModel.run_id == run_id
                        )
                    )
                ).scalars()
            )
            for sequence, message in enumerate(result.debate_history, start=1):
                if sequence in existing_sequences:
                    continue
                structured = message.get("structured_output") or {}
                session.add(
                    CouncilStepModel(
                        run_id=run_id,
                        sequence=sequence,
                        role=str(message.get("role", "")),
                        model_id=str(message.get("model_used", "")),
                        prompt=json.dumps(
                            message.get("prompt_messages") or [], ensure_ascii=False
                        ),
                        output={
                            "content": message.get("content", ""),
                            "structured_output": structured,
                        },
                        score_breakdown=structured.get("category_scores") or {},
                        input_tokens=int(message.get("input_tokens") or 0),
                        output_tokens=int(message.get("output_tokens") or 0),
                        cost_usd=float(message.get("cost_usd") or 0.0),
                    )
                )
            existing_uses = int(
                await session.scalar(
                    select(func.count(RunKnowledgeUseModel.id)).where(
                        RunKnowledgeUseModel.run_id == run_id
                    )
                )
                or 0
            )
            if not existing_uses:
                seen_resources: set[tuple[str, str, int]] = set()
                for item in result.knowledge_snapshot:
                    resource_key = (
                        str(item.get("resource_type") or "document"),
                        str(item.get("resource_id") or ""),
                        int(
                            item.get("resource_version")
                            or item.get("index_version")
                            or 1
                        ),
                    )
                    if resource_key[1] and resource_key not in seen_resources:
                        seen_resources.add(resource_key)
                        session.add(
                            RunKnowledgeUseModel(
                                run_id=run_id,
                                resource_type=resource_key[0],
                                resource_id=resource_key[1],
                                resource_version=resource_key[2],
                                metadata_json=item,
                            )
                        )
                for item in result.skill_snapshot:
                    session.add(
                        RunKnowledgeUseModel(
                            run_id=run_id,
                            resource_type="skill",
                            resource_id=str(item["skill_id"]),
                            resource_version=int(item.get("revision_number") or 1),
                            metadata_json=item,
                        )
                    )

            approval_result = await session.execute(
                select(ApprovalModel).where(
                    ApprovalModel.resource_type == "task",
                    ApprovalModel.resource_id == task_id,
                )
            )
            approval = approval_result.scalar_one_or_none()
            if approval is None:
                approval = ApprovalModel(
                    resource_type="task",
                    resource_id=task_id,
                    status="awaiting_approval",
                    version=1,
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
            outbox_result = await session.execute(
                select(OutboxEventModel).where(
                    OutboxEventModel.idempotency_key
                    == f"telegram:approval:{task_id}:v{approval_version}"
                )
            )
            if outbox_result.scalar_one_or_none() is None:
                session.add(
                    OutboxEventModel(
                        topic="telegram.approval",
                        payload={
                            "task_id": task_id,
                            "workflow_name": f"{result.council.title()} Council",
                            "draft_text": result.final_output,
                            "context_summary": task.task_description,
                            "confidence": result.confidence_score,
                            "council": result.council,
                            "retrieval_warnings": result.warnings,
                            "knowledge_sources": [
                                item.get("citation") or item.get("document_hash")
                                for item in result.knowledge_snapshot
                            ],
                            "skill_revisions": [
                                f"{item.get('name', 'Skill')} r{item.get('revision_number', 1)}"
                                for item in result.skill_snapshot
                            ],
                        },
                        idempotency_key=f"telegram:approval:{task_id}:v{approval_version}",
                    )
                )
            await record_audit(
                session,
                action="council_run.completed",
                resource_type="task",
                resource_id=task_id,
                details={
                    "run_id": run_id,
                    "status": result.status.value,
                    "draft_count": result.draft_count,
                    "cost_metrics_complete": result.cost_metrics_complete,
                },
            )
            await session.commit()
        return {
            "task_id": task_id,
            "run_id": run_id,
            "status": result.status.value,
            "confidence_score": result.confidence_score,
            "draft_count": result.draft_count,
        }

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

    async def _assert_hubspot_write_allowed(self, payload: dict[str, Any]) -> None:
        """Re-check kill switch, verified secret, and the explicit target link."""

        async with self.jobs.sessions() as session:
            switch = await session.get(KillSwitchModel, 1)
            if switch and switch.is_active:
                raise RuntimeError("Global kill switch activated before HubSpot write")
        target_type = str(payload.get("target_type") or "")
        target_id = str(payload.get("target_id") or "")
        linked = await provider_linked_to_target(
            "hubspot",
            workflow_id=target_id if target_type == "workflow" else "",
            council_id=target_id if target_type == "council" else "",
        )
        if not linked:
            raise RuntimeError("HubSpot is no longer linked to this approval target")
        await decrypted_provider_env("hubspot")

    async def _sync_hubspot_sales(
        self,
        payload: dict[str, Any],
        claim: JobClaim,
    ) -> dict[str, Any]:
        """Synchronize an approved sales lead while preserving task approval state."""

        await self._assert_hubspot_write_allowed(payload)
        try:
            async with self.jobs.sessions() as session:
                task = await session.get(TaskModel, payload["task_id"])
                attempt = await session.get(
                    PublicationAttemptModel, payload["publication_attempt_id"]
                )
                if not task or not attempt:
                    raise ValueError(
                        "HubSpot task or synchronization attempt does not exist"
                    )
                if attempt.status == "synced":
                    return {
                        "task_id": task.task_id,
                        "status": "synced",
                        **(attempt.response_payload or {}),
                    }
                attempt.status = "syncing"
                attempt.error = ""
                task.context = {
                    **(task.context or {}),
                    "hubspot_sync_status": "syncing",
                    "hubspot_sync_message": "Synchronizing the approved lead with HubSpot.",
                }
                task.version += 1
                task_payload = task.to_dict()
                await session.commit()

            # This is intentionally repeated immediately before the provider
            # call so a kill or unlink racing with the state change wins.
            await self._assert_hubspot_write_allowed(payload)
            from src.integrations.hubspot import sync_approved_sales_task

            result = await sync_approved_sales_task(task_payload)
            if result.get("status") != "synced":
                raise RuntimeError("HubSpot did not confirm the approved lead sync")

            async with self.jobs.sessions() as session:
                task = await session.get(TaskModel, payload["task_id"])
                attempt = await session.get(
                    PublicationAttemptModel, payload["publication_attempt_id"]
                )
                assert task is not None and attempt is not None
                attempt.status = "synced"
                attempt.response_payload = result
                attempt.external_id = str(result.get("hubspot_contact_id") or "")
                attempt.error = ""
                task.context = {
                    **(task.context or {}),
                    "hubspot_sync_status": "synced",
                    "hubspot_sync_message": "Approved lead synchronized with HubSpot.",
                    "hubspot_contact_id": str(result.get("hubspot_contact_id") or ""),
                    "hubspot_note_id": str(result.get("hubspot_note_id") or ""),
                    "hubspot_synced_at": utcnow().isoformat(),
                }
                task.version += 1
                session.add(
                    OutboxEventModel(
                        topic="telegram.publish_success",
                        payload={
                            "workflow_name": "Sales Council",
                            "platform": "HubSpot CRM",
                            "details": f"Approved task {task.task_id} synchronized",
                        },
                        idempotency_key=f"telegram:hubspot-synced:{attempt.id}",
                    )
                )
                await record_audit(
                    session,
                    action="hubspot.sync_succeeded",
                    resource_type="task",
                    resource_id=task.task_id,
                    details={
                        "attempt_id": attempt.id,
                        "contact_id": attempt.external_id,
                        "note_replayed": bool(result.get("note_replayed")),
                    },
                )
                await session.commit()
            return {"task_id": payload["task_id"], **result}
        except Exception as exc:
            terminal = claim.attempts >= claim.max_attempts
            message = str(exc)[:1000]
            async with self.jobs.sessions() as session:
                task = await session.get(TaskModel, payload.get("task_id", ""))
                attempt = await session.get(
                    PublicationAttemptModel,
                    payload.get("publication_attempt_id", ""),
                )
                if attempt:
                    attempt.status = "failed" if terminal else "retrying"
                    attempt.error = message
                if task:
                    task.context = {
                        **(task.context or {}),
                        "hubspot_sync_status": "failed" if terminal else "retrying",
                        "hubspot_sync_message": (
                            "HubSpot synchronization failed after all retries. The task "
                            "remains approved; review the integration and synchronize again."
                            if terminal
                            else "HubSpot synchronization will retry automatically."
                        ),
                    }
                    task.version += 1
                    if terminal:
                        await record_audit(
                            session,
                            action="hubspot.sync_failed",
                            resource_type="task",
                            resource_id=task.task_id,
                            details={
                                "attempt_id": attempt.id if attempt else "",
                                "error": message,
                            },
                        )
                        session.add(
                            OutboxEventModel(
                                topic="telegram.error",
                                payload={
                                    "workflow_name": "HubSpot CRM sync",
                                    "error": message,
                                },
                                idempotency_key=f"telegram:hubspot-failed:{payload.get('publication_attempt_id', '')}",
                            )
                        )
                await session.commit()
            raise

    async def _begin_publication(
        self, payload: dict[str, Any], workflow_id: str
    ) -> None:
        await self._assert_write_allowed(workflow_id)
        async with self.jobs.sessions() as session:
            task = await session.get(TaskModel, payload["task_id"])
            attempt = await session.get(
                PublicationAttemptModel, payload["publication_attempt_id"]
            )
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
            attempt = await session.get(
                PublicationAttemptModel, payload["publication_attempt_id"]
            )
            assert task is not None and attempt is not None
            task.status = "published"
            task.version += 1
            attempt.status = "published"
            attempt.response_payload = response
            attempt.external_id = external_id
            session.add(
                OutboxEventModel(
                    topic="telegram.publish_success",
                    payload={
                        "workflow_name": (task.context or {}).get(
                            "workflow", "Publishing"
                        ),
                        "platform": payload.get("platform", ""),
                        "details": f"Task: {task.task_id}",
                    },
                    idempotency_key=f"telegram:published:{attempt.id}",
                )
            )
            await record_audit(
                session,
                action="publication.succeeded",
                resource_type="task",
                resource_id=task.task_id,
                details={
                    "platform": payload.get("platform", ""),
                    "attempt_id": attempt.id,
                },
            )
            await session.commit()
        return {
            "task_id": payload["task_id"],
            "status": "published",
            "external_id": external_id,
        }

    async def _fail_publication(
        self, payload: dict[str, Any], error: Exception
    ) -> None:
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
                context.update(
                    {
                        "publication_state": "reconciliation_required",
                        "publication_attempt_id": payload["publication_attempt_id"],
                        "publication_retry_allowed": False,
                    }
                )
                task.context = context
                task.status = "needs_manual_review"
                task.error = message
                task.version += 1
            if attempt:
                attempt.status = "reconciliation_required"
                attempt.error = message
            if task and attempt:
                outbox_key = f"telegram:publication-failed:{attempt.id}"
                existing_outbox = (
                    await session.execute(
                        select(OutboxEventModel).where(
                            OutboxEventModel.idempotency_key == outbox_key
                        )
                    )
                ).scalar_one_or_none()
                if existing_outbox is None:
                    session.add(
                        OutboxEventModel(
                            topic="telegram.error",
                            payload={
                                "workflow_name": (task.context or {}).get(
                                    "workflow", "Publishing"
                                ),
                                "error": message,
                            },
                            idempotency_key=outbox_key,
                        )
                    )
                await record_audit(
                    session,
                    action="publication.reconciliation_required",
                    resource_type="task",
                    resource_id=task.task_id,
                    details={"attempt_id": attempt.id, "error": message},
                )
            await session.commit()

    async def _reconcile_abandoned_publications(self) -> None:
        """Make a crashed external write visible and recoverable by its safety policy."""
        now_monotonic = time.monotonic()
        if now_monotonic - self._last_reconcile_check < 30:
            return
        self._last_reconcile_check = now_monotonic
        candidates: list[dict[str, Any]] = []
        async with self.jobs.sessions() as session:
            jobs = (
                (
                    await session.execute(
                        select(WorkflowRunModel)
                        .where(
                            WorkflowRunModel.status == "dead_letter",
                            WorkflowRunModel.job_type.in_(
                                (
                                    "publish.youtube_comment",
                                    "publish.youtube_description",
                                    "publish.social",
                                    "publish.instagram_comment",
                                    "crm.hubspot_sync",
                                )
                            ),
                        )
                        .order_by(WorkflowRunModel.finished_at.desc())
                        .limit(100)
                    )
                )
                .scalars()
                .all()
            )
            for job in jobs:
                payload = job.payload or {}
                attempt_id = payload.get("publication_attempt_id")
                if not attempt_id:
                    continue
                attempt = await session.get(PublicationAttemptModel, attempt_id)
                if attempt and attempt.status in {"publishing", "syncing"}:
                    candidates.append({**payload, "job_type": job.job_type})
        for payload in candidates:
            if payload.pop("job_type", "") == "crm.hubspot_sync":
                await self._fail_abandoned_hubspot_sync(payload)
                continue
            await self._fail_publication(
                payload,
                RuntimeError(
                    "Publication outcome is unknown because the worker stopped during the "
                    "one allowed external-write attempt; automatic replay was blocked"
                ),
            )

    async def _fail_abandoned_hubspot_sync(self, payload: dict[str, Any]) -> None:
        """Close an expired final CRM attempt without changing approval state."""

        message = (
            "HubSpot synchronization stopped during its final attempt. The approved "
            "task was preserved; verify the contact in HubSpot before synchronizing again."
        )
        async with self.jobs.sessions() as session:
            task = await session.get(TaskModel, payload.get("task_id", ""))
            attempt = await session.get(
                PublicationAttemptModel,
                payload.get("publication_attempt_id", ""),
            )
            if attempt:
                attempt.status = "failed"
                attempt.error = message
            if task:
                task.context = {
                    **(task.context or {}),
                    "hubspot_sync_status": "failed",
                    "hubspot_sync_message": message,
                }
                task.version += 1
                await record_audit(
                    session,
                    action="hubspot.sync_failed",
                    resource_type="task",
                    resource_id=task.task_id,
                    details={"reason": "worker_stopped_on_final_attempt"},
                )
            await session.commit()

    async def _publish_youtube_comment(
        self, payload: dict[str, Any], _: JobClaim
    ) -> dict[str, Any]:
        try:
            await self._begin_publication(payload, "youtube_comments")
            from src.integrations.youtube import post_comment_reply

            context = payload.get("context") or {}
            # Re-check at the last application-controlled instant before the
            # provider call.  The earlier begin gate protects the state change;
            # this gate protects against a pause/kill racing with that change.
            await self._assert_write_allowed("youtube_comments")
            result = await asyncio.to_thread(
                post_comment_reply, context["comment_id"], payload["content"]
            )
            if not result:
                raise RuntimeError("YouTube did not confirm the comment reply")
            return await self._finish_publication(
                payload, result, str(result.get("id", ""))
            )
        except Exception as exc:
            await self._fail_publication(payload, exc)
            raise

    async def _publish_youtube_description(
        self, payload: dict[str, Any], _: JobClaim
    ) -> dict[str, Any]:
        try:
            await self._begin_publication(payload, "youtube_descriptions")
            from src.integrations.youtube import update_video_description

            context = payload.get("context") or {}
            await self._assert_write_allowed("youtube_descriptions")
            result = await asyncio.to_thread(
                update_video_description, context["video_id"], payload["content"]
            )
            if not result:
                raise RuntimeError("YouTube did not confirm the description update")
            return await self._finish_publication(
                payload, result, str(result.get("id", ""))
            )
        except Exception as exc:
            await self._fail_publication(payload, exc)
            raise

    async def _publish_social(
        self, payload: dict[str, Any], _: JobClaim
    ) -> dict[str, Any]:
        try:
            await self._begin_publication(payload, "content_engine")
            from src.integrations.publisher import publish_to_platforms

            platform = (
                "twitter" if payload.get("platform") == "x" else payload.get("platform")
            )
            await self._assert_write_allowed("content_engine")
            result = await publish_to_platforms(
                payload["content"],
                [str(platform)],
                (payload.get("context") or {}).get("media_url"),
            )
            if result.get("fail_count") or result.get("success_count") != 1:
                raise RuntimeError(f"Publishing failed: {result}")
            platform_result = (result.get("results") or {}).get(platform, {}).get(
                "data"
            ) or {}
            external_id = str(
                platform_result.get("id") or platform_result.get("post_id") or ""
            )
            return await self._finish_publication(payload, result, external_id)
        except Exception as exc:
            await self._fail_publication(payload, exc)
            raise

    async def _publish_instagram_comment(
        self, payload: dict[str, Any], _: JobClaim
    ) -> dict[str, Any]:
        try:
            await self._begin_publication(payload, "instagram_comments")
            from src.integrations.instagram_comments import post_public_reply

            context = payload.get("context") or {}
            await self._assert_write_allowed("instagram_comments")
            result = await post_public_reply(
                str(context["comment_id"]), payload["content"]
            )
            return await self._finish_publication(
                payload, result, str(result.get("id", ""))
            )
        except Exception as exc:
            await self._fail_publication(payload, exc)
            raise

    async def _accept_webhook(
        self, payload: dict[str, Any], claim: JobClaim
    ) -> dict[str, Any]:
        return {
            "accepted": True,
            "provider": claim.job_type.removeprefix("webhook."),
            **payload,
        }

    async def _run_blender_render_stage(
        self,
        payload: dict[str, Any],
        claim: JobClaim,
    ) -> dict[str, Any]:
        """Execute and persist one stage of a production Blender render."""
        from src.core import rendering
        from src.integrations.runpod import (
            cancel_blender_job,
            get_blender_job,
            list_pods,
            resume_pod,
            stop_pod,
            submit_render_stage,
            verify_blender_agent,
        )

        render_job_id = str(payload.get("render_job_id") or "")
        stage = str(payload.get("stage") or "")
        operation = stage.removeprefix("render.")
        if operation not in {
            "preflight", "benchmark", "observe_gui", "frame_batch",
            "prepare_flamenco", "validate", "encode", "deliver",
        }:
            raise RuntimeError("Render stage is not allowlisted")
        async with db.async_session() as session:
            render_job = await session.get(RenderJobModel, render_job_id)
        if render_job is None:
            raise RuntimeError("The production render job no longer exists")
        if render_job.status in {"cancelled", "paused", "completed"}:
            return {
                "stage": render_job.status,
                "render_job_id": render_job_id,
                "agent_status": "skipped",
            }
        requested_frames = [int(item) for item in payload.get("frames", [])]
        if operation == "frame_batch" and requested_frames:
            async with db.async_session() as session:
                completed_numbers = set((await session.execute(
                    select(RenderFrameModel.frame_number).where(
                        RenderFrameModel.render_job_id == render_job_id,
                        RenderFrameModel.frame_number.in_(requested_frames),
                        RenderFrameModel.status == "completed",
                    )
                )).scalars().all())
            requested_frames = [number for number in requested_frames if number not in completed_numbers]
            if not requested_frames:
                return {
                    "stage": stage,
                    "render_job_id": render_job_id,
                    "agent_status": "already_completed",
                }
        pod_id = render_job.pod_id
        should_stop = False

        async def update_job(
            *,
            status: str | None = None,
            next_stage: str | None = None,
            error: str | None = None,
            finished: bool = False,
        ) -> RenderJobModel:
            async with db.async_session() as session:
                row = await session.get(RenderJobModel, render_job_id, with_for_update=True)
                if row is None:
                    raise RuntimeError("The production render job no longer exists")
                if status is not None:
                    row.status = status
                if next_stage is not None:
                    row.stage = next_stage
                if error is not None:
                    row.error = error[:8000]
                if finished:
                    row.finished_at = utcnow()
                row.version += 1
                await session.commit()
                await session.refresh(row)
                return row

        async def queue_stage(next_stage: str, *, frames: list[int] | None = None) -> None:
            suffix = ""
            if frames:
                suffix = ":" + hashlib.sha256(
                    ",".join(map(str, frames)).encode()
                ).hexdigest()[:16]
            await self.jobs.enqueue(
                workflow_id="blender_manager",
                job_type="blender.render_stage",
                payload={
                    "render_job_id": render_job_id,
                    "stage": next_stage,
                    "frames": list(frames or []),
                },
                idempotency_key=f"render:{render_job_id}:{next_stage}{suffix}",
                priority=20,
                max_attempts=3 if next_stage != "render.deliver" else 8,
            )

        async def progress(stage_value: str, **values: Any) -> None:
            await self.jobs.progress(
                claim.id,
                self.worker_id,
                {"stage": stage_value, "render_job_id": render_job_id, **values},
            )

        try:
            await update_job(status="running", next_stage=stage, error="")
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
            visible_gpus = list(health.get("gpus") or [])
            if len(visible_gpus) != 1:
                raise RuntimeError(
                    "Safe baseline requires exactly one visible GPU; multi-GPU rendering is disabled until soak validation passes"
                )
            if render_job.render_mode == "kasm_gui" and not health.get("opengl_hardware_accelerated"):
                raise RuntimeError(
                    "Kasm is not using the NVIDIA OpenGL renderer; software-rendered llvmpipe is blocked"
                )
            settings = render_job.settings or {}
            frames = requested_frames
            if operation == "benchmark" and not frames:
                if render_job.frame_start is None or render_job.frame_end is None:
                    raise RuntimeError("Preflight did not discover the scene frame range")
                frames = rendering.representative_frames(
                    render_job.frame_start, render_job.frame_end, 7
                )
            switch = await db.get_kill_switch_db()
            if switch["is_active"]:
                raise RuntimeError(
                    "The Blender stage was stopped before the pod write by the global kill switch"
                )
            await progress("submitting_render_stage", operation=operation, agent_health=health)
            state = await submit_render_stage(
                pod_id,
                job_id=claim.id,
                render_job_id=render_job_id,
                operation=operation,
                source_path=render_job.source_path,
                output_profile=render_job.output_profile,
                frames=frames,
                frame_start=render_job.frame_start,
                frame_end=render_job.frame_end,
                frame_step=render_job.frame_step,
                samples=int(settings.get("samples") or 0),
                resolution_percent=int(settings.get("resolution_percent") or 100),
                expected_width=int(
                    int((render_job.preflight or {}).get("scene", {}).get("resolution_x") or 0)
                    * int(settings.get("resolution_percent") or 100) / 100
                ) or None,
                expected_height=int(
                    int((render_job.preflight or {}).get("scene", {}).get("resolution_y") or 0)
                    * int(settings.get("resolution_percent") or 100) / 100
                ) or None,
                persistent_data=bool(settings.get("persistent_data", False)),
                backend=str(settings.get("backend") or "AUTO"),
                fps=float((render_job.preflight or {}).get("scene", {}).get("fps") or 24.0),
                drive_path=str(settings.get("drive_path") or "Council OS Renders"),
                require_drive=bool(settings.get("require_drive", True)),
                include_audio=bool(
                    (render_job.preflight or {}).get("scene", {}).get("audio", {}).get("present")
                ),
            )
            deadline = asyncio.get_running_loop().time() + (
                24 * 60 * 60 if operation == "observe_gui" else 8 * 60 * 60
            )
            while state.get("status") in {"queued", "running"}:
                if asyncio.get_running_loop().time() >= deadline:
                    raise RuntimeError("The Blender stage exceeded its safety timeout")
                switch = await db.get_kill_switch_db()
                if switch["is_active"]:
                    raise RuntimeError("The Blender stage was stopped by the global kill switch")
                async with db.async_session() as session:
                    current_render = await session.get(RenderJobModel, render_job_id)
                if current_render and current_render.status in {"paused", "cancelled"}:
                    await cancel_blender_job(pod_id, claim.id)
                    return {
                        "stage": current_render.status,
                        "render_job_id": render_job_id,
                        "agent_status": current_render.status,
                    }
                await progress(
                    str(state.get("stage") or operation),
                    agent_status=str(state.get("status") or "running"),
                    completed_frames=int(state.get("completed_frames") or 0),
                    expected_frames=int(state.get("expected_frames") or 0),
                    telemetry=list(state.get("telemetry") or [])[-24:],
                    log_tail=list(state.get("log_tail") or [])[-40:],
                )
                await asyncio.sleep(5)
                state = await get_blender_job(pod_id, claim.id)
            if state.get("status") != "completed":
                raise RuntimeError(str(state.get("error") or "The Blender agent did not complete the stage"))
            report = state.get("report") if isinstance(state.get("report"), dict) else {}
            persisted = await rendering.persist_agent_snapshot(
                render_job_id, stage=stage, agent_state=state
            )

            if operation in {"benchmark", "frame_batch", "observe_gui"}:
                evidence = report.get("gpu_evidence") if isinstance(report.get("gpu_evidence"), dict) else {}
                if not (
                    evidence.get("cycles_backend_selected")
                    and evidence.get("gpu_process_observed")
                    and evidence.get("gpu_compute_observed")
                ):
                    raise RuntimeError(
                        "Blender produced output without complete PID/NVML proof of GPU compute"
                    )

            if operation == "preflight":
                scene = report.get("scene") if isinstance(report.get("scene"), dict) else {}
                if scene:
                    discovered_start = int(scene.get("frame_start", 1))
                    discovered_end = int(scene.get("frame_end", discovered_start))
                    requested_start = settings.get("requested_frame_start")
                    requested_end = settings.get("requested_frame_end")
                    start = int(requested_start) if requested_start is not None else discovered_start
                    end = int(requested_end) if requested_end is not None else discovered_end
                    if start < discovered_start or end > discovered_end or end < start:
                        raise RuntimeError(
                            "Requested frame range is outside the scene animation range"
                        )
                    await rendering.ensure_frames(
                        render_job_id,
                        start,
                        end,
                        render_job.frame_step,
                    )
                if report.get("status") == "blocked":
                    await update_job(status="blocked", next_stage="render.preflight", error="Preflight found blockers")
                    should_stop = persisted.auto_stop
                else:
                    await queue_stage("render.benchmark")
                    await update_job(status="benchmarking", next_stage="render.benchmark")
            elif operation == "benchmark":
                average_size = int(report.get("average_frame_bytes") or 0)
                average_seconds = float(report.get("average_frame_seconds") or 0)
                projected = int(average_size * max(1, persisted.expected_frame_count) * 1.25)
                storage = (persisted.preflight or {}).get("storage", {})
                projected_seconds = average_seconds * max(1, persisted.expected_frame_count)
                hourly_rate = float(pod.get("cost_per_hour") or 0)
                projected_cost = projected_seconds / 3600 * hourly_rate
                drive = (persisted.preflight or {}).get("drive", {})
                drive_quota = drive.get("quota", {}) if isinstance(drive, dict) else {}
                drive_free = int(drive_quota.get("free") or 0) if isinstance(drive_quota, dict) else 0
                evidence = report.get("gpu_evidence", {}) if isinstance(report.get("gpu_evidence"), dict) else {}
                host_peak = float(evidence.get("peak_host_ram_mb") or 0)
                host_total = float(evidence.get("host_ram_total_mb") or 0)
                required_host_gb = max(64, int((host_peak * 1.5 / 1024) + 0.999)) if host_peak else 64
                benchmark = {
                    **(persisted.benchmark or {}),
                    "projected_output_bytes_with_margin": projected,
                    "projected_runtime_seconds": projected_seconds,
                    "projected_cost": projected_cost,
                    "projected_cost_range": {
                        "low": projected_cost,
                        "high": projected_cost * 1.25,
                    },
                    "pod_hourly_rate": hourly_rate,
                    "required_host_ram_gb": required_host_gb,
                }
                async with db.async_session() as session:
                    row = await session.get(RenderJobModel, render_job_id, with_for_update=True)
                    if row:
                        row.benchmark = benchmark
                        row.settings = {
                            **(row.settings or {}),
                            "backend": str(report.get("cycles_backend_selected") or "AUTO"),
                            "persistent_data": bool(
                                (report.get("persistent_data_comparison") or {}).get("selected")
                            ),
                        }
                        if not (report.get("soak") or {}).get("passed"):
                            row.status = "blocked"
                            row.error = "The required continuous 50-frame GPU/memory soak did not pass"
                        elif projected and projected > int(storage.get("free_bytes") or 0):
                            row.status = "blocked"
                            row.error = "Projected frames exceed the safe local workspace capacity"
                        elif bool((row.settings or {}).get("require_drive", True)) and (
                            not drive_free or projected > drive_free
                        ):
                            row.status = "blocked"
                            row.error = "Google Drive lacks the projected delivery capacity plus safety margin"
                        elif host_total and host_peak / host_total >= 0.8:
                            row.status = "blocked"
                            row.error = f"Measured host RAM is unsafe; redeploy with at least {required_host_gb} GB"
                        else:
                            row.status = "awaiting_benchmark_approval"
                            row.error = ""
                        row.stage = "render.benchmark"
                        row.version += 1
                        await session.commit()
                should_stop = persisted.auto_stop
            elif operation == "prepare_flamenco":
                prepared_path = str(report.get("prepared_source_path") or "")
                prepared_checksum = str(report.get("prepared_source_checksum") or "")
                if not prepared_path.startswith(f"/workspace/render_jobs/{render_job_id}/"):
                    raise RuntimeError("The Flamenco farm copy was not created in the render workspace")
                async with db.async_session() as session:
                    row = await session.get(RenderJobModel, render_job_id, with_for_update=True)
                    if row:
                        row.scheduler_state = {
                            **(row.scheduler_state or {}),
                            "prepared_source_path": prepared_path,
                            "prepared_source_checksum": prepared_checksum,
                        }
                        row.status = "queueing_flamenco"
                        row.stage = "render.flamenco_submit"
                        row.version += 1
                        await session.commit()
                await self.jobs.enqueue(
                    workflow_id="blender_manager",
                    job_type="blender.flamenco_submit",
                    payload={"render_job_id": render_job_id},
                    idempotency_key=f"render:{render_job_id}:flamenco.submit",
                    priority=20,
                    max_attempts=4,
                )
            elif operation in {"observe_gui", "frame_batch"}:
                counted = await rendering.refresh_frame_counts(render_job_id)
                if counted.completed_frame_count >= counted.expected_frame_count:
                    await queue_stage("render.validate")
                    await update_job(status="validating", next_stage="render.validate")
                elif operation == "frame_batch":
                    async with db.async_session() as session:
                        pending = list((await session.execute(
                            select(RenderFrameModel.frame_number).where(
                                RenderFrameModel.render_job_id == render_job_id,
                                RenderFrameModel.status == "pending",
                            ).order_by(RenderFrameModel.frame_number)
                        )).scalars().all())
                    if pending:
                        batch_size = max(
                            1,
                            min(
                                int((counted.benchmark or {}).get("recommended_batch_size") or 1),
                                50,
                            ),
                        )
                        next_batch = rendering.frame_batches(pending, batch_size)[0]
                        digest = hashlib.sha256(
                            ",".join(map(str, next_batch)).encode()
                        ).hexdigest()[:16]
                        async with db.async_session() as session:
                            await session.execute(
                                update(RenderFrameModel)
                                .where(
                                    RenderFrameModel.render_job_id == render_job_id,
                                    RenderFrameModel.frame_number.in_(next_batch),
                                )
                                .values(batch_key=digest)
                            )
                            await session.commit()
                        await queue_stage("render.frame_batch", frames=next_batch)
                        await update_job(status="rendering", next_stage="render.frame_batch")
                    else:
                        # Failed frames are deliberately not looped forever. The
                        # validation stage exposes them for an explicit retry.
                        await queue_stage("render.validate")
                        await update_job(status="validating", next_stage="render.validate")
                else:
                    await update_job(status="rendering", next_stage=stage)
            elif operation == "validate":
                counted = await rendering.refresh_frame_counts(render_job_id)
                if report.get("status") == "blocked" or counted.failed_frame_count:
                    await update_job(status="needs_frame_retry", next_stage="render.validate", error="One or more frames are missing or invalid")
                    should_stop = counted.auto_stop
                else:
                    await queue_stage("render.encode")
                    await update_job(status="encoding", next_stage="render.encode")
            elif operation == "encode":
                if bool(settings.get("require_drive", True)):
                    await queue_stage("render.deliver")
                    await update_job(status="delivering", next_stage="render.deliver")
                else:
                    await update_job(status="completed", next_stage="completed", finished=True)
                    should_stop = persisted.auto_stop
            elif operation == "deliver":
                await update_job(status="completed", next_stage="completed", finished=True)
                should_stop = persisted.auto_stop

            return {
                "stage": stage,
                "render_job_id": render_job_id,
                "agent_status": "completed",
                "report": report,
                "log_tail": list(state.get("log_tail") or [])[-80:],
            }
        except Exception as exc:
            if operation == "deliver" and "delivery_blocked_storage_full" in str(exc):
                blocked = await update_job(
                    status="delivery_blocked_storage_full",
                    next_stage="render.deliver",
                    error="Google Drive storage is full; validated local outputs remain on /workspace",
                )
                should_stop = blocked.auto_stop
                return {
                    "stage": stage,
                    "render_job_id": render_job_id,
                    "agent_status": "delivery_blocked_storage_full",
                }
            await update_job(status="retrying" if claim.attempts < claim.max_attempts else "failed", next_stage=stage, error=str(exc), finished=claim.attempts >= claim.max_attempts)
            if claim.attempts >= claim.max_attempts:
                should_stop = render_job.auto_stop
            try:
                await cancel_blender_job(pod_id, claim.id)
            except Exception:
                logger.warning("Could not cancel Blender stage %s", claim.id)
            raise
        finally:
            if should_stop:
                try:
                    await stop_pod(pod_id)
                except Exception:
                    logger.exception("Could not auto-stop RunPod pod %s", pod_id)

    @staticmethod
    def _flamenco_frame_expression(start: int, end: int, step: int) -> str:
        if step <= 1:
            return f"{start}-{end}" if start != end else str(start)
        return ",".join(str(value) for value in range(start, end + 1, step))

    @staticmethod
    def _flamenco_task_frames(name: str) -> list[int]:
        if not name.startswith("render-"):
            return []
        values: list[int] = []
        for part in name.removeprefix("render-").split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                first, last = part.split("-", 1)
                values.extend(range(int(first), int(last) + 1))
            else:
                values.append(int(part))
        return sorted(set(values))

    async def _run_flamenco_submit(
        self,
        payload: dict[str, Any],
        _: JobClaim,
    ) -> dict[str, Any]:
        """Start the protected scheduler and submit one idempotent farm job."""
        from src.integrations.flamenco import start_flamenco, submit_flamenco_render

        render_job_id = str(payload.get("render_job_id") or "")
        async with db.async_session() as session:
            row = await session.get(RenderJobModel, render_job_id)
        if row is None:
            raise RuntimeError("The production render job no longer exists")
        if row.scheduler != "flamenco":
            raise RuntimeError("The render is not configured for Flamenco")
        if row.status in {"paused", "cancelled", "completed"}:
            return {"render_job_id": render_job_id, "status": row.status}
        if row.frame_start is None or row.frame_end is None:
            raise RuntimeError("Flamenco requires a preflighted scene frame range")
        state = row.scheduler_state or {}
        source_path = str(state.get("prepared_source_path") or "")
        if not source_path:
            raise RuntimeError("The immutable Flamenco scene copy is unavailable")
        coordinator_pod_id = row.coordinator_pod_id or row.pod_id
        await start_flamenco(coordinator_pod_id, "coordinator")
        if row.scheduler_job_id:
            flamenco_job_id = row.scheduler_job_id
            submitted: dict[str, Any] = {"id": flamenco_job_id, "reused": True}
        else:
            scene = (row.preflight or {}).get("scene", {})
            image_format = "OPEN_EXR" if row.output_profile == "compositing" else "PNG"
            extension = ".exr" if row.output_profile == "compositing" else ".png"
            submitted = await submit_flamenco_render(
                coordinator_pod_id,
                render_job_id=row.id,
                name=f"Council OS render {row.id[:8]}",
                source_path=source_path,
                output_directory=f"/workspace/render_jobs/{row.id}/frames",
                frames=self._flamenco_frame_expression(row.frame_start, row.frame_end, row.frame_step),
                chunk_size=max(1, min(int((row.benchmark or {}).get("recommended_batch_size") or 1), 50)),
                fps=float(scene.get("fps") or 24),
                image_format=image_format,
                image_extension=extension,
                scene=str(scene.get("name") or "Scene"),
                priority=50,
            )
            flamenco_job_id = str(submitted.get("id") or "")
        if not flamenco_job_id:
            raise RuntimeError("Flamenco did not return a scheduler job identifier")
        async with db.async_session() as session:
            current = await session.get(RenderJobModel, render_job_id, with_for_update=True)
            if current is None:
                raise RuntimeError("The production render job no longer exists")
            current.scheduler_job_id = flamenco_job_id
            current.status = "rendering"
            current.stage = "render.flamenco"
            current.scheduler_state = {
                **(current.scheduler_state or {}),
                "flamenco_status": str(submitted.get("status") or "queued"),
                "monitor_sequence": 0,
            }
            current.version += 1
            await session.commit()
        await self.jobs.enqueue(
            workflow_id="blender_manager",
            job_type="blender.flamenco_monitor",
            payload={"render_job_id": render_job_id, "sequence": 1},
            idempotency_key=f"render:{render_job_id}:flamenco.monitor:1",
            priority=20,
            max_attempts=5,
            available_at=utcnow() + timedelta(seconds=15),
        )
        return {
            "render_job_id": render_job_id,
            "flamenco_job_id": flamenco_job_id,
            "status": "queued",
        }

    async def _run_flamenco_monitor(
        self,
        payload: dict[str, Any],
        _: JobClaim,
    ) -> dict[str, Any]:
        """Reconcile Flamenco task state into Council OS durable frame state."""
        from src.integrations.flamenco import act_on_flamenco_job, get_flamenco_job

        render_job_id = str(payload.get("render_job_id") or "")
        sequence = max(1, int(payload.get("sequence") or 1))
        async with db.async_session() as session:
            row = await session.get(RenderJobModel, render_job_id)
        if row is None:
            raise RuntimeError("The production render job no longer exists")
        if row.status in {"completed", "cancelled"}:
            return {"render_job_id": render_job_id, "status": row.status}
        if not row.scheduler_job_id:
            raise RuntimeError("The Flamenco scheduler job identifier is missing")
        coordinator_pod_id = row.coordinator_pod_id or row.pod_id
        switch = await db.get_kill_switch_db()
        result = await get_flamenco_job(coordinator_pod_id, row.scheduler_job_id)
        observed_job = result.get("job") if isinstance(result.get("job"), dict) else {}
        observed_status = str(observed_job.get("status") or "unknown")
        if switch["is_active"] and observed_status not in {
            "paused", "pause-requested", "canceled", "cancel-requested", "completed", "failed",
        }:
            result = await act_on_flamenco_job(
                coordinator_pod_id,
                row.scheduler_job_id,
                "pause",
                reason="Council OS global kill switch activated",
            )
        job = result.get("job") if isinstance(result.get("job"), dict) else {}
        task_container = result.get("tasks") if isinstance(result.get("tasks"), dict) else {}
        tasks = task_container.get("tasks") if isinstance(task_container.get("tasks"), list) else []
        status = str(job.get("status") or "unknown")
        task_counts: dict[str, int] = {}
        async with db.async_session() as session:
            current = await session.get(RenderJobModel, render_job_id, with_for_update=True)
            if current is None:
                raise RuntimeError("The production render job no longer exists")
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                task_status = str(task.get("status") or "unknown")
                task_counts[task_status] = task_counts.get(task_status, 0) + 1
                frames = self._flamenco_task_frames(str(task.get("name") or ""))
                if not frames:
                    continue
                frame_status = {
                    "active": "rendering",
                    "queued": "pending",
                    "completed": "rendered",
                    "failed": "failed",
                    "soft-failed": "failed",
                    "canceled": "failed",
                    "paused": "pending",
                }.get(task_status, "pending")
                await session.execute(
                    update(RenderFrameModel)
                    .where(
                        RenderFrameModel.render_job_id == render_job_id,
                        RenderFrameModel.frame_number.in_(frames),
                        RenderFrameModel.status != "completed",
                    )
                    .values(
                        status=frame_status,
                        error=("Flamenco task failed" if frame_status == "failed" else ""),
                    )
                )
            current.scheduler_state = {
                **(current.scheduler_state or {}),
                "flamenco_status": status,
                "activity": str(job.get("activity") or ""),
                "steps_completed": int(job.get("steps_completed") or 0),
                "steps_total": int(job.get("steps_total") or 0),
                "task_counts": task_counts,
                "monitor_sequence": sequence,
            }
            if status == "paused":
                current.status = "paused"
            elif status == "pause-requested":
                current.status = "pausing"
            elif status == "completed":
                current.status = "validating"
                current.stage = "render.validate"
            elif status == "failed":
                current.status = "needs_frame_retry"
                current.error = "Flamenco stopped after repeated task failures; completed outputs were retained"
            elif status in {"canceled", "cancel-requested"}:
                current.status = "cancelled" if status == "canceled" else "cancelling"
                if status == "canceled":
                    current.finished_at = utcnow()
            else:
                current.status = "rendering"
                current.stage = "render.flamenco"
            current.version += 1
            await session.commit()

        if status == "completed":
            await self.jobs.enqueue(
                workflow_id="blender_manager",
                job_type="blender.render_stage",
                payload={"render_job_id": render_job_id, "stage": "render.validate", "frames": []},
                idempotency_key=f"render:{render_job_id}:render.validate:flamenco",
                priority=20,
                max_attempts=3,
            )
        elif status not in {"failed", "canceled", "paused"}:
            next_sequence = sequence + 1
            await self.jobs.enqueue(
                workflow_id="blender_manager",
                job_type="blender.flamenco_monitor",
                payload={"render_job_id": render_job_id, "sequence": next_sequence},
                idempotency_key=f"render:{render_job_id}:flamenco.monitor:{next_sequence}",
                priority=20,
                max_attempts=5,
                available_at=utcnow() + timedelta(seconds=15),
            )
        return {
            "render_job_id": render_job_id,
            "flamenco_job_id": row.scheduler_job_id,
            "status": status,
            "task_counts": task_counts,
        }

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
                    pod = next(
                        (item for item in pods if item.get("id") == pod_id), None
                    )
                    if pod and pod.get("desired_status") == "RUNNING":
                        break
                else:
                    raise RuntimeError(
                        "The RunPod pod did not become ready within ten minutes"
                    )

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
                    raise RuntimeError(
                        "The Blender template job exceeded the six-hour safety limit"
                    )
                switch = await db.get_kill_switch_db()
                if switch["is_active"]:
                    raise RuntimeError(
                        "The Blender job was stopped by the global kill switch"
                    )
                await progress(
                    str(state.get("stage") or "gpu_job_running"),
                    agent_status=str(state.get("status") or "running"),
                    log_tail=list(state.get("log_tail") or [])[-40:],
                )
                await asyncio.sleep(5)
                state = await get_blender_job(pod_id, claim.id)
            if state.get("status") != "completed":
                raise RuntimeError(
                    str(
                        state.get("error")
                        or "The Blender agent did not complete the job"
                    )
                )
            report = (
                state.get("report") if isinstance(state.get("report"), dict) else {}
            )
            evidence = report.get("gpu_evidence") if isinstance(report.get("gpu_evidence"), dict) else {}
            if not (
                evidence.get("cycles_backend_selected")
                and evidence.get("gpu_process_observed")
                and evidence.get("gpu_compute_observed")
            ):
                raise RuntimeError(
                    "Blender completed without PID/NVML proof that Cycles used a GPU"
                )
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
                    logger.exception(
                        "Could not auto-stop RunPod pod %s after Blender job %s",
                        pod_id,
                        claim.id,
                    )
            if stopped:
                logger.info(
                    "Stopped RunPod pod %s after Blender job %s", pod_id, claim.id
                )

    async def run_forever(self) -> None:
        logger.info("Worker %s started", self.worker_id)
        try:
            while not self._stopping.is_set():
                worked = await self.run_once()
                if not worked:
                    try:
                        await asyncio.wait_for(
                            self._stopping.wait(), timeout=self.poll_interval
                        )
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
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(_main())
