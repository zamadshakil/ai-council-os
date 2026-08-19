"""Add the native Council Brain, versioned skills, and scoped MCP state.

Revision ID: 20260819_0006
Revises: 20260818_0005
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = "20260819_0006"
down_revision = "20260818_0005"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    for column in (
        sa.Column(
            "raw_content", sa.LargeBinary(), nullable=False,
            server_default=sa.text("decode('', 'hex')") if is_postgres else sa.text("X''"),
        ),
        sa.Column("normalized_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("extraction_warnings", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("indexing_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding_model", sa.String(200), nullable=False, server_default=""),
        sa.Column("ingestion_job_id", sa.String(36), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    ):
        op.add_column("knowledge_documents", column)

    for column in (
        sa.Column("document_id", sa.String(36), nullable=True),
        sa.Column("source_start", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_end", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parent_key", sa.String(80), nullable=False, server_default=""),
        sa.Column("index_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("embedding_model", sa.String(200), nullable=False, server_default=""),
    ):
        op.add_column("knowledge_chunks", column)
    if op.get_bind().dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_knowledge_chunk_document", "knowledge_chunks", "knowledge_documents",
            ["document_id"], ["id"], ondelete="CASCADE",
        )
    else:
        with op.batch_alter_table("knowledge_chunks") as batch_op:
            batch_op.create_foreign_key(
                "fk_knowledge_chunk_document", "knowledge_documents",
                ["document_id"], ["id"], ondelete="CASCADE",
            )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])
    op.execute(
        "UPDATE knowledge_chunks SET document_id = knowledge_documents.id "
        "FROM knowledge_documents WHERE knowledge_chunks.doc_hash = knowledge_documents.sha256"
        if op.get_bind().dialect.name == "postgresql" else
        "UPDATE knowledge_chunks SET document_id = (SELECT id FROM knowledge_documents "
        "WHERE knowledge_documents.sha256 = knowledge_chunks.doc_hash LIMIT 1)"
    )

    op.create_table(
        "knowledge_collections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
    )
    op.create_table(
        "knowledge_collection_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("collection_id", sa.String(36), sa.ForeignKey("knowledge_collections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("collection_id", "document_id", name="uq_collection_document"),
    )
    op.create_index("ix_knowledge_collection_documents_collection_id", "knowledge_collection_documents", ["collection_id"])
    op.create_index("ix_knowledge_collection_documents_document_id", "knowledge_collection_documents", ["document_id"])
    op.create_table(
        "knowledge_bindings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("target_type", sa.String(30), nullable=False),
        sa.Column("target_id", sa.String(100), nullable=False),
        sa.Column("collection_id", sa.String(36), sa.ForeignKey("knowledge_collections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint("target_type", "target_id", "collection_id", name="uq_knowledge_binding"),
    )
    op.create_index("ix_knowledge_bindings_target_type", "knowledge_bindings", ["target_type"])
    op.create_index("ix_knowledge_bindings_target_id", "knowledge_bindings", ["target_id"])
    op.create_index("ix_knowledge_bindings_collection_id", "knowledge_bindings", ["collection_id"])
    op.create_table(
        "knowledge_binding_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("target_type", sa.String(30), nullable=False),
        sa.Column("target_id", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint("target_type", "target_id", name="uq_knowledge_binding_state_target"),
    )
    op.create_index("ix_knowledge_binding_states_target_type", "knowledge_binding_states", ["target_type"])
    op.create_index("ix_knowledge_binding_states_target_id", "knowledge_binding_states", ["target_id"])

    op.create_table(
        "brain_entities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("canonical_key", sa.String(240), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(30), nullable=False, server_default="proposed"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint("entity_type", "canonical_key", name="uq_brain_entity_key"),
    )
    op.create_index("ix_brain_entities_name", "brain_entities", ["name"])
    op.create_index("ix_brain_entities_canonical_key", "brain_entities", ["canonical_key"])
    op.create_index("ix_brain_entities_entity_type", "brain_entities", ["entity_type"])
    op.create_index("ix_brain_entities_status", "brain_entities", ["status"])
    op.create_table(
        "brain_entity_aliases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("brain_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alias", sa.String(240), nullable=False),
        sa.Column("normalized_alias", sa.String(240), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("normalized_alias", "entity_id", name="uq_entity_alias"),
    )
    op.create_index("ix_brain_entity_aliases_entity_id", "brain_entity_aliases", ["entity_id"])
    op.create_index("ix_brain_entity_aliases_alias", "brain_entity_aliases", ["alias"])
    op.create_index("ix_brain_entity_aliases_normalized_alias", "brain_entity_aliases", ["normalized_alias"])
    op.create_table(
        "brain_facts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("subject_entity_id", sa.String(36), sa.ForeignKey("brain_entities.id", ondelete="SET NULL")),
        sa.Column("predicate", sa.String(180), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(30), nullable=False, server_default="proposed"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("effective_from", sa.DateTime(timezone=True)),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column("supersedes_fact_id", sa.String(36), sa.ForeignKey("brain_facts.id", ondelete="SET NULL")),
        sa.Column("source_document_id", sa.String(36), sa.ForeignKey("knowledge_documents.id", ondelete="SET NULL")),
        sa.Column("source_chunk_id", sa.String(36), sa.ForeignKey("knowledge_chunks.id", ondelete="SET NULL")),
        sa.Column("council_run_id", sa.String(36), sa.ForeignKey("council_runs.id", ondelete="SET NULL")),
        sa.Column("approval_id", sa.String(36), sa.ForeignKey("approvals.id", ondelete="SET NULL")),
        sa.Column("citation_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("review_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
    )
    op.create_index("ix_brain_fact_subject_status", "brain_facts", ["subject_entity_id", "status"])
    for name in (
        "subject_entity_id", "predicate", "status", "supersedes_fact_id",
        "source_document_id", "source_chunk_id", "council_run_id", "approval_id",
    ):
        op.create_index(f"ix_brain_facts_{name}", "brain_facts", [name])
    op.create_table(
        "brain_relationships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_entity_id", sa.String(36), sa.ForeignKey("brain_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_entity_id", sa.String(36), sa.ForeignKey("brain_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relationship_type", sa.String(120), nullable=False),
        sa.Column("source_fact_id", sa.String(36), sa.ForeignKey("brain_facts.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(30), nullable=False, server_default="proposed"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint("source_entity_id", "relationship_type", "target_entity_id", "source_fact_id", name="uq_brain_relationship"),
    )
    for name in ("source_entity_id", "target_entity_id", "relationship_type", "status"):
        op.create_index(f"ix_brain_relationships_{name}", "brain_relationships", [name])
    op.create_table(
        "brain_conflicts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("fact_a_id", sa.String(36), sa.ForeignKey("brain_facts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fact_b_id", sa.String(36), sa.ForeignKey("brain_facts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(30), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("resolution", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint("fact_a_id", "fact_b_id", name="uq_brain_conflict_pair"),
    )
    for name in ("fact_a_id", "fact_b_id", "status"):
        op.create_index(f"ix_brain_conflicts_{name}", "brain_conflicts", [name])
    op.create_table(
        "brain_gaps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("gap_key", sa.String(64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint("gap_key", name="uq_brain_gap_key"),
    )
    op.create_index("ix_brain_gaps_status", "brain_gaps", ["status"])
    op.create_table(
        "brain_model_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("purpose", sa.String(80), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(100), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("structured_output", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float()),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_brain_model_calls_purpose", "brain_model_calls", ["purpose"])
    op.create_index("ix_brain_model_calls_resource_id", "brain_model_calls", ["resource_id"])
    op.create_table(
        "brain_maintenance_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("maintenance_date", sa.String(10), nullable=False, unique=True),
        sa.Column("result", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
    )
    op.create_index("ix_brain_maintenance_runs_status", "brain_maintenance_runs", ["status"])
    op.create_table(
        "retrieval_evaluations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset_version", sa.String(80), nullable=False),
        sa.Column("pipeline_version", sa.String(80), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(30), nullable=False, server_default="completed"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
    )
    op.create_table(
        "retrieval_cache",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(200), nullable=False),
        sa.Column("index_version", sa.Integer(), nullable=False),
        sa.Column("query_vector", Vector(384) if is_postgres else sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_retrieval_cache_expires_at", "retrieval_cache", ["expires_at"])
    op.create_index("ix_retrieval_cache_query_hash", "retrieval_cache", ["query_hash"])
    op.create_index("ix_retrieval_cache_scope_hash", "retrieval_cache", ["scope_hash"])

    op.create_table(
        "skills",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("scope_type", sa.String(30), nullable=False),
        sa.Column("scope_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("active_revision_id", sa.String(36)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint("scope_type", "scope_id", "name", name="uq_skill_scope_name"),
    )
    for name in ("scope_type", "scope_id", "active_revision_id"):
        op.create_index(f"ix_skills_{name}", "skills", [name])
    op.create_table(
        "skill_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("skill_id", sa.String(36), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "vector",
            Vector(384) if op.get_bind().dialect.name == "postgresql" else sa.JSON(),
            nullable=False,
        ),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_by", sa.String(100), nullable=False, server_default="administrator"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("skill_id", "revision_number", name="uq_skill_revision_number"),
    )
    op.create_index("ix_skill_revisions_skill_id", "skill_revisions", ["skill_id"])
    op.create_table(
        "learning_suggestions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_task_id", sa.String(50), sa.ForeignKey("tasks.task_id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_id", sa.String(36), sa.ForeignKey("skills.id", ondelete="SET NULL")),
        sa.Column("scope_type", sa.String(30), nullable=False),
        sa.Column("scope_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("proposed_instructions", sa.Text(), nullable=False),
        sa.Column("diff_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint("idempotency_key", name="uq_learning_suggestion_idempotency"),
    )
    for name in ("source_task_id", "skill_id", "status"):
        op.create_index(f"ix_learning_suggestions_{name}", "learning_suggestions", [name])
    op.create_table(
        "run_knowledge_uses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("council_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_type", sa.String(30), nullable=False),
        sa.Column("resource_id", sa.String(100), nullable=False),
        sa.Column("resource_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "resource_type", "resource_id", "resource_version", name="uq_run_knowledge_use"),
    )
    op.create_index("ix_run_knowledge_uses_run_id", "run_knowledge_uses", ["run_id"])
    op.create_table(
        "mcp_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("prefix", sa.String(12), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint("token_hash", name="uq_mcp_token_hash"),
    )
    op.create_index("ix_mcp_tokens_token_hash", "mcp_tokens", ["token_hash"])
    op.create_index("ix_mcp_tokens_expires_at", "mcp_tokens", ["expires_at"])
    op.create_table(
        "mcp_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token_id", sa.String(36), sa.ForeignKey("mcp_tokens.id", ondelete="CASCADE"), nullable=False),
        sa.Column("method", sa.String(100), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mcp_call_rate", "mcp_calls", ["token_id", "created_at"])
    op.create_index("ix_mcp_calls_token_id", "mcp_calls", ["token_id"])


def downgrade() -> None:
    op.drop_index("ix_mcp_call_rate", table_name="mcp_calls")
    for table in (
        "mcp_calls", "mcp_tokens", "run_knowledge_uses", "learning_suggestions",
    ):
        op.drop_table(table)
    op.drop_table("skill_revisions")
    op.drop_table("skills")
    for table in (
        "retrieval_cache", "retrieval_evaluations", "brain_maintenance_runs",
        "brain_model_calls", "brain_gaps", "brain_conflicts", "brain_relationships",
        "brain_facts", "brain_entity_aliases", "brain_entities", "knowledge_binding_states", "knowledge_bindings",
        "knowledge_collection_documents", "knowledge_collections",
    ):
        op.drop_table(table)
    op.drop_index("ix_knowledge_chunks_document_id", table_name="knowledge_chunks")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("fk_knowledge_chunk_document", "knowledge_chunks", type_="foreignkey")
    else:
        with op.batch_alter_table("knowledge_chunks") as batch_op:
            batch_op.drop_constraint("fk_knowledge_chunk_document", type_="foreignkey")
    for name in ("embedding_model", "index_version", "parent_key", "source_end", "source_start", "document_id"):
        op.drop_column("knowledge_chunks", name)
    for name in (
        "version", "error", "ingestion_job_id", "embedding_model", "indexing_version",
        "extraction_warnings", "metadata_json", "normalized_text", "raw_content",
    ):
        op.drop_column("knowledge_documents", name)
