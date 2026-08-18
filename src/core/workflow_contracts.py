"""Persistable contracts shared by workflow producers, API, and worker."""

from __future__ import annotations

import inspect
import uuid
from collections.abc import MutableMapping
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class WorkflowTaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PublicationPolicy(str, Enum):
    MANUAL_ONLY = "manual_only"
    APPROVAL_REQUIRED = "approval_required"


class WorkflowTask(BaseModel):
    """Durable task payload; ``source`` + ``external_id`` is the dedupe key."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow: str
    source: str
    external_id: str
    council: str
    status: WorkflowTaskStatus
    task_description: str
    final_output: str
    structured_output: dict[str, Any] = Field(default_factory=dict)
    confidence_score: float = Field(ge=0, le=100)
    iterations: int = Field(ge=1, le=3)
    total_cost_usd: float = Field(ge=0)
    cost_metrics_complete: bool
    debate_history: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    publication_policy: PublicationPolicy
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def dedupe_key(self) -> tuple[str, str]:
        return self.source, self.external_id

    def to_persisted_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        # Keep the workflow in context for compatibility with the existing API.
        data["context"] = {"workflow": self.workflow, **data["context"]}
        return data


class WorkflowRunResult(BaseModel):
    workflow: str
    status: str
    scanned: int = 0
    staged: int = 0
    skipped: int = 0
    failed: int = 0
    task_ids: list[str] = Field(default_factory=list)
    error: str | None = None


@runtime_checkable
class WorkflowTaskRepository(Protocol):
    async def stage_workflow_task(self, task: WorkflowTask) -> Any:
        """Atomically insert a task with a unique (source, external_id) key."""

    async def has_external_item(self, source: str, external_id: str) -> bool:
        ...

    async def record_external_item(
        self, source: str, external_id: str, metadata: dict[str, Any]
    ) -> bool:
        """Atomically remember a processed item that produced no approval task."""

    async def is_kill_switch_active(self) -> bool:
        ...

    async def is_workflow_blocked(self, workflow_id: str) -> bool:
        ...


TaskSink = MutableMapping[str, dict[str, Any]] | WorkflowTaskRepository


class DuplicateExternalItem(ValueError):
    pass


async def has_external_item(sink: TaskSink, source: str, external_id: str) -> bool:
    method = getattr(sink, "has_external_item", None)
    if method is not None:
        result = method(source, external_id)
        return bool(await result) if inspect.isawaitable(result) else bool(result)
    if isinstance(sink, MutableMapping):
        return any(
            item.get("source") == source and item.get("external_id") == external_id
            for item in sink.values()
            if isinstance(item, dict)
        )
    raise TypeError("Workflow task sink does not implement the persistence contract.")


async def stage_workflow_task(sink: TaskSink, task: WorkflowTask) -> WorkflowTask:
    """Stage through a durable repository or the legacy in-memory adapter."""
    method = getattr(sink, "stage_workflow_task", None)
    if method is not None:
        result = method(task)
        if inspect.isawaitable(result):
            await result
        return task
    if isinstance(sink, MutableMapping):
        if await has_external_item(sink, task.source, task.external_id):
            raise DuplicateExternalItem(f"Duplicate external item {task.dedupe_key!r}.")
        sink[task.task_id] = task.to_persisted_dict()
        return task
    raise TypeError("Workflow task sink does not implement the persistence contract.")


async def record_external_item(
    sink: TaskSink,
    source: str,
    external_id: str,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Record a filtered/discarded source item when the repository supports it."""
    method = getattr(sink, "record_external_item", None)
    if method is None:
        return False
    result = method(source, external_id, metadata or {})
    return bool(await result) if inspect.isawaitable(result) else bool(result)


async def workflow_kill_switch_active(sink: TaskSink) -> bool:
    """Read the production DB kill switch, with a legacy local adapter fallback."""
    method = getattr(sink, "is_kill_switch_active", None)
    if method is not None:
        result = method()
        return bool(await result) if inspect.isawaitable(result) else bool(result)
    from src.core.kill_switch import is_killed

    return is_killed()


async def workflow_execution_blocked(sink: TaskSink, workflow_id: str) -> bool:
    """Stop a long run when kill, pause, disable, or credential state changes."""
    method = getattr(sink, "is_workflow_blocked", None)
    if method is not None:
        result = method(workflow_id)
        return bool(await result) if inspect.isawaitable(result) else bool(result)
    return await workflow_kill_switch_active(sink)
