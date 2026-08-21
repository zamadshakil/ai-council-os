"""SQLAlchemy schema for the durable AI Council OS state."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text,
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


class RenderJobModel(Base, TimestampMixin):
    """Authoritative state for a Blender production render.

    WorkflowRunModel owns execution leases; this model owns the user-visible
    render lifecycle and survives retries, pod restarts, and delivery failures.
    """

    __tablename__ = "render_jobs"
    __table_args__ = (
        Index("ix_render_jobs_status_updated", "status", "updated_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    pod_id: Mapped[str] = mapped_column(String(100), index=True)
    source_path: Mapped[str] = mapped_column(String(1000))
    source_checksum: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(50), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(50), default="render.preflight", index=True)
    render_mode: Mapped[str] = mapped_column(String(30), default="headless")
    scheduler: Mapped[str] = mapped_column(String(30), default="native", index=True)
    scheduler_job_id: Mapped[str] = mapped_column(String(100), default="", index=True)
    coordinator_pod_id: Mapped[str] = mapped_column(String(100), default="")
    worker_pod_ids: Mapped[list] = mapped_column(JSON, default=list)
    scheduler_state: Mapped[dict] = mapped_column(JSON, default=dict)
    output_profile: Mapped[str] = mapped_column(String(30), default="delivery")
    output_directory: Mapped[str] = mapped_column(String(1000), default="")
    frame_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frame_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frame_step: Mapped[int] = mapped_column(Integer, default=1)
    expected_frame_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_frame_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_frame_count: Mapped[int] = mapped_column(Integer, default=0)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    preflight: Mapped[dict] = mapped_column(JSON, default=dict)
    benchmark: Mapped[dict] = mapped_column(JSON, default=dict)
    delivery: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    auto_stop: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class RenderFrameModel(Base, TimestampMixin):
    __tablename__ = "render_frames"
    __table_args__ = (
        UniqueConstraint("render_job_id", "frame_number", name="uq_render_job_frame"),
        Index("ix_render_frames_job_status", "render_job_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    render_job_id: Mapped[str] = mapped_column(
        ForeignKey("render_jobs.id", ondelete="CASCADE"), index=True
    )
    frame_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    batch_key: Mapped[str] = mapped_column(String(100), default="")
    output_path: Mapped[str] = mapped_column(String(1000), default="")
    checksum: Mapped[str] = mapped_column(String(64), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    render_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)


class RenderTelemetryModel(Base):
    __tablename__ = "render_telemetry"
    __table_args__ = (Index("ix_render_telemetry_job_sample", "render_job_id", "sampled_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    render_job_id: Mapped[str] = mapped_column(
        ForeignKey("render_jobs.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(50), default="")
    gpu_index: Mapped[int] = mapped_column(Integer, default=0)
    blender_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gpu_utilization: Mapped[float] = mapped_column(Float, default=0.0)
    vram_used_mb: Mapped[float] = mapped_column(Float, default=0.0)
    vram_total_mb: Mapped[float] = mapped_column(Float, default=0.0)
    power_watts: Mapped[float] = mapped_column(Float, default=0.0)
    host_ram_used_mb: Mapped[float] = mapped_column(Float, default=0.0)
    host_ram_total_mb: Mapped[float] = mapped_column(Float, default=0.0)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RenderArtifactModel(Base, TimestampMixin):
    __tablename__ = "render_artifacts"
    __table_args__ = (
        UniqueConstraint("render_job_id", "kind", "path", name="uq_render_artifact_path"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    render_job_id: Mapped[str] = mapped_column(
        ForeignKey("render_jobs.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(50), index=True)
    path: Mapped[str] = mapped_column(String(1000))
    checksum: Mapped[str] = mapped_column(String(64), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="available")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
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
    raw_content: Mapped[bytes] = mapped_column(LargeBinary, default=b"")
    normalized_text: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    extraction_warnings: Mapped[list] = mapped_column(JSON, default=list)
    indexing_version: Mapped[int] = mapped_column(Integer, default=0)
    embedding_model: Mapped[str] = mapped_column(String(200), default="")
    ingestion_job_id: Mapped[str] = mapped_column(String(36), default="")
    selected_for_grant: Mapped[bool] = mapped_column(Boolean, default=False)
    warning: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)


class KnowledgeChunkModel(Base):
    """PostgreSQL-backed production retrieval index.

    SQLite uses this same schema only for local development and isolated tests;
    production chunks and embeddings are durable PostgreSQL/pgvector state.
    """

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("doc_hash", "chunk_index", name="uq_knowledge_chunk_position"),
        Index("ix_knowledge_chunks_doc_hash", "doc_hash"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    doc_hash: Mapped[str] = mapped_column(String(64))
    doc_name: Mapped[str] = mapped_column(String(255))
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    parent_text: Mapped[str] = mapped_column(Text)
    source_start: Mapped[int] = mapped_column(Integer, default=0)
    source_end: Mapped[int] = mapped_column(Integer, default=0)
    parent_key: Mapped[str] = mapped_column(String(80), default="")
    index_version: Mapped[int] = mapped_column(Integer, default=1)
    embedding_model: Mapped[str] = mapped_column(String(200), default="")
    vector: Mapped[list] = mapped_column(Vector(384).with_variant(JSON(), "sqlite"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeCollectionModel(Base, TimestampMixin):
    __tablename__ = "knowledge_collections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)


class KnowledgeCollectionDocumentModel(Base):
    __tablename__ = "knowledge_collection_documents"
    __table_args__ = (
        UniqueConstraint("collection_id", "document_id", name="uq_collection_document"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_collections.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeBindingModel(Base, TimestampMixin):
    __tablename__ = "knowledge_bindings"
    __table_args__ = (
        UniqueConstraint("target_type", "target_id", "collection_id", name="uq_knowledge_binding"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    target_type: Mapped[str] = mapped_column(String(30), index=True)
    target_id: Mapped[str] = mapped_column(String(100), index=True)
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_collections.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)


class KnowledgeBindingStateModel(Base, TimestampMixin):
    __tablename__ = "knowledge_binding_states"
    __table_args__ = (
        UniqueConstraint("target_type", "target_id", name="uq_knowledge_binding_state_target"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    target_type: Mapped[str] = mapped_column(String(30), index=True)
    target_id: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class BrainEntityModel(Base, TimestampMixin):
    __tablename__ = "brain_entities"
    __table_args__ = (UniqueConstraint("entity_type", "canonical_key", name="uq_brain_entity_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(240), index=True)
    canonical_key: Mapped[str] = mapped_column(String(240), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="proposed", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    version: Mapped[int] = mapped_column(Integer, default=1)


class BrainEntityAliasModel(Base):
    __tablename__ = "brain_entity_aliases"
    __table_args__ = (UniqueConstraint("normalized_alias", "entity_id", name="uq_entity_alias"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_id: Mapped[str] = mapped_column(ForeignKey("brain_entities.id", ondelete="CASCADE"), index=True)
    alias: Mapped[str] = mapped_column(String(240), index=True)
    normalized_alias: Mapped[str] = mapped_column(String(240), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BrainFactModel(Base, TimestampMixin):
    __tablename__ = "brain_facts"
    __table_args__ = (Index("ix_brain_fact_subject_status", "subject_entity_id", "status"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    subject_entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("brain_entities.id", ondelete="SET NULL"), index=True
    )
    predicate: Mapped[str] = mapped_column(String(180), index=True)
    value_text: Mapped[str] = mapped_column(Text)
    normalized_value: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="proposed", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supersedes_fact_id: Mapped[str | None] = mapped_column(
        ForeignKey("brain_facts.id", ondelete="SET NULL"), index=True
    )
    source_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="SET NULL"), index=True
    )
    source_chunk_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_chunks.id", ondelete="SET NULL"), index=True
    )
    council_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("council_runs.id", ondelete="SET NULL"), index=True
    )
    approval_id: Mapped[str | None] = mapped_column(
        ForeignKey("approvals.id", ondelete="SET NULL"), index=True
    )
    citation_text: Mapped[str] = mapped_column(Text, default="")
    review_reason: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)


class BrainRelationshipModel(Base, TimestampMixin):
    __tablename__ = "brain_relationships"
    __table_args__ = (
        UniqueConstraint("source_entity_id", "relationship_type", "target_entity_id", "source_fact_id", name="uq_brain_relationship"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_entity_id: Mapped[str] = mapped_column(ForeignKey("brain_entities.id", ondelete="CASCADE"), index=True)
    target_entity_id: Mapped[str] = mapped_column(ForeignKey("brain_entities.id", ondelete="CASCADE"), index=True)
    relationship_type: Mapped[str] = mapped_column(String(120), index=True)
    source_fact_id: Mapped[str | None] = mapped_column(ForeignKey("brain_facts.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(30), default="proposed", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    version: Mapped[int] = mapped_column(Integer, default=1)


class BrainConflictModel(Base, TimestampMixin):
    __tablename__ = "brain_conflicts"
    __table_args__ = (UniqueConstraint("fact_a_id", "fact_b_id", name="uq_brain_conflict_pair"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    fact_a_id: Mapped[str] = mapped_column(ForeignKey("brain_facts.id", ondelete="CASCADE"), index=True)
    fact_b_id: Mapped[str] = mapped_column(ForeignKey("brain_facts.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(30), default="medium")
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    resolution: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)


class BrainGapModel(Base, TimestampMixin):
    __tablename__ = "brain_gaps"
    __table_args__ = (UniqueConstraint("gap_key", name="uq_brain_gap_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    gap_key: Mapped[str] = mapped_column(String(64))
    question: Mapped[str] = mapped_column(Text)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class BrainModelCallModel(Base):
    __tablename__ = "brain_model_calls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    purpose: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str] = mapped_column(String(100), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str] = mapped_column(String(200))
    structured_output: Mapped[dict] = mapped_column(JSON, default=dict)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BrainMaintenanceRunModel(Base, TimestampMixin):
    __tablename__ = "brain_maintenance_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    maintenance_date: Mapped[str] = mapped_column(String(10), unique=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)


class RetrievalEvaluationModel(Base, TimestampMixin):
    __tablename__ = "retrieval_evaluations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    dataset_version: Mapped[str] = mapped_column(String(80))
    pipeline_version: Mapped[str] = mapped_column(String(80))
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="completed")
    version: Mapped[int] = mapped_column(Integer, default=1)


class RetrievalCacheModel(Base):
    __tablename__ = "retrieval_cache"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    query_hash: Mapped[str] = mapped_column(String(64), index=True)
    scope_hash: Mapped[str] = mapped_column(String(64), index=True)
    model_version: Mapped[str] = mapped_column(String(200))
    index_version: Mapped[int] = mapped_column(Integer)
    query_vector: Mapped[list] = mapped_column(
        Vector(384).with_variant(JSON(), "sqlite"), default=list
    )
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SkillModel(Base, TimestampMixin):
    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("scope_type", "scope_id", "name", name="uq_skill_scope_name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    scope_type: Mapped[str] = mapped_column(String(30), index=True)
    scope_id: Mapped[str] = mapped_column(String(100), default="", index=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    active_revision_id: Mapped[str | None] = mapped_column(String(36), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class SkillRevisionModel(Base):
    __tablename__ = "skill_revisions"
    __table_args__ = (UniqueConstraint("skill_id", "revision_number", name="uq_skill_revision_number"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    instructions: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    vector: Mapped[list] = mapped_column(Vector(384).with_variant(JSON(), "sqlite"), default=list)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(100), default="administrator")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LearningSuggestionModel(Base, TimestampMixin):
    __tablename__ = "learning_suggestions"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_learning_suggestion_idempotency"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id", ondelete="CASCADE"), index=True)
    skill_id: Mapped[str | None] = mapped_column(ForeignKey("skills.id", ondelete="SET NULL"), index=True)
    scope_type: Mapped[str] = mapped_column(String(30))
    scope_id: Mapped[str] = mapped_column(String(100), default="")
    title: Mapped[str] = mapped_column(String(200))
    rationale: Mapped[str] = mapped_column(Text)
    proposed_instructions: Mapped[str] = mapped_column(Text)
    diff_text: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, default=1)


class RunKnowledgeUseModel(Base):
    __tablename__ = "run_knowledge_uses"
    __table_args__ = (UniqueConstraint("run_id", "resource_type", "resource_id", "resource_version", name="uq_run_knowledge_use"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("council_runs.id", ondelete="CASCADE"), index=True)
    resource_type: Mapped[str] = mapped_column(String(30))
    resource_id: Mapped[str] = mapped_column(String(100))
    resource_version: Mapped[int] = mapped_column(Integer, default=1)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MCPTokenModel(Base, TimestampMixin):
    __tablename__ = "mcp_tokens"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_mcp_token_hash"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), index=True)
    prefix: Mapped[str] = mapped_column(String(12))
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class MCPCallModel(Base):
    __tablename__ = "mcp_calls"
    __table_args__ = (Index("ix_mcp_call_rate", "token_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    token_id: Mapped[str] = mapped_column(ForeignKey("mcp_tokens.id", ondelete="CASCADE"), index=True)
    method: Mapped[str] = mapped_column(String(100))
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
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
