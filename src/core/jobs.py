"""Durable database-backed workflow jobs and transactional outbox."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from src.core import database as db
from src.core.audit import record_audit
from src.core.models import ExternalItemModel, OutboxEventModel, WorkflowRunModel, utcnow


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@dataclass(frozen=True)
class JobClaim:
    id: str
    workflow_id: str
    job_type: str
    payload: dict[str, Any]
    priority: int
    attempts: int
    max_attempts: int
    lease_owner: str
    leased_until: datetime


@dataclass(frozen=True)
class StageResult:
    created: bool
    job_id: str | None
    external_item_id: str


class JobLeaseError(RuntimeError):
    pass


class JobService:
    def __init__(
        self,
        *,
        session_factory=None,
        lease_duration: timedelta = timedelta(minutes=5),
        retry_base: timedelta = timedelta(seconds=30),
        retry_cap: timedelta = timedelta(hours=1),
    ) -> None:
        self._session_factory = session_factory
        self.lease_duration = lease_duration
        self.retry_base = retry_base
        self.retry_cap = retry_cap

    @property
    def sessions(self):
        return self._session_factory or db.async_session

    async def enqueue(
        self,
        *,
        workflow_id: str,
        job_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        priority: int = 0,
        max_attempts: int = 5,
        available_at: datetime | None = None,
    ) -> WorkflowRunModel:
        async with self.sessions() as session:
            existing = await session.execute(
                select(WorkflowRunModel).where(
                    WorkflowRunModel.idempotency_key == idempotency_key
                )
            )
            job = existing.scalar_one_or_none()
            if job:
                return job
            job = WorkflowRunModel(
                workflow_id=workflow_id,
                job_type=job_type,
                payload=payload,
                idempotency_key=idempotency_key,
                priority=priority,
                max_attempts=max(1, max_attempts),
                available_at=available_at or utcnow(),
            )
            session.add(job)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                result = await session.execute(
                    select(WorkflowRunModel).where(
                        WorkflowRunModel.idempotency_key == idempotency_key
                    )
                )
                return result.scalar_one()
            await session.refresh(job)
            return job

    async def stage_external_job(
        self,
        *,
        source: str,
        external_id: str,
        workflow_id: str,
        job_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        metadata: dict[str, Any] | None = None,
        priority: int = 0,
        max_attempts: int = 5,
    ) -> StageResult:
        """Atomically claim an external item and enqueue its work."""
        async with self.sessions() as session:
            existing_result = await session.execute(
                select(ExternalItemModel).where(
                    ExternalItemModel.source == source,
                    ExternalItemModel.external_id == external_id,
                )
            )
            existing = existing_result.scalar_one_or_none()
            if existing:
                return StageResult(False, existing.workflow_run_id, existing.id)

            job = WorkflowRunModel(
                workflow_id=workflow_id,
                job_type=job_type,
                payload=payload,
                idempotency_key=idempotency_key,
                priority=priority,
                max_attempts=max(1, max_attempts),
            )
            session.add(job)
            try:
                await session.flush()
                item = ExternalItemModel(
                    source=source,
                    external_id=external_id,
                    workflow_run_id=job.id,
                    metadata_json=metadata or {},
                )
                session.add(item)
                await record_audit(
                    session,
                    action="workflow_job.staged",
                    resource_type="workflow_run",
                    resource_id=job.id,
                    details={
                        "workflow_id": workflow_id,
                        "source": source,
                        "external_id": external_id,
                    },
                )
                await session.commit()
            except IntegrityError:
                await session.rollback()
                result = await session.execute(
                    select(ExternalItemModel).where(
                        ExternalItemModel.source == source,
                        ExternalItemModel.external_id == external_id,
                    )
                )
                existing = result.scalar_one()
                return StageResult(False, existing.workflow_run_id, existing.id)
            return StageResult(True, job.id, item.id)

    async def claim(self, worker_id: str) -> JobClaim | None:
        now = utcnow()
        async with self.sessions() as session:
            # An expired final attempt is ambiguous (the process may have
            # crashed after an external write).  Dead-letter it instead of
            # reclaiming and risking a duplicate publication.
            await session.execute(
                update(WorkflowRunModel)
                .where(
                    WorkflowRunModel.status == "running",
                    WorkflowRunModel.leased_until.is_not(None),
                    WorkflowRunModel.leased_until < now,
                    WorkflowRunModel.attempts >= WorkflowRunModel.max_attempts,
                )
                .values(
                    status="dead_letter",
                    error="Worker lease expired after the final allowed attempt",
                    finished_at=now,
                    lease_owner=None,
                    leased_until=None,
                    version=WorkflowRunModel.version + 1,
                    updated_at=now,
                )
            )
            query = (
                select(WorkflowRunModel)
                .where(
                    WorkflowRunModel.available_at <= now,
                    WorkflowRunModel.attempts < WorkflowRunModel.max_attempts,
                    or_(
                        WorkflowRunModel.status.in_(("queued", "retry")),
                        (
                            (WorkflowRunModel.status == "running")
                            & (WorkflowRunModel.leased_until.is_not(None))
                            & (WorkflowRunModel.leased_until < now)
                        ),
                    ),
                )
                .order_by(
                    WorkflowRunModel.priority.desc(),
                    WorkflowRunModel.available_at.asc(),
                    WorkflowRunModel.created_at.asc(),
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            result = await session.execute(query)
            job = result.scalar_one_or_none()
            if not job:
                await session.commit()
                return None
            job.status = "running"
            job.lease_owner = worker_id
            job.leased_until = now + self.lease_duration
            job.started_at = job.started_at or now
            job.attempts += 1
            job.version += 1
            await session.commit()
            return JobClaim(
                id=job.id,
                workflow_id=job.workflow_id,
                job_type=job.job_type,
                payload=job.payload or {},
                priority=job.priority,
                attempts=job.attempts,
                max_attempts=job.max_attempts,
                lease_owner=worker_id,
                leased_until=_as_utc(job.leased_until),
            )

    async def heartbeat(self, job_id: str, worker_id: str) -> datetime:
        async with self.sessions() as session:
            job = await self._locked_job(session, job_id, worker_id)
            job.leased_until = utcnow() + self.lease_duration
            job.version += 1
            await session.commit()
            return _as_utc(job.leased_until)

    async def progress(
        self,
        job_id: str,
        worker_id: str,
        result: dict[str, Any],
    ) -> None:
        """Persist truthful intermediate state while retaining the current lease."""
        async with self.sessions() as session:
            job = await self._locked_job(session, job_id, worker_id)
            job.result = result
            # Progress is also proof the worker is alive. Extending the lease
            # here makes paid, long-running jobs fail closed if PostgreSQL is
            # unavailable instead of being reclaimed behind the active worker.
            job.leased_until = utcnow() + self.lease_duration
            job.version += 1
            await session.commit()

    async def complete(self, job_id: str, worker_id: str, result: dict[str, Any]) -> None:
        async with self.sessions() as session:
            job = await self._locked_job(session, job_id, worker_id)
            job.status = "completed"
            job.result = result
            job.error = ""
            job.finished_at = utcnow()
            job.lease_owner = None
            job.leased_until = None
            job.version += 1
            await record_audit(
                session, action="workflow_job.completed",
                resource_type="workflow_run", resource_id=job.id,
                details={"attempts": job.attempts},
            )
            await session.commit()

    async def fail(self, job_id: str, worker_id: str, error: str) -> str:
        async with self.sessions() as session:
            job = await self._locked_job(session, job_id, worker_id)
            job.error = error[:8000]
            job.lease_owner = None
            job.leased_until = None
            if job.attempts >= job.max_attempts:
                job.status = "dead_letter"
                job.finished_at = utcnow()
            else:
                exponent = max(0, job.attempts - 1)
                seconds = min(
                    self.retry_cap.total_seconds(),
                    self.retry_base.total_seconds() * (2**exponent),
                )
                job.status = "retry"
                job.available_at = utcnow() + timedelta(seconds=seconds)
            job.version += 1
            await record_audit(
                session, action=f"workflow_job.{job.status}",
                resource_type="workflow_run", resource_id=job.id,
                details={"attempts": job.attempts, "error": job.error},
            )
            await session.commit()
            return job.status

    async def release(self, job_id: str, worker_id: str, delay: timedelta) -> None:
        async with self.sessions() as session:
            job = await self._locked_job(session, job_id, worker_id)
            job.status = "queued"
            job.available_at = utcnow() + delay
            job.lease_owner = None
            job.leased_until = None
            # A policy gate (pause, kill switch, unverified credentials) did
            # not execute the handler and therefore must not consume a retry.
            job.attempts = max(0, job.attempts - 1)
            job.version += 1
            await session.commit()

    @staticmethod
    async def _locked_job(session, job_id: str, worker_id: str) -> WorkflowRunModel:
        result = await session.execute(
            select(WorkflowRunModel).where(WorkflowRunModel.id == job_id).with_for_update()
        )
        job = result.scalar_one_or_none()
        if not job or job.status != "running" or job.lease_owner != worker_id:
            raise JobLeaseError(f"Worker {worker_id!r} does not own job {job_id!r}")
        return job


@dataclass(frozen=True)
class OutboxClaim:
    id: str
    topic: str
    payload: dict[str, Any]
    attempts: int
    lease_owner: str


class OutboxService:
    def __init__(self, *, session_factory=None, lease_duration: timedelta = timedelta(minutes=2)):
        self._session_factory = session_factory
        self.lease_duration = lease_duration

    @property
    def sessions(self):
        return self._session_factory or db.async_session

    async def enqueue(
        self,
        *,
        topic: str,
        payload: dict[str, Any],
        idempotency_key: str,
        max_attempts: int = 10,
    ) -> OutboxEventModel:
        async with self.sessions() as session:
            result = await session.execute(
                select(OutboxEventModel).where(OutboxEventModel.idempotency_key == idempotency_key)
            )
            event = result.scalar_one_or_none()
            if event:
                return event
            event = OutboxEventModel(
                topic=topic,
                payload=payload,
                idempotency_key=idempotency_key,
                max_attempts=max(1, max_attempts),
            )
            session.add(event)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                result = await session.execute(
                    select(OutboxEventModel).where(
                        OutboxEventModel.idempotency_key == idempotency_key
                    )
                )
                return result.scalar_one()
            return event

    async def claim(self, worker_id: str) -> OutboxClaim | None:
        now = utcnow()
        async with self.sessions() as session:
            await session.execute(
                update(OutboxEventModel)
                .where(
                    OutboxEventModel.status == "publishing",
                    OutboxEventModel.leased_until.is_not(None),
                    OutboxEventModel.leased_until < now,
                    OutboxEventModel.attempts >= OutboxEventModel.max_attempts,
                )
                .values(
                    status="dead_letter",
                    last_error="Outbox lease expired after the final allowed attempt",
                    lease_owner=None,
                    leased_until=None,
                    version=OutboxEventModel.version + 1,
                )
            )
            result = await session.execute(
                select(OutboxEventModel)
                .where(
                    OutboxEventModel.available_at <= now,
                    OutboxEventModel.attempts < OutboxEventModel.max_attempts,
                    or_(
                        OutboxEventModel.status.in_(("pending", "retry")),
                        (
                            (OutboxEventModel.status == "publishing")
                            & (OutboxEventModel.leased_until.is_not(None))
                            & (OutboxEventModel.leased_until < now)
                        ),
                    ),
                )
                .order_by(OutboxEventModel.available_at.asc(), OutboxEventModel.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            event = result.scalar_one_or_none()
            if not event:
                await session.commit()
                return None
            event.status = "publishing"
            event.lease_owner = worker_id
            event.leased_until = now + self.lease_duration
            event.attempts += 1
            event.version += 1
            await session.commit()
            return OutboxClaim(event.id, event.topic, event.payload or {}, event.attempts, worker_id)

    async def mark_published(self, event_id: str, worker_id: str) -> None:
        async with self.sessions() as session:
            event = await self._locked_event(session, event_id, worker_id)
            event.status = "published"
            event.published_at = utcnow()
            event.lease_owner = None
            event.leased_until = None
            event.version += 1
            await session.commit()

    async def mark_failed(self, event_id: str, worker_id: str, error: str) -> str:
        async with self.sessions() as session:
            event = await self._locked_event(session, event_id, worker_id)
            event.last_error = error[:8000]
            event.lease_owner = None
            event.leased_until = None
            if event.attempts >= event.max_attempts:
                event.status = "dead_letter"
            else:
                event.status = "retry"
                event.available_at = utcnow() + timedelta(seconds=min(3600, 30 * 2 ** (event.attempts - 1)))
            event.version += 1
            await session.commit()
            return event.status

    async def release(self, event_id: str, worker_id: str, delay: timedelta) -> None:
        """Return a policy-gated event without consuming a delivery attempt."""
        async with self.sessions() as session:
            event = await self._locked_event(session, event_id, worker_id)
            event.status = "pending"
            event.available_at = utcnow() + delay
            event.lease_owner = None
            event.leased_until = None
            event.attempts = max(0, event.attempts - 1)
            event.version += 1
            await session.commit()

    @staticmethod
    async def _locked_event(session, event_id: str, worker_id: str) -> OutboxEventModel:
        result = await session.execute(
            select(OutboxEventModel).where(OutboxEventModel.id == event_id).with_for_update()
        )
        event = result.scalar_one_or_none()
        if not event or event.status != "publishing" or event.lease_owner != worker_id:
            raise JobLeaseError(f"Worker {worker_id!r} does not own outbox event {event_id!r}")
        return event
