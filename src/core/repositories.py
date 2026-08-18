"""Transactional repositories used by API and workflow producers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.core import database as db
from src.core.audit import record_audit
from src.core.models import (
    ApprovalModel,
    ExternalItemModel,
    KillSwitchModel,
    OutboxEventModel,
    TaskModel,
    utcnow,
)
from src.core.workflow_contracts import DuplicateExternalItem, WorkflowTask


class DurableTaskRepository:
    """Task sink that makes deduplication and task creation one transaction."""

    def __init__(self, *, session_factory=None) -> None:
        self._session_factory = session_factory

    @property
    def sessions(self):
        return self._session_factory or db.async_session

    async def is_kill_switch_active(self) -> bool:
        async with self.sessions() as session:
            switch = await session.get(KillSwitchModel, 1)
            return bool(switch and switch.is_active)

    async def is_workflow_blocked(self, workflow_id: str) -> bool:
        """Re-check pause/enable/credential gates during long producer loops."""
        from src.core.models import WorkflowDefinitionModel

        async with self.sessions() as session:
            switch = await session.get(KillSwitchModel, 1)
            definition = await session.get(WorkflowDefinitionModel, workflow_id)
            return bool(
                (switch and switch.is_active)
                or not definition
                or not definition.is_enabled
                or definition.is_paused
                or definition.credential_status != "verified"
            )

    async def has_external_item(self, source: str, external_id: str) -> bool:
        async with self.sessions() as session:
            result = await session.execute(
                select(ExternalItemModel).where(
                    ExternalItemModel.source == source,
                    ExternalItemModel.external_id == external_id,
                )
            )
            item = result.scalar_one_or_none()
            if not item:
                return False
            disposition = (item.metadata_json or {}).get("disposition")
            return item.task_id is not None or disposition in {"filtered", "excluded", "processed"}

    async def record_external_item(
        self, source: str, external_id: str, metadata: dict[str, Any]
    ) -> bool:
        """Remember a filtered item without creating a task or approval."""
        item = ExternalItemModel(
            source=source,
            external_id=external_id,
            metadata_json={**(metadata or {}), "disposition": "filtered"},
        )
        async with self.sessions() as session:
            session.add(item)
            try:
                await session.flush()
                await record_audit(
                    session,
                    action="external_item.filtered",
                    resource_type="external_item",
                    resource_id=item.id,
                    details={"source": source, "external_id": external_id, **(metadata or {})},
                )
                await session.commit()
                return True
            except IntegrityError:
                await session.rollback()
                return False

    async def stage_workflow_task(self, task: WorkflowTask) -> dict[str, Any]:
        persisted = task.to_persisted_dict()
        context = dict(persisted.get("context") or {})
        context.update(
            {
                "source": task.source,
                "external_id": task.external_id,
                "structured_output": task.structured_output,
                "publication_policy": task.publication_policy.value,
                "cost_metrics_complete": task.cost_metrics_complete,
            }
        )
        row = TaskModel(
            task_id=task.task_id,
            council=task.council,
            status=task.status.value,
            task_description=task.task_description,
            final_output=task.final_output,
            confidence_score=task.confidence_score,
            iterations=task.iterations,
            total_cost_usd=task.total_cost_usd,
            debate_history=task.debate_history,
            context=context,
            version=task.version,
            created_at=task.created_at,
            updated_at=task.created_at,
        )
        async with self.sessions() as session:
            existing_result = await session.execute(
                select(ExternalItemModel).where(
                    ExternalItemModel.source == task.source,
                    ExternalItemModel.external_id == task.external_id,
                )
            )
            item = existing_result.scalar_one_or_none()
            if item and item.task_id:
                if item.task_id == task.task_id:
                    existing_task = await session.get(TaskModel, task.task_id)
                    return existing_task.to_dict()
                raise DuplicateExternalItem(
                    f"Duplicate external item {(task.source, task.external_id)!r}"
                )

            session.add(row)
            if item:
                item.task_id = task.task_id
                item.metadata_json = {**(item.metadata_json or {}), "workflow": task.workflow}
            else:
                session.add(
                    ExternalItemModel(
                        source=task.source,
                        external_id=task.external_id,
                        task_id=task.task_id,
                        metadata_json={"workflow": task.workflow},
                    )
                )
            session.add(
                ApprovalModel(
                    resource_type="task",
                    resource_id=task.task_id,
                    # Even a below-threshold draft remains reviewable; the
                    # task retains needs_manual_review while its decision
                    # record stays in the approval state machine.
                    status="awaiting_approval",
                    version=task.version,
                )
            )
            session.add(
                OutboxEventModel(
                    topic="telegram.approval",
                    payload={
                        "task_id": task.task_id,
                        "workflow_name": task.workflow.replace("_", " ").title(),
                        "draft_text": task.final_output,
                        "context_summary": task.task_description,
                        "confidence": task.confidence_score,
                        "council": task.council,
                    },
                    idempotency_key=f"telegram:approval:{task.task_id}:v{task.version}",
                )
            )
            try:
                await record_audit(
                    session,
                    action="task.staged",
                    resource_type="task",
                    resource_id=task.task_id,
                    details={
                        "workflow": task.workflow,
                        "source": task.source,
                        "external_id": task.external_id,
                    },
                )
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                duplicate = await session.execute(
                    select(ExternalItemModel.id).where(
                        ExternalItemModel.source == task.source,
                        ExternalItemModel.external_id == task.external_id,
                    )
                )
                if duplicate.scalar_one_or_none() is not None:
                    raise DuplicateExternalItem(
                        f"Duplicate external item {(task.source, task.external_id)!r}"
                    ) from exc
                raise
            return row.to_dict()

    async def get(self, task_id: str) -> dict[str, Any] | None:
        async with self.sessions() as session:
            task = await session.get(TaskModel, task_id)
            return task.to_dict() if task else None

    async def update(
        self, task_id: str, updates: dict[str, Any], *, expected_version: int | None = None
    ) -> dict[str, Any] | None:
        async with self.sessions() as session:
            result = await session.execute(
                select(TaskModel).where(TaskModel.task_id == task_id).with_for_update()
            )
            task = result.scalar_one_or_none()
            if not task:
                return None
            if expected_version is not None and task.version != expected_version:
                raise ValueError(
                    f"Task version conflict: expected {expected_version}, current {task.version}"
                )
            allowed = {
                "status", "final_output", "confidence_score", "iterations",
                "total_cost_usd", "debate_history", "context", "feedback_notes", "error",
            }
            for key, value in updates.items():
                if key in allowed:
                    setattr(task, key, value)
            task.version += 1
            task.updated_at = utcnow()
            await session.commit()
            await session.refresh(task)
            return task.to_dict()
