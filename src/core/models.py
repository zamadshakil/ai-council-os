"""SQLAlchemy schema for the durable AI Council OS state."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pgvector.sqlalchemy import Vector


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TaskModel(Base, TimestampMixin):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    council: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(50), index=True, default="queued")
    task_description: Mapped[str] = mapped_column(Text, default="")
    final_output: Mapped[str] = mapped_column(Text, default="")
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    iterations: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    debate_history: Mapped[list] = mapped_column(JSON, default=list)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    feedback_notes: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id, "council": self.council, "status": self.status,
            "task_description": self.task_description, "final_output": self.final_output,
            "confidence_score": self.confidence_score, "iterations": self.iterations,
            "total_cost_usd": self.total_cost_usd,
            "cost_metrics_complete": bool((self.context or {}).get("cost_metrics_complete", False)),
            "debate_history": self.debate_history or [], "context": self.context or {},
            "feedback_notes": self.feedback_notes or "", "error": self.error or "",
            "version": self.version, "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }


class UserModel(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(30), default="admin")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SessionModel(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(512), default="")


class LoginAttemptModel(Base):
    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempt_lookup", "username", "client_ip", "attempted_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100))
    client_ip: Mapped[str] = mapped_column(String(64), default="unknown")
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CouncilRunModel(Base, TimestampMixin):
    __tablename__ = "council_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # A task may have multiple persisted runs when an operator requests Retry.
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.task_id", ondelete="SET NULL"), index=True
    )
    council: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    prompt: Mapped[str] = mapped_column(Text)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    final_output: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    warning: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)


class CouncilStepModel(Base):
    __tablename__ = "council_steps"
    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_council_step_sequence"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("council_runs.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(30))
    model_id: Mapped[str] = mapped_column(String(200))
    prompt: Mapped[str] = mapped_column(Text)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkflowDefinitionModel(Base, TimestampMixin):
    __tablename__ = "workflow_definitions"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    schedule: Mapped[dict] = mapped_column(JSON, default=dict)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    credential_status: Mapped[str] = mapped_column(String(30), default="untested")
    version: Mapped[int] = mapped_column(Integer, default=1)


class WorkflowRunModel(Base, TimestampMixin):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_workflow_run_idempotency"),
        Index("ix_workflow_run_claim", "status", "priority", "available_at", "leased_until"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(String(100), index=True)
    job_type: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    idempotency_key: Mapped[str] = mapped_column(String(255))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class ExternalItemModel(Base):
    __tablename__ = "external_items"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_external_item"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source: Mapped[str] = mapped_column(String(100), index=True)
    external_id: Mapped[str] = mapped_column(String(255))
    workflow_run_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_runs.id", ondelete="SET NULL"))
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.task_id", ondelete="SET NULL"))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SeenItemModel(Base):
    __tablename__ = "seen_items"
    __table_args__ = (UniqueConstraint("source", "item_id", name="uq_seen_item"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[str] = mapped_column(String(255), index=True)
    source: Mapped[str] = mapped_column(String(100), index=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    metadata_text: Mapped[str] = mapped_column(Text, default="")


class ApprovalModel(Base, TimestampMixin):
    __tablename__ = "approvals"
    __table_args__ = (UniqueConstraint("resource_type", "resource_id", name="uq_approval_resource"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(40), default="awaiting_approval")
    action: Mapped[str] = mapped_column(String(30), default="")
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[str] = mapped_column(Text, default="")
    edited_output: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PublicationAttemptModel(Base, TimestampMixin):
    __tablename__ = "publication_attempts"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_publication_idempotency"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    approval_id: Mapped[str] = mapped_column(ForeignKey("approvals.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(40), default="queued")
    idempotency_key: Mapped[str] = mapped_column(String(255))
    request_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    response_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    external_id: Mapped[str] = mapped_column(String(255), default="")
    error: Mapped[str] = mapped_column(Text, default="")


class AuditEventModel(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_resource", "resource_type", "resource_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_type: Mapped[str] = mapped_column(String(30), default="system")
    actor_id: Mapped[str] = mapped_column(String(100), default="")
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    request_id: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class OutboxEventModel(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_outbox_idempotency"),
        Index("ix_outbox_claim", "status", "available_at", "leased_until"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    topic: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(40), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=10)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class IdempotencyRecordModel(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("scope", "idempotency_key", name="uq_idempotency_scope_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(100))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    resource_id: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KnowledgeDocumentModel(Base, TimestampMixin):
    __tablename__ = "knowledge_documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    storage_key: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    selected_for_grant: Mapped[bool] = mapped_column(Boolean, default=False)
    warning: Mapped[str] = mapped_column(Text, default="")


class KnowledgeChunkModel(Base):
    """PostgreSQL-backed production retrieval index.

    Local development may continue to use the lightweight LanceDB/SQLite
    adapter, but production chunks and embeddings are durable database state.
    """

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("doc_hash", "chunk_index", name="uq_knowledge_chunk_position"),
        Index("ix_knowledge_chunks_doc_hash", "doc_hash"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    doc_hash: Mapped[str] = mapped_column(String(64))
    doc_name: Mapped[str] = mapped_column(String(255))
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    parent_text: Mapped[str] = mapped_column(Text)
    vector: Mapped[list] = mapped_column(Vector(384).with_variant(JSON(), "sqlite"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KillSwitchModel(Base):
    __tablename__ = "kill_switch"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    toggled_by: Mapped[str] = mapped_column(String(100), default="system")
    toggled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reason: Mapped[str] = mapped_column(Text, default="")


class WorkflowSettingsModel(Base):
    __tablename__ = "workflow_settings"
    workflow_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    custom_prompt: Mapped[str] = mapped_column(Text, default="")
    selected_docs: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


def iso(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")
