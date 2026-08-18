"""Store the production Grant knowledge index in PostgreSQL.

Revision ID: 20260818_0002
Revises: 20260818_0001
Create Date: 2026-08-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "20260818_0002"
down_revision = "20260818_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("doc_hash", sa.String(64), nullable=False),
        sa.Column("doc_name", sa.String(255), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("parent_text", sa.Text(), nullable=False),
        sa.Column(
            "vector",
            Vector(384) if op.get_bind().dialect.name == "postgresql" else sa.JSON(),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "doc_hash", "chunk_index", name="uq_knowledge_chunk_position"
        ),
    )
    op.create_index(
        "ix_knowledge_chunks_doc_hash", "knowledge_chunks", ["doc_hash"]
    )
    if op.get_bind().dialect.name == "postgresql":
        # Conservative HNSW parameters keep the index useful on a small VPS
        # without the default memory/build overhead of a large graph.
        op.execute(
            "CREATE INDEX ix_knowledge_chunks_vector_hnsw "
            "ON knowledge_chunks USING hnsw (vector vector_cosine_ops) "
            "WITH (m = 8, ef_construction = 32)"
        )
        op.execute(
            "CREATE INDEX ix_knowledge_chunks_search_gin ON knowledge_chunks "
            "USING gin (to_tsvector('simple', "
            "coalesce(parent_text, '') || ' ' || coalesce(text, '')))"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_search_gin")
        op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_vector_hnsw")
    op.drop_index("ix_knowledge_chunks_doc_hash", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
