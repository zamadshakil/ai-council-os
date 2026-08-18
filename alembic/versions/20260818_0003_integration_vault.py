"""Add encrypted integration connections and reusable workflow links.

Revision ID: 20260818_0003
Revises: 20260818_0002
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260818_0003"
down_revision = "20260818_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_connections",
        sa.Column("provider", sa.String(length=50), primary_key=True),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("encrypted_credentials", sa.Text(), nullable=False),
        sa.Column("credential_fields", sa.JSON(), nullable=False),
        sa.Column("credential_fingerprint", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="configured"),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "workflow_integrations",
        sa.Column(
            "workflow_id",
            sa.String(length=100),
            sa.ForeignKey("workflow_definitions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "provider",
            sa.String(length=50),
            sa.ForeignKey("integration_connections.provider", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("purpose", sa.String(length=80), nullable=False, server_default="primary"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("workflow_integrations")
    op.drop_table("integration_connections")
