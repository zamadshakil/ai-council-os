"""
database.py — PostgreSQL + pgvector Database Layer

Replaces in-memory tasks_store with persistent PostgreSQL.
Uses pgvector for semantic memory (replacing ChromaDB).

Tables:
- tasks: All council tasks (Reddit leads, YouTube replies, content variants, etc.)
- seen_items: Deduplication store (replaces SQLite dedup.py for production)
- embeddings: Vector store for knowledge base (replaces ChromaDB)
- kill_switch: Global kill switch state
"""

import os
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import json

from sqlalchemy import (
    Column, String, Float, Integer, Boolean, Text, DateTime,
    JSON, create_engine, text as sql_text
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")

# Auto-detect: if no DB URL set, use SQLite for local dev
if not DATABASE_URL:
    os.makedirs("./data", exist_ok=True)
    DATABASE_URL = "sqlite+aiosqlite:///./data/council_os.db"
    print("[Database] Using SQLite (local dev). Set DATABASE_URL for PostgreSQL in production.")
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "asyncpg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)



class Base(DeclarativeBase):
    pass


# ── Models ───────────────────────────────────────────────────────────────

class TaskModel(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    council: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(50), index=True, default="pending")
    task_description: Mapped[str] = mapped_column(Text, default="")
    final_output: Mapped[str] = mapped_column(Text, default="")
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    iterations: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    debate_history: Mapped[dict] = mapped_column(JSON, default=list)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    feedback_notes: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self) -> dict:
        created_iso = ""
        if self.created_at:
            dt = self.created_at if self.created_at.tzinfo else self.created_at.replace(tzinfo=timezone.utc)
            created_iso = dt.isoformat()
            if not created_iso.endswith("Z") and "+" not in created_iso:
                created_iso += "Z"

        return {
            "task_id": self.task_id,
            "council": self.council,
            "status": self.status,
            "task_description": self.task_description,
            "final_output": self.final_output,
            "confidence_score": self.confidence_score,
            "iterations": self.iterations,
            "total_cost_usd": self.total_cost_usd,
            "debate_history": self.debate_history or [],
            "context": self.context or {},
            "feedback_notes": self.feedback_notes or "",
            "error": self.error or "",
            "created_at": created_iso,
        }


