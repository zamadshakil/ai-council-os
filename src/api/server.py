"""
server.py — FastAPI Backend for AI Council OS

Exposes the LangGraph councils as REST API endpoints.
The Next.js dashboard communicates with this server.
Uses PostgreSQL + pgvector for persistent storage.

Run with:
    uvicorn src.api.server:app --reload --port 8000
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.core.state import CouncilStatus, Priority
from src.core.scheduler import start_scheduler, set_tasks_store
from src.core import kill_switch
from src.core.database import (
    init_db, create_task, get_task, list_tasks as db_list_tasks,
    update_task, get_stats as db_get_stats,
    get_kill_switch_db, set_kill_switch_db,
)
from src.integrations.youtube import post_comment_reply, update_video_description
from src.integrations.reddit import post_reddit_reply
from src.integrations.telegram_bot import notify_publish_success


# ── App ──────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI Council OS",
    description="Multi-agent AI council system with debate-driven consensus",
    version="0.2.0",
)

# In-memory cache (synced with DB, used by scheduler for quick access)
tasks_store: dict[str, dict] = {}


@app.on_event("startup")
async def startup_event():
    """Initialize database and start background schedulers."""
    print("[FastAPI] Booting up...")
    await init_db()

    # Load existing tasks from DB into memory cache
    existing = await db_list_tasks()
    for t in existing:
        tasks_store[t["task_id"]] = t

    set_tasks_store(tasks_store)
    start_scheduler()
    print(f"[FastAPI] Loaded {len(tasks_store)} tasks from DB. All systems online.")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
@app.get("/healthz")
async def health_check():
    return {"status": "online", "system": "AI Council OS", "version": "0.2.0"}



import os
import hmac
import hashlib
import json
import base64
from fastapi import Header, Depends


# ── Security & Authentication Config ────────────────────────────────────
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "zakaria")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "councils@2026")
JWT_SECRET = os.getenv("JWT_SECRET", "ai-council-os-secure-token-secret-2026")


def create_auth_token(username: str) -> str:
    """Create a signed HMAC token for authenticated user session."""
    payload = {
        "username": username,
        "exp": int(datetime.now(timezone.utc).timestamp()) + 86400 * 30  # 30 days valid
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    sig = hmac.new(JWT_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_auth_token(authorization: Optional[str] = Header(None)) -> dict:
    """Verify Authorization Bearer token."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication token required")
    
    token = authorization.replace("Bearer ", "").strip()
    try:
        parts = token.split(".")
        if len(parts) != 2:
            raise HTTPException(status_code=401, detail="Invalid token format")
        
        payload_b64, sig = parts[0], parts[1]
        expected_sig = hmac.new(JWT_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            raise HTTPException(status_code=401, detail="Invalid token signature")
        
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode()).decode())
        if payload.get("exp", 0) < int(datetime.now(timezone.utc).timestamp()):
            raise HTTPException(status_code=401, detail="Token has expired")
        
        return payload
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=401, detail="Token verification failed")


# ── Request/Response Models ──────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class RunCouncilRequest(BaseModel):
    council: str
    task_description: str
    context: dict[str, Any] = Field(default_factory=dict)
    priority: str = "high"


class ApprovalRequest(BaseModel):
    approved: bool
    edited_output: str = ""
    notes: str = ""


class ContentEngineRequest(BaseModel):
    video_title: str
    transcript: str
    video_id: str = ""
    metadata: dict = Field(default_factory=dict)


# ── Auth Endpoints ───────────────────────────────────────────────────────

@app.post("/api/auth/login")
async def api_login(request: LoginRequest):
    """Authenticate user with username and password."""
    env_user = os.getenv("ADMIN_USERNAME", "zakaria")
    env_pass = os.getenv("ADMIN_PASSWORD", "councils@2026")
    
    if request.username == env_user and request.password == env_pass:
        token = create_auth_token(request.username)
        return {
            "status": "success",
            "token": token,
            "user": {
                "username": request.username,
                "name": "Zakaria",
                "role": "Admin",
                "email": "zakaria@councilos.ai",
                "avatar": "/avatar-zakaria.png"
            }
        }
    
    raise HTTPException(status_code=401, detail="Invalid username or password")


@app.get("/api/auth/me")
async def api_get_current_user(token_data: dict = Depends(verify_auth_token)):
    """Return authenticated user profile."""
    return {
        "username": token_data.get("username", "zakaria"),
        "name": "Zakaria",
        "role": "Admin",
        "email": "zakaria@councilos.ai",
        "status": "authenticated"
    }


