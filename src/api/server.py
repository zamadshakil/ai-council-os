"""
server.py — FastAPI Backend for AI Council OS

Exposes the LangGraph councils as REST API endpoints.
The Next.js dashboard communicates with this server.

Run with:
    uvicorn src.api.server:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.core.state import CouncilStatus, Priority


# ── App ──────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI Council OS",
    description="Multi-agent AI council system with debate-driven consensus",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── In-Memory Store (replaced by DB in production) ──────────────────────

tasks_store: dict[str, dict] = {}

# Seed with demo data
DEMO_TASKS = [
    {
        "task_id": "demo-001",
        "council": "sales",
        "status": "awaiting_approval",
        "task_description": "Cold outreach to Sarah Chen, CTO @ DataFlow Inc.",
        "final_output": (
            "Hi Sarah,\n\n"
            "Congrats on the Series B — $25M is a serious vote of confidence "
            "in what DataFlow is building for real-time pipelines.\n\n"
            "As you scale the team past 150, support ticket volume tends to "
            "spike 3-4x. We've helped similar B2B SaaS companies automate "
            "60% of L1 support with AI — without sacrificing CSAT.\n\n"
            "Would a 15-min walkthrough be worth your time this week?\n\n"
            "Best,\nHassan"
        ),
        "confidence_score": 88.5,
        "iterations": 2,
        "total_cost_usd": 0.0142,
        "debate_history": [
            {
                "role": "generator",
                "model": "gpt-4.1",
                "content": "Generated initial cold outreach draft focusing on the prospect's recent Series B funding and scaling challenges.",
                "confidence_score": 0,
                "timestamp": "2026-07-20T10:00:00Z",
            },
            {
                "role": "critic",
                "model": "claude-sonnet-5",
                "content": "PERSONALIZATION: 7/10 — Good funding reference but no mention of their data pipeline product.\nVALUE PROP: 6/10 — Too vague. '60% automation' needs a proof point.\nTONE: 8/10 — Natural, not robotic.\nCTA: 7/10 — '15-min walkthrough' is fine but could be more specific.\nLENGTH: 9/10 — Concise.\n\nCONFIDENCE: 72/100",
                "confidence_score": 72,
                "timestamp": "2026-07-20T10:00:05Z",
            },
            {
                "role": "generator",
                "model": "gpt-4.1",
                "content": "Revised draft with specific reference to real-time data pipelines and a more concrete value proposition.",
                "confidence_score": 0,
                "timestamp": "2026-07-20T10:00:10Z",
            },
            {
                "role": "critic",
                "model": "claude-sonnet-5",
                "content": "PERSONALIZATION: 9/10 — References their specific product focus.\nVALUE PROP: 8/10 — '60% L1 automation' with CSAT preservation is compelling.\nTONE: 9/10 — Feels human-written.\nCTA: 9/10 — Low-friction ask.\nLENGTH: 9/10 — Perfect.\n\nCONFIDENCE: 88.5/100",
                "confidence_score": 88.5,
                "timestamp": "2026-07-20T10:00:15Z",
            },
            {
                "role": "synthesizer",
                "model": "gpt-4.1",
                "content": "Final version synthesized from V2 draft with all critic feedback addressed.",
                "confidence_score": 0,
                "timestamp": "2026-07-20T10:00:20Z",
            },
        ],
        "created_at": "2026-07-20T10:00:00Z",
        "context": {
            "prospect_name": "Sarah Chen",
            "prospect_title": "CTO",
            "company": "DataFlow Inc.",
            "funding": "Series B, $25M",
            "company_size": "~150 employees",
        },
    },
    {
        "task_id": "demo-002",
        "council": "content",
        "status": "awaiting_approval",
        "task_description": "LinkedIn post about AI automation trends for Q3 2026",
        "final_output": (
            "The AI automation landscape in Q3 2026 is shifting fast.\n\n"
            "3 trends I'm watching:\n\n"
            "1. Multi-agent systems replacing single-prompt workflows\n"
            "2. Voice-first interfaces becoming the default input method\n"
            "3. AI councils (yes, plural AIs debating) outperforming solo models\n\n"
            "The companies winning right now aren't using AI as a tool.\n"
            "They're building AI organizations.\n\n"
            "What trend are you most excited about? 👇"
        ),
        "confidence_score": 91.0,
        "iterations": 1,
        "total_cost_usd": 0.0089,
        "debate_history": [
            {
                "role": "generator",
                "model": "gpt-4.1",
                "content": "Generated LinkedIn post on AI automation trends.",
                "confidence_score": 0,
                "timestamp": "2026-07-20T11:00:00Z",
            },
            {
                "role": "critic",
                "model": "claude-sonnet-5",
                "content": "Strong hook, good structure, engaging CTA. CONFIDENCE: 91/100",
                "confidence_score": 91.0,
                "timestamp": "2026-07-20T11:00:05Z",
            },
            {
                "role": "synthesizer",
                "model": "gpt-4.1",
                "content": "Minor polish on point 3 for clarity.",
                "confidence_score": 0,
                "timestamp": "2026-07-20T11:00:10Z",
            },
        ],
        "created_at": "2026-07-20T11:00:00Z",
        "context": {},
    },
    {
        "task_id": "demo-003",
        "council": "grant",
        "status": "awaiting_approval",
        "task_description": "Executive summary for EU Horizon grant — AI in healthcare diagnostics",
        "final_output": (
            "Executive Summary\n\n"
            "This proposal addresses the critical need for early-stage diagnostic "
            "support in resource-limited healthcare settings across the European Union...\n\n"
            "[Full grant summary would appear here — typically 500-1000 words]"
        ),
        "confidence_score": 82.0,
        "iterations": 3,
        "total_cost_usd": 0.0456,
        "debate_history": [],
        "created_at": "2026-07-20T12:00:00Z",
        "context": {},
    },
]

for task in DEMO_TASKS:
    tasks_store[task["task_id"]] = task


# ── Request/Response Models ──────────────────────────────────────────────

class RunCouncilRequest(BaseModel):
    council: str  # "sales", "content", "grant", "strategy"
    task_description: str
    context: dict[str, Any] = Field(default_factory=dict)
    priority: str = "high"


class ApprovalRequest(BaseModel):
    approved: bool
    edited_output: str = ""
    notes: str = ""


class TaskResponse(BaseModel):
    task_id: str
    council: str
    status: str
    task_description: str
    final_output: str
    confidence_score: float
    iterations: int
    total_cost_usd: float
    debate_history: list[dict]
    created_at: str
    context: dict = Field(default_factory=dict)


# ── Endpoints ────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"service": "AI Council OS", "version": "0.1.0", "status": "running"}


@app.get("/api/tasks")
async def list_tasks(status: str | None = None, council: str | None = None):
    """List all tasks, optionally filtered by status or council."""
    tasks = list(tasks_store.values())

    if status:
        tasks = [t for t in tasks if t["status"] == status]
    if council:
        tasks = [t for t in tasks if t["council"] == council]

    # Sort by created_at descending
    tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return {"tasks": tasks, "total": len(tasks)}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    """Get a specific task by ID."""
    task = tasks_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.post("/api/tasks/{task_id}/approve")
async def approve_task(task_id: str, request: ApprovalRequest):
    """Approve or reject a pending task."""
    task = tasks_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task["status"] != "awaiting_approval":
        raise HTTPException(status_code=400, detail="Task is not pending approval")

    task["status"] = "approved" if request.approved else "rejected"
    if request.edited_output:
        task["final_output"] = request.edited_output
    task["feedback_notes"] = request.notes

    return {"task_id": task_id, "status": task["status"]}


@app.post("/api/councils/run")
async def run_council(request: RunCouncilRequest):
    """Submit a new task to a council."""
    task_id = str(uuid.uuid4())[:8]

    # In production, this triggers the actual LangGraph council
    # For now, return a placeholder
    new_task = {
        "task_id": task_id,
        "council": request.council,
        "status": "pending",
        "task_description": request.task_description,
        "final_output": "",
        "confidence_score": 0,
        "iterations": 0,
        "total_cost_usd": 0,
        "debate_history": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "context": request.context,
    }

    tasks_store[task_id] = new_task
    return {"task_id": task_id, "status": "pending", "message": "Council is processing..."}


@app.get("/api/stats")
async def get_stats():
    """Dashboard analytics."""
    tasks = list(tasks_store.values())
    total = len(tasks)
    pending = len([t for t in tasks if t["status"] == "awaiting_approval"])
    approved = len([t for t in tasks if t["status"] == "approved"])
    rejected = len([t for t in tasks if t["status"] == "rejected"])
    total_cost = sum(t.get("total_cost_usd", 0) for t in tasks)
    avg_confidence = (
        sum(t.get("confidence_score", 0) for t in tasks) / total if total > 0 else 0
    )

    # Per-council breakdown
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
