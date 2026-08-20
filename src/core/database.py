"""Async database runtime and legacy-compatible persistence helpers.

PostgreSQL is production-only and must be migrated explicitly with Alembic.
SQLite remains a zero-configuration local-development option.
"""

from __future__ import annotations

import json
import os
from typing import Any, List, Optional

from dotenv import load_dotenv
from sqlalchemy import delete, event, inspect, select, text as sql_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.models import *  # noqa: F403 - compatibility exports are intentional
from src.core import integration_models as _integration_models  # noqa: F401

load_dotenv()


def normalize_database_url(raw_url: str | None) -> str:
    if not raw_url:
        os.makedirs("./data", exist_ok=True)
        return "sqlite+aiosqlite:///./data/council_os.db"
    if raw_url.startswith("postgres://"):
        return raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
    if raw_url.startswith("postgresql://") and "+asyncpg" not in raw_url:
        return raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw_url


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL"))
engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
    """Make SQLite development behavior match PostgreSQL referential actions."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


if DATABASE_URL.startswith("sqlite"):
    event.listen(engine.sync_engine, "connect", _enable_sqlite_foreign_keys)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

SQLITE_REQUIRED_COLUMNS = {
    "tasks": {"version"},
    "knowledge_documents": {
        "raw_content", "normalized_text", "metadata_json",
        "extraction_warnings", "indexing_version", "embedding_model", "version",
    },
    "knowledge_chunks": {
        "document_id", "source_start", "source_end", "parent_key",
        "index_version", "embedding_model",
    },
}


def missing_sqlite_columns(local_columns: dict[str, set[str]]) -> dict[str, list[str]]:
    """Return every required column missing from a local development schema."""
    return {
        table: sorted(columns - local_columns.get(table, set()))
        for table, columns in SQLITE_REQUIRED_COLUMNS.items()
        if columns - local_columns.get(table, set())
    }


async def init_db() -> None:
    """Create a local schema or verify that production migrations ran.

    This function intentionally does not create or alter production tables.
    The release command for PostgreSQL is ``alembic upgrade head``.
    """
    if DATABASE_URL.startswith("sqlite"):
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)  # noqa: F405
            def inspect_local_schema(sync_connection: Any) -> dict[str, set[str]]:
                inspector = inspect(sync_connection)
                table_names = set(inspector.get_table_names())
                return {
                    table: {
                        column["name"] for column in inspector.get_columns(table)
                    } if table in table_names else set()
                    for table in SQLITE_REQUIRED_COLUMNS
                }

            local_columns = await connection.run_sync(inspect_local_schema)
        missing_columns = missing_sqlite_columns(local_columns)
        if missing_columns:
            details = "; ".join(
                f"{table}: {', '.join(columns)}"
                for table, columns in sorted(missing_columns.items())
            )
            raise RuntimeError(
                "The local SQLite database uses a legacy schema; run `alembic upgrade head` "
                f"once before starting the application (missing columns: {details})."
            )
    else:
        required = {
            "alembic_version", "users", "sessions", "workflow_runs", "audit_events",
            "knowledge_documents", "knowledge_chunks", "knowledge_collections",
            "knowledge_binding_states", "brain_entities", "brain_facts", "skills", "mcp_tokens",
            "render_jobs", "render_frames", "render_telemetry", "render_artifacts",
        }

        def table_names(sync_connection: Any) -> set[str]:
            return set(inspect(sync_connection).get_table_names())

        async with engine.connect() as connection:
            present = await connection.run_sync(table_names)
        missing = sorted(required - present)
        if missing:
            raise RuntimeError(
                "Production database is not migrated; run `alembic upgrade head` "
                f"before startup (missing: {', '.join(missing)})."
            )

    legacy_demo_ids = [
        "task-sales-01", "task-support-01", "task-content-01",
        "task-content-02", "task-grant-01", "task-strategy-01",
    ]
    async with async_session() as session:
        await session.execute(delete(TaskModel).where(TaskModel.task_id.in_(legacy_demo_ids)))  # noqa: F405
        await session.commit()


async def database_ready() -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(sql_text("SELECT 1"))
        return True
    except Exception:
        return False


async def create_task(task_data: dict[str, Any]) -> dict[str, Any]:
    """Persist a task or raise; durable state never falls back to memory."""
    async with async_session() as session:
        task = TaskModel(**{  # noqa: F405
            key: value for key, value in task_data.items()
            if key in TaskModel.__table__.columns  # noqa: F405
        })
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task.to_dict()


async def get_task(task_id: str) -> Optional[dict[str, Any]]:
    async with async_session() as session:
        task = await session.get(TaskModel, task_id)  # noqa: F405
        return task.to_dict() if task else None


async def list_tasks(status: Optional[str] = None, council: Optional[str] = None) -> List[dict]:
    async with async_session() as session:
        query = select(TaskModel)  # noqa: F405
        if status:
            query = query.where(TaskModel.status == status)  # noqa: F405
        if council:
            query = query.where(TaskModel.council == council)  # noqa: F405
        result = await session.execute(query.order_by(TaskModel.created_at.desc()))  # noqa: F405
        return [task.to_dict() for task in result.scalars().all()]


async def update_task(task_id: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
    async with async_session() as session:
        task = await session.get(TaskModel, task_id)  # noqa: F405
        if not task:
            return None
        allowed = set(TaskModel.__table__.columns.keys()) - {"task_id", "created_at"}  # noqa: F405
        for key, value in updates.items():
            if key in allowed:
                setattr(task, key, value)
        task.version += 1
        task.updated_at = utcnow()  # noqa: F405
        await session.commit()
        await session.refresh(task)
        return task.to_dict()


async def get_stats() -> dict[str, Any]:
    tasks = await list_tasks()
    total = len(tasks)
    councils: dict[str, dict[str, Any]] = {}
    for task in tasks:
        bucket = councils.setdefault(task["council"], {
            "tasks": 0, "cost": 0.0, "scores": [], "cost_metrics_complete": True,
        })
        bucket["tasks"] += 1
        if task.get("cost_metrics_complete"):
            bucket["cost"] += task.get("total_cost_usd") or 0.0
        else:
            bucket["cost_metrics_complete"] = False
        if task.get("confidence_score") is not None:
            bucket["scores"].append(float(task["confidence_score"]))
    for bucket in councils.values():
        scores = bucket.pop("scores")
        bucket["avg_confidence"] = sum(scores) / len(scores) if scores else None
    scored = [
        float(task["confidence_score"])
        for task in tasks if task.get("confidence_score") is not None
    ]
    complete_costs = [
        float(task.get("total_cost_usd") or 0.0)
        for task in tasks if task.get("cost_metrics_complete")
    ]
    return {
        "total_tasks": total,
        "pending": sum(task["status"] == "awaiting_approval" for task in tasks),
        "approved": sum(task["status"] == "approved" for task in tasks),
        "rejected": sum(task["status"] == "rejected" for task in tasks),
        "total_cost_usd": round(sum(complete_costs), 4),
        "cost_metrics_complete": len(complete_costs) == total,
        "avg_confidence": round(sum(scored) / len(scored), 1) if scored else None,
        "councils": councils,
    }


async def is_seen_db(item_id: str, source: str) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(SeenItemModel.id).where(  # noqa: F405
                SeenItemModel.item_id == item_id, SeenItemModel.source == source  # noqa: F405
            )
        )
        return result.scalar_one_or_none() is not None


async def mark_seen_db(item_id: str, source: str, metadata: str = "") -> bool:
    async with async_session() as session:
        session.add(SeenItemModel(item_id=item_id, source=source, metadata_text=metadata))  # noqa: F405
        try:
            await session.commit()
            return True
        except IntegrityError:
            await session.rollback()
            return False


async def get_kill_switch_db() -> dict[str, Any]:
    async with async_session() as session:
        switch = await session.get(KillSwitchModel, 1)  # noqa: F405
        if not switch:
            return {"is_active": False, "toggled_by": "system", "toggled_at": "", "reason": ""}
        return {
            "is_active": switch.is_active, "toggled_by": switch.toggled_by,
            "toggled_at": iso(switch.toggled_at), "reason": switch.reason or "",  # noqa: F405
        }


async def set_kill_switch_db(
    is_active: bool, toggled_by: str = "system", reason: str = ""
) -> dict[str, Any]:
    async with async_session() as session:
        switch = await session.get(KillSwitchModel, 1)  # noqa: F405
        if not switch:
            switch = KillSwitchModel(id=1)  # noqa: F405
            session.add(switch)
        switch.is_active = is_active
        switch.toggled_by = toggled_by
        switch.toggled_at = utcnow()  # noqa: F405
        switch.reason = reason
        await session.commit()
        return {
            "is_active": switch.is_active, "toggled_by": switch.toggled_by,
            "toggled_at": iso(switch.toggled_at), "reason": switch.reason,  # noqa: F405
        }


async def get_workflow_settings(workflow_id: str) -> dict[str, Any]:
    async with async_session() as session:
        settings = await session.get(WorkflowSettingsModel, workflow_id)  # noqa: F405
        if not settings:
            return {"workflow_id": workflow_id, "custom_prompt": "", "selected_docs": []}
        selected = settings.selected_docs or []
        if isinstance(selected, str):
            try:
                selected = json.loads(selected)
            except json.JSONDecodeError:
                selected = []
        return {
            "workflow_id": workflow_id, "custom_prompt": settings.custom_prompt,
            "selected_docs": selected,
        }


async def set_workflow_settings(
    workflow_id: str, custom_prompt: str, selected_docs: list[str]
) -> dict[str, Any]:
    async with async_session() as session:
        settings = await session.get(WorkflowSettingsModel, workflow_id)  # noqa: F405
        if not settings:
            settings = WorkflowSettingsModel(workflow_id=workflow_id)  # noqa: F405
            session.add(settings)
        settings.custom_prompt = custom_prompt
        settings.selected_docs = list(selected_docs)
        settings.updated_at = utcnow()  # noqa: F405
        await session.commit()
        return {
            "workflow_id": workflow_id, "custom_prompt": custom_prompt,
            "selected_docs": list(selected_docs),
        }
