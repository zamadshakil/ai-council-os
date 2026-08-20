"""Add durable Blender production render state.

Revision ID: 20260819_0007
Revises: 20260819_0006
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260819_0007"
down_revision = "20260819_0006"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "render_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("pod_id", sa.String(100), nullable=False),
        sa.Column("source_path", sa.String(1000), nullable=False),
        sa.Column("source_checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(50), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(50), nullable=False, server_default="render.preflight"),
        sa.Column("render_mode", sa.String(30), nullable=False, server_default="headless"),
        sa.Column("output_profile", sa.String(30), nullable=False, server_default="delivery"),
        sa.Column("output_directory", sa.String(1000), nullable=False, server_default=""),
        sa.Column("frame_start", sa.Integer(), nullable=True),
        sa.Column("frame_end", sa.Integer(), nullable=True),
        sa.Column("frame_step", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("expected_frame_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_frame_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_frame_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("settings", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("preflight", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("benchmark", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("delivery", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("auto_stop", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
    )
    op.create_index("ix_render_jobs_pod_id", "render_jobs", ["pod_id"])
    op.create_index("ix_render_jobs_status", "render_jobs", ["status"])
    op.create_index("ix_render_jobs_stage", "render_jobs", ["stage"])
    op.create_index("ix_render_jobs_status_updated", "render_jobs", ["status", "updated_at"])

    op.create_table(
        "render_frames",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("render_job_id", sa.String(36), sa.ForeignKey("render_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("frame_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("batch_key", sa.String(100), nullable=False, server_default=""),
        sa.Column("output_path", sa.String(1000), nullable=False, server_default=""),
        sa.Column("checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("render_seconds", sa.Float(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint("render_job_id", "frame_number", name="uq_render_job_frame"),
    )
    op.create_index("ix_render_frames_render_job_id", "render_frames", ["render_job_id"])
    op.create_index("ix_render_frames_status", "render_frames", ["status"])
    op.create_index("ix_render_frames_job_status", "render_frames", ["render_job_id", "status"])

    op.create_table(
        "render_telemetry",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("render_job_id", sa.String(36), sa.ForeignKey("render_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", sa.String(50), nullable=False, server_default=""),
        sa.Column("gpu_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blender_pid", sa.Integer(), nullable=True),
        sa.Column("gpu_utilization", sa.Float(), nullable=False, server_default="0"),
        sa.Column("vram_used_mb", sa.Float(), nullable=False, server_default="0"),
        sa.Column("vram_total_mb", sa.Float(), nullable=False, server_default="0"),
        sa.Column("power_watts", sa.Float(), nullable=False, server_default="0"),
        sa.Column("host_ram_used_mb", sa.Float(), nullable=False, server_default="0"),
        sa.Column("host_ram_total_mb", sa.Float(), nullable=False, server_default="0"),
        sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_render_telemetry_render_job_id", "render_telemetry", ["render_job_id"])
    op.create_index("ix_render_telemetry_job_sample", "render_telemetry", ["render_job_id", "sampled_at"])

    op.create_table(
        "render_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("render_job_id", sa.String(36), sa.ForeignKey("render_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("path", sa.String(1000), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(40), nullable=False, server_default="available"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint("render_job_id", "kind", "path", name="uq_render_artifact_path"),
    )
    op.create_index("ix_render_artifacts_render_job_id", "render_artifacts", ["render_job_id"])
    op.create_index("ix_render_artifacts_kind", "render_artifacts", ["kind"])


def downgrade() -> None:
    op.drop_table("render_artifacts")
    op.drop_table("render_telemetry")
    op.drop_table("render_frames")
    op.drop_table("render_jobs")
