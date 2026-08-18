"""Preserve unknown task confidence instead of fabricating zero.

Revision ID: 20260818_0004
Revises: 20260818_0003
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260818_0004"
down_revision = "20260818_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.alter_column(
            "confidence_score",
            existing_type=sa.Float(),
            nullable=True,
            server_default=None,
        )


def downgrade() -> None:
    op.execute("UPDATE tasks SET confidence_score = 0 WHERE confidence_score IS NULL")
    with op.batch_alter_table("tasks") as batch:
        batch.alter_column(
            "confidence_score",
            existing_type=sa.Float(),
            nullable=False,
            server_default="0",
        )
