"""Optimistic, idempotent approval state transitions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from src.core import database as db
from src.core.audit import record_audit
from src.core.models import (
    ApprovalModel, CouncilRunModel, IdempotencyRecordModel, TaskModel, utcnow,
)


class ApprovalError(RuntimeError):
    code = "APPROVAL_ERROR"


class ApprovalNotFound(ApprovalError):
    code = "APPROVAL_NOT_FOUND"


class ApprovalConflict(ApprovalError):
    code = "APPROVAL_VERSION_CONFLICT"


class ApprovalInvalidAction(ApprovalError):
    code = "APPROVAL_INVALID_ACTION"


@dataclass(frozen=True)
class MutationResult:
    resource: dict[str, Any]
    version: int
    audit_event_id: str
    replayed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "version": self.version,
            "audit_event_id": self.audit_event_id,
            "replayed": self.replayed,
        }


class ApprovalService:
    def __init__(self, *, session_factory=None) -> None:
        self._session_factory = session_factory

    @property
    def sessions(self):
        return self._session_factory or db.async_session

    async def create_pending(self, resource_type: str, resource_id: str) -> ApprovalModel:
        async with self.sessions() as session:
            result = await session.execute(
                select(ApprovalModel).where(
                    ApprovalModel.resource_type == resource_type,
                    ApprovalModel.resource_id == resource_id,
                )
            )
            approval = result.scalar_one_or_none()
            if approval:
                return approval
            approval = ApprovalModel(resource_type=resource_type, resource_id=resource_id)
            session.add(approval)
            await session.flush()
            await record_audit(
                session,
                action="approval.created",
                resource_type=resource_type,
                resource_id=resource_id,
                details={"approval_id": approval.id},
            )
            await session.commit()
            await session.refresh(approval)
            return approval

    async def act(
        self,
        approval_id: str,
        *,
        action: str,
        expected_version: int,
        idempotency_key: str,
        actor_user_id: str | None = None,
        actor_type: str = "user",
        actor_id: str = "",
        notes: str = "",
        edited_output: dict[str, Any] | None = None,
        request_id: str = "",
    ) -> MutationResult:
        action = action.strip().lower()
        if action not in {"approve", "reject", "cancel", "retry"}:
            raise ApprovalInvalidAction(f"Unsupported approval action: {action}")
        if not idempotency_key.strip():
            raise ApprovalInvalidAction("An idempotency key is required")

        request_payload = {
            "approval_id": approval_id,
            "action": action,
            "expected_version": expected_version,
            "actor_user_id": actor_user_id,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "notes": notes,
            "edited_output": edited_output or {},
        }
        request_hash = hashlib.sha256(
            json.dumps(request_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        scope = f"approval:{approval_id}"

        async with self.sessions() as session:
            result = await session.execute(
                select(ApprovalModel)
                .where(ApprovalModel.id == approval_id)
                .with_for_update()
            )
            approval = result.scalar_one_or_none()
            if not approval:
                raise ApprovalNotFound(f"Approval {approval_id!r} does not exist")

            replay_result = await session.execute(
                select(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.scope == scope,
                    IdempotencyRecordModel.idempotency_key == idempotency_key,
                )
            )
            replay = replay_result.scalar_one_or_none()
            if replay:
                if replay.request_hash != request_hash:
                    raise ApprovalConflict("Idempotency key was reused with a different request")
                payload = replay.response_payload
                return MutationResult(
                    resource=payload["resource"],
                    version=payload["version"],
                    audit_event_id=payload["audit_event_id"],
                    replayed=True,
                )

            if approval.version != expected_version:
                raise ApprovalConflict(
                    f"Expected version {expected_version}, current version is {approval.version}"
                )

            allowed = {
                "awaiting_approval": {"approve", "reject", "cancel", "retry"},
                "rejected": {"retry"},
                "cancelled": {"retry"},
                "failed": {"retry"},
            }
            if action not in allowed.get(approval.status, set()):
                raise ApprovalInvalidAction(
                    f"Action {action!r} is not allowed from status {approval.status!r}"
                )

            next_status = {
                "approve": "approved",
                "reject": "rejected",
                "cancel": "cancelled",
                "retry": "awaiting_approval",
            }[action]
            approval.status = next_status
            approval.action = action
            approval.actor_user_id = actor_user_id
            approval.notes = notes
            approval.edited_output = edited_output or {}
            approval.decided_at = None if action == "retry" else utcnow()
            approval.version += 1
            approval.updated_at = utcnow()

            await self._sync_resource_status(session, approval, next_status)
            event = await record_audit(
                session,
                action=f"approval.{action}",
                resource_type=approval.resource_type,
                resource_id=approval.resource_id,
                actor_type=actor_type,
                actor_id=actor_id or actor_user_id or "",
                request_id=request_id,
                details={"approval_id": approval.id, "version": approval.version, "notes": notes},
            )
            resource = self._serialize(approval)
            payload = {
                "resource": resource,
                "version": approval.version,
                "audit_event_id": event.id,
            }
            session.add(
                IdempotencyRecordModel(
                    scope=scope,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    response_payload=payload,
                    resource_id=approval.id,
                    expires_at=utcnow() + timedelta(days=30),
                )
            )
            await session.commit()
            return MutationResult(resource, approval.version, event.id)

    @staticmethod
    async def _sync_resource_status(session, approval: ApprovalModel, status: str) -> None:
        if approval.resource_type == "task":
            resource = await session.get(TaskModel, approval.resource_id)
        elif approval.resource_type == "council_run":
            resource = await session.get(CouncilRunModel, approval.resource_id)
        else:
            resource = None
        if resource is not None:
            resource.status = status
            resource.version += 1
            resource.updated_at = utcnow()

    @staticmethod
    def _serialize(approval: ApprovalModel) -> dict[str, Any]:
        return {
            "id": approval.id,
            "resource_type": approval.resource_type,
            "resource_id": approval.resource_id,
            "status": approval.status,
            "action": approval.action,
            "notes": approval.notes,
            "edited_output": approval.edited_output or {},
            "version": approval.version,
        }