class SeenItemModel(Base):
    __tablename__ = "seen_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[str] = mapped_column(String(255), index=True)
    source: Mapped[str] = mapped_column(String(100), index=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    metadata_text: Mapped[str] = mapped_column(Text, default="")


class KillSwitchModel(Base):
    __tablename__ = "kill_switch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    toggled_by: Mapped[str] = mapped_column(String(100), default="system")
    toggled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    reason: Mapped[str] = mapped_column(Text, default="")

class WorkflowSettingsModel(Base):
    __tablename__ = "workflow_settings"

    workflow_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    custom_prompt: Mapped[str] = mapped_column(Text, default="")
    selected_docs: Mapped[str] = mapped_column(JSON, default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


# ── Database Initialization ──────────────────────────────────────────────

async def init_db():
    """Create all tables. Call during FastAPI startup."""
    async with engine.begin() as conn:
        # Enable pgvector extension (PostgreSQL only, skip for SQLite)
        if "postgresql" in DATABASE_URL:
            await conn.execute(sql_text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    # Remove legacy demo/sample tasks that were previously auto-seeded into
    # production. These were placeholder rows (fake models, fake proposals)
    # that showed up mixed with real client data and must never reappear.
    legacy_demo_ids = [
        "task-sales-01", "task-support-01", "task-content-01",
        "task-content-02", "task-grant-01", "task-strategy-01",
    ]
    async with async_session() as session:
        from sqlalchemy import delete
        await session.execute(delete(TaskModel).where(TaskModel.task_id.in_(legacy_demo_ids)))
        await session.commit()

    print("[Database] Tables initialized.")




# ── CRUD Operations ──────────────────────────────────────────────────────

async def create_task(task_data: dict) -> dict:
    """Insert a new task into the database with fallback."""
    try:
        async with async_session() as session:
            task = TaskModel(**{
                k: v for k, v in task_data.items()
                if k in TaskModel.__table__.columns.keys()
            })
            session.add(task)
            await session.commit()
            await session.refresh(task)
            return task.to_dict()
    except Exception as e:
        print(f"[Database Warning] Failed to insert task into DB: {e}. Using in-memory store.")
        if "created_at" not in task_data:
            task_data["created_at"] = datetime.now(timezone.utc).isoformat() + "Z"
        return task_data


async def get_task(task_id: str) -> Optional[dict]:
    """Get a single task by ID."""
    from sqlalchemy import select
    async with async_session() as session:
        result = await session.execute(
            select(TaskModel).where(TaskModel.task_id == task_id)
        )
        task = result.scalar_one_or_none()
        return task.to_dict() if task else None


async def list_tasks(status: Optional[str] = None, council: Optional[str] = None) -> List[dict]:
    """List tasks with optional filters."""
    from sqlalchemy import select
    async with async_session() as session:
        query = select(TaskModel)
        if status:
            query = query.where(TaskModel.status == status)
        if council:
            query = query.where(TaskModel.council == council)
        query = query.order_by(TaskModel.created_at.desc())

        result = await session.execute(query)
        tasks = result.scalars().all()
        return [t.to_dict() for t in tasks]


async def update_task(task_id: str, updates: dict) -> Optional[dict]:
    """Update a task's fields."""
    from sqlalchemy import select
    async with async_session() as session:
        result = await session.execute(
            select(TaskModel).where(TaskModel.task_id == task_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            return None
        for key, value in updates.items():
            if hasattr(task, key):
                setattr(task, key, value)
        task.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(task)
        return task.to_dict()


async def get_stats() -> dict:
    """Get dashboard statistics."""
    from sqlalchemy import select, func
    async with async_session() as session:
        tasks = await list_tasks()
        total = len(tasks)
        pending = len([t for t in tasks if t["status"] == "awaiting_approval"])
        approved = len([t for t in tasks if t["status"] == "approved"])
        rejected = len([t for t in tasks if t["status"] == "rejected"])
        total_cost = sum(t.get("total_cost_usd", 0) for t in tasks)
        avg_confidence = (
            sum(t.get("confidence_score", 0) for t in tasks) / total if total > 0 else 0
        )

        councils = {}
        for t in tasks:
            c = t["council"]
            if c not in councils:
                councils[c] = {"tasks": 0, "cost": 0, "avg_confidence": 0, "scores": []}
            councils[c]["tasks"] += 1
            councils[c]["cost"] += t.get("total_cost_usd", 0)
            councils[c]["scores"].append(t.get("confidence_score", 0))

        for c in councils.values():
            c["avg_confidence"] = sum(c["scores"]) / len(c["scores"]) if c["scores"] else 0
            del c["scores"]

        return {
            "total_tasks": total,
            "pending": pending,
            "approved": approved,
            "rejected": rejected,
            "total_cost_usd": round(total_cost, 4),
            "avg_confidence": round(avg_confidence, 1),
            "councils": councils,
        }


# ── Dedup Operations ─────────────────────────────────────────────────────

async def is_seen_db(item_id: str, source: str) -> bool:
    """Check if an item has been processed."""
    from sqlalchemy import select, and_
    async with async_session() as session:
        result = await session.execute(
            select(SeenItemModel).where(
                and_(SeenItemModel.item_id == item_id, SeenItemModel.source == source)
            )
        )
        return result.scalar_one_or_none() is not None


async def mark_seen_db(item_id: str, source: str, metadata: str = ""):
    """Mark an item as processed."""
    async with async_session() as session:
        existing = await is_seen_db(item_id, source)
        if not existing:
            session.add(SeenItemModel(item_id=item_id, source=source, metadata_text=metadata))
            await session.commit()


# ── Kill Switch Operations ───────────────────────────────────────────────

async def get_kill_switch_db() -> dict:
    """Get kill switch status from DB."""
    from sqlalchemy import select
    async with async_session() as session:
        result = await session.execute(select(KillSwitchModel).where(KillSwitchModel.id == 1))
        ks = result.scalar_one_or_none()
        if ks:
            return {
                "is_active": ks.is_active,
                "toggled_by": ks.toggled_by,
                "toggled_at": ks.toggled_at.isoformat() if ks.toggled_at else "",
                "reason": ks.reason or "",
            }
        return {"is_active": False, "toggled_by": "system", "toggled_at": "", "reason": ""}


async def set_kill_switch_db(is_active: bool, toggled_by: str = "system", reason: str = ""):
    async with async_session() as session:
        from sqlalchemy import select
        res = await session.execute(select(KillSwitchModel).where(KillSwitchModel.id == 1))
        ks = res.scalar_one_or_none()
        if not ks:
            ks = KillSwitchModel(id=1, is_active=is_active, toggled_by=toggled_by, reason=reason)
            session.add(ks)
        else:
            ks.is_active = is_active
            ks.toggled_by = toggled_by
            ks.toggled_at = datetime.now(timezone.utc)
            ks.reason = reason
        await session.commit()

# ── Workflow Settings ────────────────────────────────────────────────────

async def get_workflow_settings(workflow_id: str) -> dict:
    """Get settings for a specific workflow."""
    async with async_session() as session:
        from sqlalchemy import select
        res = await session.execute(select(WorkflowSettingsModel).where(WorkflowSettingsModel.workflow_id == workflow_id))
        settings = res.scalar_one_or_none()
        if settings:
            return {
                "workflow_id": settings.workflow_id,
                "custom_prompt": settings.custom_prompt,
                "selected_docs": json.loads(settings.selected_docs) if settings.selected_docs else []
            }
        return {"workflow_id": workflow_id, "custom_prompt": "", "selected_docs": []}

async def set_workflow_settings(workflow_id: str, custom_prompt: str, selected_docs: list[str]):
    """Set settings for a specific workflow."""
    async with async_session() as session:
        from sqlalchemy import select
        res = await session.execute(select(WorkflowSettingsModel).where(WorkflowSettingsModel.workflow_id == workflow_id))
        settings = res.scalar_one_or_none()
        if not settings:
            settings = WorkflowSettingsModel(
                workflow_id=workflow_id,
                custom_prompt=custom_prompt,
                selected_docs=json.dumps(selected_docs)
            )
            session.add(settings)
        else:
            settings.custom_prompt = custom_prompt
            settings.selected_docs = json.dumps(selected_docs)
            settings.updated_at = datetime.now(timezone.utc)
        await session.commit()
