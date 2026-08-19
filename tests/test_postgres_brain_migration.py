from __future__ import annotations

import os
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_postgres16_pgvector_schema_and_indexes():
    database_url = os.getenv("TEST_POSTGRES_URL", "").strip()
    if not database_url:
        pytest.skip(
            "Set TEST_POSTGRES_URL to a dedicated PostgreSQL 16 + pgvector database"
        )
    environment = {**os.environ, "DATABASE_URL": database_url}
    for command in (
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        [sys.executable, "-m", "alembic", "check"],
    ):
        result = subprocess.run(
            command, env=environment, capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, result.stdout + result.stderr
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            version = await connection.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname='vector'")
            )
            indexes = set(
                (
                    await connection.execute(
                        text(
                            "SELECT indexname FROM pg_indexes WHERE tablename='knowledge_chunks'"
                        )
                    )
                ).scalars()
            )
        assert version
        assert {
            "ix_knowledge_chunks_vector_hnsw",
            "ix_knowledge_chunks_search_gin",
        } <= indexes
    finally:
        await engine.dispose()


def test_postgres_idempotent_mutation_serializes_concurrent_requests():
    database_url = os.getenv("TEST_POSTGRES_URL", "").strip()
    if not database_url:
        pytest.skip(
            "Set TEST_POSTGRES_URL to a dedicated PostgreSQL 16 + pgvector database"
        )
    case_id = uuid.uuid4().hex
    environment = {**os.environ, "DATABASE_URL": database_url}
    migration = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert migration.returncode == 0, migration.stdout + migration.stderr
    program = f"""
import asyncio
from sqlalchemy import func, select
from src.api.server import (
    _begin_idempotent_mutation, _commit_idempotent_mutation, _mutation,
)
from src.core.audit import record_audit
from src.core.database import async_session
from src.core.models import (
    AuditEventModel, IdempotencyRecordModel, KnowledgeCollectionModel,
)

SCOPE = "postgres-race:{case_id}"
KEY = "race-key-{case_id}"
PAYLOAD = {{"name": "race-{case_id}"}}

async def mutate():
    async with async_session() as session:
        replay = await _begin_idempotent_mutation(
            session, scope=SCOPE, idempotency_key=KEY, request_payload=PAYLOAD,
        )
        if replay:
            return replay
        collection = KnowledgeCollectionModel(name=PAYLOAD["name"])
        session.add(collection)
        await session.flush()
        event = await record_audit(
            session, action="test.concurrent_mutation",
            resource_type="knowledge_collection", resource_id=collection.id,
        )
        response = _mutation(
            {{"id": collection.id, "name": collection.name}},
            collection.version, event.id,
        )
        return await _commit_idempotent_mutation(
            session, scope=SCOPE, idempotency_key=KEY,
            request_payload=PAYLOAD, response_payload=response,
            resource_id=collection.id,
        )

async def main():
    first, second = await asyncio.gather(mutate(), mutate())
    assert first["resource"]["id"] == second["resource"]["id"]
    assert first.get("replayed") or second.get("replayed")
    async with async_session() as session:
        collections = int(await session.scalar(select(func.count(
            KnowledgeCollectionModel.id
        )).where(KnowledgeCollectionModel.name == PAYLOAD["name"])) or 0)
        replays = int(await session.scalar(select(func.count(
            IdempotencyRecordModel.id
        )).where(IdempotencyRecordModel.scope == SCOPE)) or 0)
        audits = int(await session.scalar(select(func.count(
            AuditEventModel.id
        )).where(AuditEventModel.action == "test.concurrent_mutation")) or 0)
    assert (collections, replays, audits) == (1, 1, 1)

asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
