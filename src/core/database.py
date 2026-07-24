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
            "created_at": self.created_at.isoformat() if self.created_at else "",
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


# ── Database Initialization ──────────────────────────────────────────────

async def init_db():
    """Create all tables. Call during FastAPI startup."""
    async with engine.begin() as conn:
        # Enable pgvector extension (PostgreSQL only, skip for SQLite)
        if "postgresql" in DATABASE_URL:
            await conn.execute(sql_text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    # Seed initial sample tasks if database is empty
    async with async_session() as session:
        from sqlalchemy import select, func
        count_res = await session.execute(select(func.count(TaskModel.task_id)))
        if count_res.scalar() == 0:
            await _seed_mock_data(session)

    print("[Database] Tables initialized.")


async def _seed_mock_data(session):
    """Seeds rich sample tasks for demonstration if the database is brand new."""
    now = datetime.now(timezone.utc)
    sample_tasks = [
        TaskModel(
            task_id="task-sales-01",
            council="sales",
            status="awaiting_approval",
            task_description="High-Intent Lead Prospecting on r/SaaS: 'Looking for an AI platform to automate support tickets'",
            final_output="Hey @dev_founder_99! For automating support ticket triage and multi-channel responses, AI Council OS is built specifically for this. It runs a 3-stage consensus debate (Generator -> Critic -> Synthesizer) before proposing a response to your team's dashboard for 1-click approval. Happy to share a quick live demo!",
            confidence_score=94.5,
            iterations=2,
            total_cost_usd=0.0412,
            context={
                "subreddit": "SaaS",
                "author": "dev_founder_99",
                "intent_score": 0.94,
                "workflow": "reddit_prospector",
                "title": "Looking for an AI platform to automate support tickets"
            },
            debate_history=[
                {"role": "generator", "model": "GPT-4o", "content": "Drafted initial outreach focusing on features and price.", "timestamp": now.isoformat()},
                {"role": "critic", "model": "Claude 3.5 Sonnet", "content": "Critique: Response sounds slightly overly salesy. Recommend emphasizing human-in-the-loop safety and 1-click approval.", "confidence_score": 0.94, "timestamp": now.isoformat()},
                {"role": "synthesizer", "model": "GPT-4o", "content": "Synthesized balanced, helpful reply addressing the founder's exact pain point with zero fluff.", "timestamp": now.isoformat()}
            ],
            created_at=now,
        ),
        TaskModel(
            task_id="task-support-01",
            council="support",
            status="awaiting_approval",
            task_description="YouTube Comment Reply: 'Can this integration handle webhooks and real-time alerts on Telegram?'",
            final_output="Great question! Yes — the system includes a built-in Telegram notifier that sends real-time approval alerts whenever a new task is generated or approved, as well as instant kill-switch notifications. You can also hook custom webhooks into the FastAPI endpoints!",
            confidence_score=91.0,
            iterations=1,
            total_cost_usd=0.0185,
            context={
                "video_title": "Building Autonomous AI Councils in Python",
                "video_id": "v_781920",
                "comment_id": "c_99812",
                "original_comment": "Can this integration handle webhooks and real-time alerts on Telegram?",
                "workflow": "youtube_comments"
            },
            debate_history=[
                {"role": "generator", "model": "GPT-4o", "content": "Generated reply confirming Telegram notification capabilities.", "timestamp": now.isoformat()},
                {"role": "critic", "model": "Claude 3.5 Sonnet", "content": "Approved. Technical accuracy verified against architecture specs.", "confidence_score": 0.91, "timestamp": now.isoformat()}
            ],
            created_at=now,
        ),
        TaskModel(
            task_id="task-content-01",
            council="content",
            status="awaiting_approval",
            task_description="Bulk Description Update for Video: 'Mastering LangGraph Multi-Agent Workflows'",
            final_output="In this video, we deep dive into building production-ready multi-agent architectures using LangGraph and FastAPI.\n\n--- KEY TIMESTAMPS ---\n0:00 Introduction & Architecture Overview\n3:45 Setting up the Generator-Critic Loop\n8:20 Human-in-the-Loop Dashboard Integration\n14:10 Live Deployment on Hostinger VPS\n\n--- RESOURCES & LINKS ---\n🌐 Website: https://council-os.dev\n📄 Documentation: https://docs.council-os.dev\n💬 Discord Community: https://discord.gg/council-os",
            confidence_score=88.0,
            iterations=2,
            total_cost_usd=0.0350,
            context={
                "video_title": "Mastering LangGraph Multi-Agent Workflows",
                "video_id": "v_102938",
                "workflow": "youtube_descriptions"
            },
            debate_history=[
                {"role": "generator", "model": "GPT-4o", "content": "Preserved opening paragraph and updated standard links section.", "timestamp": now.isoformat()},
                {"role": "critic", "model": "Claude 3.5 Sonnet", "content": "Verified timestamps match audio outline.", "confidence_score": 0.88, "timestamp": now.isoformat()}
            ],
            created_at=now,
        ),
        TaskModel(
            task_id="task-content-02",
            council="content",
            status="awaiting_approval",
            task_description="Multi-Platform Variant Generation: 'AI Council OS Announcement Video'",
            final_output="🚀 Excited to announce AI Council OS — the first multi-agent AI operating system built for teams that demand human oversight.\n\nWhy traditional AI automations fail: They operate blindly without validation.\n\nHow AI Council OS fixes this:\n1️⃣ Generator agent drafts the response\n2️⃣ Critic agent validates facts & tone\n3️⃣ Synthesizer produces final output\n4️⃣ Human approves via 1-click Dashboard\n\nFull open-source repo & walkthrough available now!",
            confidence_score=96.0,
            iterations=3,
            total_cost_usd=0.0620,
            context={
                "platform": "linkedin",
                "platform_name": "LinkedIn",
                "workflow": "content_engine"
            },
            debate_history=[
                {"role": "generator", "model": "GPT-4o", "content": "Drafted initial post for LinkedIn audience.", "timestamp": now.isoformat()},
                {"role": "critic", "model": "Claude 3.5 Sonnet", "content": "Format optimized with line breaks and emoji bullet points.", "confidence_score": 0.96, "timestamp": now.isoformat()}
            ],
            created_at=now,
        ),
        TaskModel(
            task_id="task-grant-01",
            council="grant",
            status="approved",
            task_description="Draft Executive Summary for $50k Web3 Ecosystem Infrastructure Grant",
            final_output="Executive Summary: AI Council OS proposes an open-source decentralized agent orchestrator enabling reliable multi-LLM debate loops. Funding will cover core SDK development, pgvector memory persistence, and standardized API integrations.",
            confidence_score=92.0,
            iterations=2,
            total_cost_usd=0.0780,
            context={
                "grant_body": "Web3 Foundation",
                "amount": "$50,000"
            },
            debate_history=[
                {"role": "generator", "model": "GPT-4o", "content": "Drafted grant proposal alignment with Web3 roadmap.", "timestamp": now.isoformat()},
                {"role": "critic", "model": "Claude 3.5 Sonnet", "content": "Strengthened technical deliverable metrics.", "confidence_score": 0.92, "timestamp": now.isoformat()}
            ],
            created_at=now,
        ),
        TaskModel(
            task_id="task-strategy-01",
            council="strategy",
            status="approved",
            task_description="Q3 Competitive Positioning Analysis: AI Agents vs Single-Prompt Automation",
            final_output="Strategic Insight: Position AI Council OS as 'The Trust Engine for Enterprise AI'. While single-prompt tools have a 35% hallucination rate in production, multi-agent debate reduces errors below 3% while keeping human approval mandatory.",
            confidence_score=89.5,
            iterations=2,
            total_cost_usd=0.0540,
            context={
                "market_segment": "Enterprise SaaS Automation"
            },
            debate_history=[
                {"role": "generator", "model": "GPT-4o", "content": "Analyzed market positioning against single-prompt automation.", "timestamp": now.isoformat()},
                {"role": "critic", "model": "Claude 3.5 Sonnet", "content": "Validated enterprise error reduction stats.", "confidence_score": 0.895, "timestamp": now.isoformat()}
            ],
            created_at=now,
        )
    ]
    session.add_all(sample_tasks)
    await session.commit()
    print("[Database] Seeded 6 initial sample tasks for demonstration.")


# ── CRUD Operations ──────────────────────────────────────────────────────

async def create_task(task_data: dict) -> dict:
    """Insert a new task into the database."""
    async with async_session() as session:
        task = TaskModel(**{
            k: v for k, v in task_data.items()
            if k in TaskModel.__table__.columns.keys()
        })
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task.to_dict()


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


async def set_kill_switch_db(is_active: bool, toggled_by: str = "dashboard", reason: str = ""):
    """Set kill switch state in DB."""
    from sqlalchemy import select
    async with async_session() as session:
        result = await session.execute(select(KillSwitchModel).where(KillSwitchModel.id == 1))
        ks = result.scalar_one_or_none()
        if ks:
            ks.is_active = is_active
            ks.toggled_by = toggled_by
            ks.toggled_at = datetime.now(timezone.utc)
            ks.reason = reason
        else:
            session.add(KillSwitchModel(
                id=1, is_active=is_active, toggled_by=toggled_by, reason=reason
            ))
        await session.commit()
