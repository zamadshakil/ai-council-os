"""Create the durable production foundation.

Revision ID: 20260818_0001
Revises:
Create Date: 2026-08-18

The upgrade is intentionally legacy-aware: a database created by the old
runtime ``create_all`` path can be upgraded in place, while a fresh database
receives the complete schema.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260818_0001"
down_revision = None
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _create_index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in indexes:
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    tables = _tables()

    if "tasks" not in tables:
        op.create_table(
            "tasks",
            sa.Column("task_id", sa.String(50), primary_key=True),
            sa.Column("council", sa.String(50), nullable=False),
            sa.Column("status", sa.String(50), nullable=False, server_default="queued"),
            sa.Column("task_description", sa.Text(), nullable=False, server_default=""),
            sa.Column("final_output", sa.Text(), nullable=False, server_default=""),
            sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("iterations", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_cost_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("debate_history", sa.JSON(), nullable=False),
            sa.Column("context", sa.JSON(), nullable=False),
            sa.Column("feedback_notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("error", sa.Text(), nullable=False, server_default=""),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_tasks_council", "tasks", ["council"])
        _create_index("ix_tasks_status", "tasks", ["status"])
    elif "version" not in _columns("tasks"):
        op.add_column("tasks", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))

    if "seen_items" not in tables:
        op.create_table(
            "seen_items",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("item_id", sa.String(255), nullable=False),
            sa.Column("source", sa.String(100), nullable=False),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("metadata_text", sa.Text(), nullable=False, server_default=""),
            sa.UniqueConstraint("source", "item_id", name="uq_seen_item"),
        )
        _create_index("ix_seen_items_item_id", "seen_items", ["item_id"])
        _create_index("ix_seen_items_source", "seen_items", ["source"])
    else:
        unique_names = {
            constraint["name"] for constraint in sa.inspect(op.get_bind()).get_unique_constraints("seen_items")
        }
        if "uq_seen_item" not in unique_names:
            op.execute(sa.text(
                "DELETE FROM seen_items WHERE id NOT IN "
                "(SELECT MIN(id) FROM seen_items GROUP BY source, item_id)"
            ))
            with op.batch_alter_table("seen_items") as batch:
                batch.create_unique_constraint("uq_seen_item", ["source", "item_id"])

    if "kill_switch" not in tables:
        op.create_table(
            "kill_switch",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("toggled_by", sa.String(100), nullable=False, server_default="system"),
            sa.Column("toggled_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        )

    if "workflow_settings" not in tables:
        op.create_table(
            "workflow_settings",
            sa.Column("workflow_id", sa.String(100), primary_key=True),
            sa.Column("custom_prompt", sa.Text(), nullable=False, server_default=""),
            sa.Column("selected_docs", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(30), nullable=False, server_default="admin"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("client_ip", sa.String(64), nullable=False, server_default=""),
        sa.Column("user_agent", sa.String(512), nullable=False, server_default=""),
    )
    _create_index("ix_sessions_user_id", "sessions", ["user_id"])
    _create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("client_ip", sa.String(64), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_index(
        "ix_login_attempt_lookup", "login_attempts", ["username", "client_ip", "attempted_at"]
    )

    op.create_table(
        "council_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(50), sa.ForeignKey("tasks.task_id", ondelete="SET NULL")),
        sa.Column("council", sa.String(30), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="queued"),
        sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("final_output", sa.JSON(), nullable=False),
        sa.Column("confidence_score", sa.Float()),
        sa.Column("total_input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("warning", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_index("ix_council_runs_council", "council_runs", ["council"])
    _create_index("ix_council_runs_status", "council_runs", ["status"])
    _create_index("ix_council_runs_task_id", "council_runs", ["task_id"])

    op.create_table(
        "council_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("council_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("score_breakdown", sa.JSON(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "sequence", name="uq_council_step_sequence"),
    )
    _create_index("ix_council_steps_run_id", "council_steps", ["run_id"])

    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("schedule", sa.JSON(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("credential_status", sa.String(30), nullable=False, server_default="untested"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(100), nullable=False),
        sa.Column("job_type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="queued"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(100)),
        sa.Column("leased_until", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_workflow_run_idempotency"),
    )
    _create_index("ix_workflow_runs_workflow_id", "workflow_runs", ["workflow_id"])
    _create_index("ix_workflow_runs_job_type", "workflow_runs", ["job_type"])
    _create_index("ix_workflow_runs_status", "workflow_runs", ["status"])
    _create_index(
        "ix_workflow_run_claim",
        "workflow_runs",
        ["status", "priority", "available_at", "leased_until"],
    )

    op.create_table(
        "external_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("workflow_run_id", sa.String(36), sa.ForeignKey("workflow_runs.id", ondelete="SET NULL")),
        sa.Column("task_id", sa.String(50), sa.ForeignKey("tasks.task_id", ondelete="SET NULL")),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source", "external_id", name="uq_external_item"),
    )
    _create_index("ix_external_items_source", "external_items", ["source"])

    op.create_table(
        "approvals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="awaiting_approval"),
        sa.Column("action", sa.String(30), nullable=False, server_default=""),
        sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("edited_output", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("resource_type", "resource_id", name="uq_approval_resource"),
    )

    op.create_table(
        "publication_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("approval_id", sa.String(36), sa.ForeignKey("approvals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="queued"),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_publication_idempotency"),
    )
    _create_index("ix_publication_attempts_approval_id", "publication_attempts", ["approval_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_type", sa.String(30), nullable=False, server_default="system"),
        sa.Column("actor_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(100), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("request_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_index("ix_audit_events_created_at", "audit_events", ["created_at"])
    _create_index("ix_audit_resource", "audit_events", ["resource_type", "resource_id", "created_at"])

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("topic", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(100)),
        sa.Column("leased_until", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("idempotency_key", name="uq_outbox_idempotency"),
    )
    _create_index("ix_outbox_events_topic", "outbox_events", ["topic"])
    _create_index("ix_outbox_claim", "outbox_events", ["status", "available_at", "leased_until"])

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("resource_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("scope", "idempotency_key", name="uq_idempotency_scope_key"),
    )

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("selected_for_grant", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("warning", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "knowledge_documents", "idempotency_records", "outbox_events", "audit_events",
        "publication_attempts", "approvals", "external_items", "workflow_runs",
        "workflow_definitions", "council_steps", "council_runs", "login_attempts",
        "sessions", "users",
    ):
        if table in _tables():
            op.drop_table(table)
    if "tasks" in _tables() and "version" in _columns("tasks"):
        with op.batch_alter_table("tasks") as batch:
            batch.drop_column("version")
