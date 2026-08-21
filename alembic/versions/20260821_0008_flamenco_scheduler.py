"""Add Flamenco scheduler state to production renders.

Revision ID: 20260821_0008
Revises: 20260819_0007
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260821_0008"
down_revision = "20260819_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "render_jobs",
        sa.Column("scheduler", sa.String(30), nullable=False, server_default="native"),
    )
    op.add_column(
        "render_jobs",
        sa.Column("scheduler_job_id", sa.String(100), nullable=False, server_default=""),
    )
    op.add_column(
        "render_jobs",
        sa.Column("coordinator_pod_id", sa.String(100), nullable=False, server_default=""),
    )
    op.add_column(
        "render_jobs",
        sa.Column("worker_pod_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "render_jobs",
        sa.Column("scheduler_state", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_render_jobs_scheduler", "render_jobs", ["scheduler"])
    op.create_index("ix_render_jobs_scheduler_job_id", "render_jobs", ["scheduler_job_id"])


def downgrade() -> None:
    op.drop_index("ix_render_jobs_scheduler_job_id", table_name="render_jobs")
    op.drop_index("ix_render_jobs_scheduler", table_name="render_jobs")
    op.drop_column("render_jobs", "scheduler_state")
    op.drop_column("render_jobs", "worker_pod_ids")
    op.drop_column("render_jobs", "coordinator_pod_id")
    op.drop_column("render_jobs", "scheduler_job_id")
    op.drop_column("render_jobs", "scheduler")