# ── Core Task Endpoints ─────────────────────────────────────────────────

@app.get("/")
async def root():
    ks = await get_kill_switch_db()
    return {
        "service": "AI Council OS",
        "version": "0.2.0",
        "status": "running",
        "kill_switch": ks["is_active"],
        "tasks_loaded": len(tasks_store),
    }


@app.get("/api/tasks")
async def api_list_tasks(status: str | None = None, council: str | None = None):
    """List all tasks, optionally filtered by status or council."""
    tasks = await db_list_tasks(status=status, council=council)
    return {"tasks": tasks, "total": len(tasks)}


@app.get("/api/tasks/{task_id}")
async def api_get_task(task_id: str):
    """Get a specific task by ID."""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.post("/api/tasks/{task_id}/approve")
async def approve_task(task_id: str, request: ApprovalRequest):
    """Approve or reject a pending task. Triggers real API actions on approval."""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    allowed_statuses = {"pending", "generating", "critiquing", "refining", "awaiting_approval"}
    if task["status"] not in allowed_statuses and task["status"] != "approved" and task["status"] != "rejected":
        raise HTTPException(status_code=400, detail="Task cannot be modified")

    new_status = "approved" if request.approved else "rejected"
    updates = {"status": new_status, "feedback_notes": request.notes}
    if request.edited_output:
        updates["final_output"] = request.edited_output

    await update_task(task_id, updates)
    # Update memory cache
    task.update(updates)
    tasks_store[task_id] = task

    # Execute real integration actions on approval
    if request.approved:
        output = updates.get("final_output", task["final_output"])
        workflow = task.get("context", {}).get("workflow", "")

        try:
            if workflow == "youtube_comments" and "comment_id" in task.get("context", {}):
                post_comment_reply(task["context"]["comment_id"], output)
                await notify_publish_success("YouTube Reply", "YouTube",
                    f"Comment: {task['context']['comment_id']}")

            elif workflow == "reddit_prospector" and "id" in task.get("context", {}):
                post_reddit_reply(task["context"]["id"], output)
                await notify_publish_success("Reddit Reply", "Reddit",
                    f"Post: {task['context'].get('title', '')[:50]}")

            elif workflow == "youtube_descriptions" and "video_id" in task.get("context", {}):
                update_video_description(task["context"]["video_id"], output)
                await notify_publish_success("Description Update", "YouTube",
                    f"Video: {task['context'].get('video_title', '')[:50]}")

            elif workflow == "content_engine" and "platform" in task.get("context", {}):
                platform = task["context"].get("platform_name", task["context"]["platform"])
                await notify_publish_success("Content Engine", platform)

        except Exception as e:
            await update_task(task_id, {"status": "failed", "error": str(e)})
            tasks_store[task_id]["status"] = "failed"
            return {"task_id": task_id, "status": "failed", "error": str(e)}

    return {"task_id": task_id, "status": new_status}


import asyncio

_background_tasks: set[asyncio.Task] = set()


async def _process_council_task(task_id: str, council_name: str, description: str, context: dict, priority: str):
    """Executes the multi-agent debate loop via OpenRouter in the background."""
    try:
        c_name = council_name.lower()
        if c_name == "sales":
            from src.councils.sales.council import SalesCouncil
            council = SalesCouncil()
        elif c_name == "content":
            from src.councils.content.council import ContentCouncil
            council = ContentCouncil()
        elif c_name == "grant":
            from src.councils.grant.council import GrantCouncil
            council = GrantCouncil()
        elif c_name == "strategy":
            from src.councils.strategy.council import StrategyCouncil
            council = StrategyCouncil()
        elif c_name == "support":
            from src.councils.support.council import SupportCouncil
            council = SupportCouncil()
        else:
            from src.councils.sales.council import SalesCouncil
            council = SalesCouncil()

        res = await council.graph.ainvoke({
            "task_description": description,
            "context": context,
            "priority": priority,
        })

        updates = {
            "status": "awaiting_approval",
            "final_output": res.get("final_output", ""),
            "confidence_score": float(res.get("confidence_score", 90.0)),
            "iterations": int(res.get("iteration", 1)),
            "total_cost_usd": float(res.get("total_cost_usd", 0.02)),
            "debate_history": res.get("debate_history", []),
        }

        await update_task(task_id, updates)
        if task_id in tasks_store:
            tasks_store[task_id].update(updates)
        print(f"[Council Success] Task {task_id} processed by {council_name} council.")

    except Exception as e:
        print(f"[Council Error] Task {task_id} failed: {e}")
        await update_task(task_id, {"status": "failed", "error": str(e)})
        if task_id in tasks_store:
            tasks_store[task_id]["status"] = "failed"
            tasks_store[task_id]["error"] = str(e)


