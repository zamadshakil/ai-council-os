"""Add reusable provider links for council approval destinations.

Revision ID: 20260818_0005
Revises: 20260818_0004
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260818_0005"
down_revision = "20260818_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "council_integrations",
        sa.Column("council_id", sa.String(length=30), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column(
            "purpose",
            sa.String(length=80),
            nullable=False,
            server_default="approved_output",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider"], ["integration_connections.provider"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("council_id", "provider"),
    )


def downgrade() -> None:
    op.drop_table("council_integrations")