@app.post("/api/councils/run")
async def run_council(request: RunCouncilRequest):
    """Submit a new task to a council."""
    task_id = str(uuid.uuid4())[:8]

    task_data = {
        "task_id": task_id,
        "council": request.council,
        "status": "pending",
        "task_description": request.task_description,
        "final_output": "",
        "confidence_score": 0,
        "iterations": 0,
        "total_cost_usd": 0,
        "debate_history": [],
        "context": request.context,
    }

    saved = await create_task(task_data)
    tasks_store[task_id] = saved

    # Trigger background multi-agent AI debate via OpenRouter
    bg_task = asyncio.create_task(
        _process_council_task(
            task_id=task_id,
            council_name=request.council,
            description=request.task_description,
            context=request.context,
            priority=request.priority,
        )
    )
    _background_tasks.add(bg_task)
    bg_task.add_done_callback(_background_tasks.discard)

    return {"task_id": task_id, "status": "pending", "message": "Council AI agents are executing debate loop..."}


@app.get("/api/stats")
async def api_get_stats():
    """Dashboard analytics."""
    return await db_get_stats()


# ── Workflow Trigger Endpoints ───────────────────────────────────────────

@app.post("/api/workflows/reddit-prospector")
async def trigger_reddit_prospector():
    """Manually trigger the Reddit Lead Prospector."""
    from src.workflows.reddit_prospector import run_reddit_prospector
    result = await run_reddit_prospector(tasks_store)
    # Sync any new tasks to DB
    await _sync_new_tasks_to_db()
    return result


@app.post("/api/workflows/youtube-comments")
async def trigger_youtube_comments():
    """Manually trigger YouTube Comment Auto-Reply."""
    from src.workflows.youtube_comments import run_youtube_comment_workflow
    result = await run_youtube_comment_workflow(tasks_store)
    await _sync_new_tasks_to_db()
    return result


@app.post("/api/workflows/youtube-descriptions")
async def trigger_youtube_descriptions(boilerplate: str = ""):
    """Trigger YouTube Description Updater (Phase 1: Generate)."""
    from src.workflows.youtube_descriptions import run_description_generator
    result = await run_description_generator(tasks_store, boilerplate=boilerplate)
    await _sync_new_tasks_to_db()
    return result


@app.post("/api/workflows/youtube-descriptions/publish")
async def trigger_publish_descriptions():
    """Trigger Phase 2: Publish approved descriptions."""
    from src.workflows.youtube_descriptions import publish_approved_descriptions
    result = await publish_approved_descriptions(tasks_store)
    return result


@app.post("/api/workflows/content-engine")
async def trigger_content_engine(request: ContentEngineRequest):
    """Trigger Multi-Platform Content Engine."""
    from src.workflows.content_engine import run_content_engine
    result = await run_content_engine(
        video_title=request.video_title,
        transcript=request.transcript,
        video_id=request.video_id,
        tasks_store=tasks_store,
        metadata=request.metadata,
    )
    await _sync_new_tasks_to_db()
    return result


# ── Kill Switch Endpoints ────────────────────────────────────────────────

@app.get("/api/kill-switch")
async def api_get_kill_switch():
    """Get current kill switch state."""
    return await get_kill_switch_db()


@app.post("/api/kill-switch/activate")
async def api_activate_kill_switch(reason: str = "Activated via Dashboard"):
    """Activate kill switch — all workflows stop."""
    await set_kill_switch_db(True, toggled_by="dashboard", reason=reason)
    kill_switch.activate(toggled_by="dashboard", reason=reason)
    return {"status": "activated", "message": "All workflows stopped."}


@app.post("/api/kill-switch/deactivate")
async def api_deactivate_kill_switch():
    """Deactivate kill switch — workflows resume."""
    await set_kill_switch_db(False, toggled_by="dashboard")
    kill_switch.deactivate(toggled_by="dashboard")
    return {"status": "deactivated", "message": "Workflows resumed."}


# ── Helpers ──────────────────────────────────────────────────────────────

async def _sync_new_tasks_to_db():
    """Sync any new tasks from memory cache to the database."""
    existing_ids = {t["task_id"] for t in await db_list_tasks()}
    for task_id, task_data in tasks_store.items():
        if task_id not in existing_ids:
            try:
                await create_task(task_data)
            except Exception:
                pass  # Already exists or constraint error
