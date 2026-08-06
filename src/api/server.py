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

from fastapi import FastAPI, HTTPException, Query, Request, UploadFile, File
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
    ABANDONED_STATUSES = {"pending", "generating", "critiquing", "refining"}
    for t in existing:
        if t.get("status") in ABANDONED_STATUSES:
            # A server restart kills any in-flight debate loop mid-execution.
            # Without this, the task sits forever showing "AI agents debating"
            # even though nothing is actually running anymore.
            fixed = {
                **t,
                "status": "failed",
                "error": "Task was abandoned by a server restart before it finished. Use Retry to resubmit.",
            }
            try:
                await update_task(t["task_id"], {"status": fixed["status"], "error": fixed["error"]})
            except Exception as cleanup_err:
                print(f"[Startup Cleanup] Failed to mark {t['task_id']} as failed: {cleanup_err}")
            tasks_store[t["task_id"]] = fixed
        else:
            tasks_store[t["task_id"]] = t

    set_tasks_store(tasks_store)
    start_scheduler()

    # Start Telegram control bot
    try:
        from src.integrations.telegram_bot import start_telegram_bot_async
        import asyncio
        asyncio.create_task(start_telegram_bot_async())
        print("[FastAPI] Telegram bot initialized.")
    except Exception as e:
        print(f"[FastAPI] Telegram bot initialization skipped: {e}")

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
# ADMIN_PASSWORD and JWT_SECRET must be set via environment. There is no
# hardcoded fallback for either — this codebase is on a client-visible
# GitHub repo, so a hardcoded default here would be a public secret.
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()

if not ADMIN_PASSWORD:
    raise ValueError("ADMIN_PASSWORD environment variable is not set on the server.")
if not JWT_SECRET:
    raise ValueError("JWT_SECRET environment variable is not set on the server.")


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
    env_user = ADMIN_USERNAME
    env_pass = ADMIN_PASSWORD
    
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
    db_tasks = await db_list_tasks(status=status, council=council)
    
    # Merge with in-memory tasks_store to ensure zero data loss
    combined = {t["task_id"]: t for t in db_tasks}
    for tid, tdict in tasks_store.items():
        if tid not in combined:
            if status and status != "all" and tdict.get("status") != status:
                continue
            if council and tdict.get("council") != council:
                continue
            combined[tid] = tdict

    tasks_list = list(combined.values())
    tasks_list.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"tasks": tasks_list, "total": len(tasks_list)}


@app.get("/api/tasks/{task_id}")
async def api_get_task(task_id: str):
    """Get a specific task by ID with in-memory fallback."""
    task = await get_task(task_id)
    if not task:
        task = tasks_store.get(task_id)
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

    # Store in episodic memory (learn from this outcome)
    try:
        from src.core.memory_manager import store_episode
        await store_episode(
            council=task.get("council", "unknown"),
            task_summary=task.get("task_description", "")[:400],
            output_summary=(updates.get("final_output") or task.get("final_output", ""))[:400],
            outcome=new_status,
            feedback_notes=request.notes,
            confidence=float(task.get("confidence_score", 0.0)),
        )
    except Exception as mem_err:
        print(f"[Memory] Episode storage failed (non-fatal): {mem_err}")

    # Multi-platform publishing is opt-in through the persisted task context.
    # Approval alone never silently publishes content to an external platform.
    if request.approved:
        publish_platforms = task.get("context", {}).get("publish_to", [])
        if publish_platforms:
            try:
                from src.integrations.publisher import publish_to_platforms
                output = updates.get("final_output") or task.get("final_output", "")
                media_url = task.get("context", {}).get("media_url")
                asyncio.create_task(publish_to_platforms(output, publish_platforms, media_url))
            except Exception as pub_err:
                print(f"[Publisher] Publish trigger failed (non-fatal): {pub_err}")

        # Best-effort HubSpot sync for approved Sales Council outreach.
        # Safe no-op until HUBSPOT_ACCESS_TOKEN is configured.
        if task.get("council") == "sales":
            try:
                from src.integrations.hubspot import sync_approved_sales_task
                sync_result = await sync_approved_sales_task({**task, **updates})
                if sync_result.get("status") != "skipped":
                    print(f"[HubSpot] Task {task_id} sync result: {sync_result}")
            except Exception as hubspot_err:
                print(f"[HubSpot] Sync failed (non-fatal): {hubspot_err}")

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

        final_state = {}
        async for chunk in council.graph.astream({
            "task_description": description,
            "context": context,
            "priority": priority,
        }):
            for node_name, node_state in chunk.items():
                final_state.update(node_state)
                
                # Determine current status based on node
                step_status = "generating"
                if node_name == "_critique" or node_name == "critique":
                    step_status = "critiquing"
                elif node_name == "_synthesize" or node_name == "synthesize":
                    step_status = "awaiting_approval"
                elif node_state.get("final_output"):
                    step_status = "awaiting_approval"

                partial_updates = {
                    "status": step_status,
                    "final_output": node_state.get("final_output", final_state.get("final_output", "")),
                    "confidence_score": float(node_state.get("confidence_score", final_state.get("confidence_score", 0.0))),
                    "iterations": int(node_state.get("iteration", final_state.get("iteration", 1))),
                    "total_cost_usd": float(node_state.get("total_cost_usd", final_state.get("total_cost_usd", 0.01))),
                    "debate_history": node_state.get("debate_history", final_state.get("debate_history", [])),
                }

                try:
                    await update_task(task_id, partial_updates)
                except Exception as stream_db_err:
                    print(f"[DB Stream Error] {stream_db_err}")

                if task_id in tasks_store:
                    tasks_store[task_id].update(partial_updates)

        # Final guarantee update
        final_updates = {
            "status": "awaiting_approval",
            "final_output": final_state.get("final_output", final_state.get("current_draft", "")),
            "confidence_score": float(final_state.get("confidence_score", 90.0)),
            "iterations": int(final_state.get("iteration", 1)),
            "total_cost_usd": float(final_state.get("total_cost_usd", 0.02)),
            "debate_history": final_state.get("debate_history", []),
        }

        await update_task(task_id, final_updates)
        if task_id in tasks_store:
            tasks_store[task_id].update(final_updates)

        # Every completed council task enters the same human approval queue in
        # both Telegram and the dashboard. Telegram-submitted tasks return to
        # the originating chat; dashboard tasks use configured destinations.
        try:
            from src.integrations.telegram_bot import send_draft_for_approval
            telegram_chat_id = context.get("telegram_chat_id")
            await send_draft_for_approval(
                task_id=task_id,
                workflow_name=f"{council_name.title()} Council",
                draft_text=final_updates["final_output"],
                context_summary=description,
                confidence=final_updates["confidence_score"],
                destination_chat_id=int(telegram_chat_id) if telegram_chat_id else None,
                council=council_name,
            )
        except Exception as telegram_error:
            print(f"[Telegram] Approval delivery failed for task {task_id}: {telegram_error}")

        print(f"[Council Success] Task {task_id} completed streaming by {council_name} council.")

    except Exception as e:
        print(f"[Council Error] Task {task_id} failed: {e}")
        try:
            await update_task(task_id, {"status": "failed", "error": str(e)})
        except Exception as db_e:
            print(f"[DB Error] Failed to update error column (schema might be old): {db_e}")
            try:
                # Fallback: just update status if 'error' column doesn't exist
                await update_task(task_id, {"status": "failed"})
            except Exception as inner_db_e:
                print(f"[DB Error] Critical failure updating task status: {inner_db_e}")
        
        if task_id in tasks_store:
            tasks_store[task_id]["status"] = "failed"
            tasks_store[task_id]["error"] = str(e)


@app.post("/api/councils/run")
async def run_council(request: RunCouncilRequest):
    """Submit a new task to a council."""
    if kill_switch.is_killed():
        raise HTTPException(
            status_code=423,
            detail="Global kill switch is active. Resume workflows before submitting a council task.",
        )

    allowed_councils = {"content", "sales", "grant", "strategy", "support"}
    if request.council.lower() not in allowed_councils:
        raise HTTPException(status_code=400, detail="Unknown council")

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

async def _sync_new_tasks_to_db():
    """
    Persist any workflow-created tasks that only exist in the in-memory
    tasks_store into the database, so they survive a server restart.

    Workflows (Reddit Prospector, YouTube, Content Engine) write directly
    to tasks_store for immediate dashboard visibility; this bridges that
    into permanent storage.
    """
    for task_id, task_data in list(tasks_store.items()):
        try:
            existing = await get_task(task_id)
            if existing is None:
                await create_task(task_data)
        except Exception as e:
            print(f"[Sync] Failed to sync task {task_id} to DB: {e}")


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


# ── Meta Real-Time Instagram Webhook Endpoints ─────────────────────────

VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "").strip()
if not VERIFY_TOKEN:
    print("[WARNING] META_VERIFY_TOKEN is not set — Instagram webhook verification will always fail until it's configured.")


@app.get("/api/webhooks/instagram")
async def verify_instagram_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
):
    """Meta Webhook Challenge Verification."""
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        print(f"[Instagram Webhook] Successfully verified with Meta challenge: {hub_challenge}")
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=hub_challenge)
    from fastapi import HTTPException
    raise HTTPException(status_code=403, detail="Verification token mismatch")


@app.post("/api/webhooks/instagram")
async def receive_instagram_webhook(request: Request):
    """Receive real-time comment notifications from Meta and reply instantly (< 5 sec)."""
    try:
        body = await request.json()
        print(f"[Instagram Webhook Payload Received]: {body}")

        # Kill switch check — must be respected by ALL workflows including webhooks
        from src.core.kill_switch import is_killed
        if is_killed():
            print("🛑 [Instagram Webhook] Kill switch active. Ignoring incoming comment.")
            return {"status": "killed", "message": "Kill switch active — comment ignored"}

        from src.integrations.instagram_commenter import handle_instant_webhook_comment

        # Parse Meta webhook entries
        entries = body.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                if change.get("field") == "comments":
                    value = change.get("value", {})
                    comment_id = value.get("id")
                    comment_text = value.get("text")
                    from_user = value.get("from", {}).get("username", "user")
                    media_id = value.get("media", {}).get("id", "")

                    if comment_id and comment_text:
                        # Process in background task immediately so Meta gets 200 OK within 2 seconds
                        asyncio.create_task(
                            handle_instant_webhook_comment(comment_id, comment_text, from_user, media_id)
                        )

        return {"status": "ok", "message": "Event received"}
    except Exception as e:
        print(f"[Instagram Webhook Error]: {e}")
        return {"status": "error", "error": str(e)}


@app.get("/api/workflows/{workflow_id}/details")
async def get_workflow_details_endpoint(workflow_id: str):
    """Get live connected account details and execution history for a workflow."""
    if workflow_id == "instagram-comments":
        from src.integrations.instagram_commenter import get_instagram_workflow_details
        return get_instagram_workflow_details()
    
    # Generic default for other workflows
    return {
        "id": workflow_id,
        "name": workflow_id.replace("-", " ").title(),
        "status": "active",
        "total_replied": 0,
        "activity_history": [],
    }


# Env vars each workflow genuinely needs to run for real (not just to draft
# with the LLM). Shown to the dashboard so "Active" never lies about whether
# a workflow can actually reach its external platform.
WORKFLOW_REQUIRED_ENV: dict[str, list[str]] = {
    "instagram-comments": ["INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_BUSINESS_ID"],
    "reddit": ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"],
    "youtube-comments": ["YOUTUBE_API_KEY", "YOUTUBE_CHANNEL_ID"],
    "youtube-descriptions": ["YOUTUBE_API_KEY", "YOUTUBE_CHANNEL_ID"],
    "content-engine": [],  # Drafting only needs the LLM; publishing is opt-in per platform.
}


@app.get("/api/tasks/{task_id}/export/docx")
async def export_task_docx(task_id: str):
    """Download a task's final output as a formatted Word document."""
    task = await get_task(task_id)
    if not task:
        task = tasks_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.get("final_output"):
        raise HTTPException(status_code=400, detail="Task has no final output yet")

    from src.integrations.docx_export import build_task_docx, build_task_docx_filename
    from fastapi.responses import Response

    file_bytes = build_task_docx(task)
    filename = build_task_docx_filename(task)
    return Response(
        content=file_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/integrations/status")
async def get_integrations_status():
    """Report real connection status for CRM/publishing integrations (no dummy data)."""
    from src.integrations.hubspot import get_hubspot_status
    from src.integrations.publisher import get_platform_status
    from src.core.llm_router import get_model_router_status

    return {
        "hubspot": get_hubspot_status(),
        "publishing": await get_platform_status(),
        "model_router": get_model_router_status(),
    }


@app.get("/api/workflows/config-status")
async def get_workflows_config_status():
    """
    Report, per workflow, whether the credentials it needs to actually run
    are configured on this server. Lets the dashboard show 'Needs Setup'
    instead of falsely claiming a workflow is Active.
    """
    result = {}
    for workflow_id, required_vars in WORKFLOW_REQUIRED_ENV.items():
        missing = [v for v in required_vars if not os.getenv(v, "").strip()]
        result[workflow_id] = {
            "ready": len(missing) == 0,
            "missing_env": missing,
        }
    return result

class WorkflowSettingsRequest(BaseModel):
    custom_prompt: str
    selected_docs: list[str]

@app.get("/api/workflows/{workflow_id}/settings")
async def get_workflow_settings_endpoint(workflow_id: str):
    """Get custom prompt and selected docs for a workflow."""
    from src.core.database import get_workflow_settings
    return await get_workflow_settings(workflow_id)

@app.post("/api/workflows/{workflow_id}/settings")
async def update_workflow_settings_endpoint(workflow_id: str, settings: WorkflowSettingsRequest):
    """Update custom prompt and selected docs for a workflow."""
    from src.core.database import set_workflow_settings
    await set_workflow_settings(workflow_id, settings.custom_prompt, settings.selected_docs)
    return {"status": "success", "message": "Workflow settings saved."}



@app.post("/api/workflows/instagram-comments")
async def trigger_instagram_commenter():
    """Manually trigger Instagram Comment Auto-Reply workflow (Client Priority #1)."""
    from src.integrations.instagram_commenter import run_instagram_commenter
    asyncio.create_task(run_instagram_commenter(tasks_store))
    return {
        "status": "started",
        "workflow": "instagram-comments",
        "message": "Instagram comment auto-reply workflow triggered! AI is fetching comments and generating replies."
    }


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


# ── Knowledge Base (RAG) Endpoints ─────────────────────────────────────────

@app.post("/api/knowledge/upload")
async def upload_knowledge_document(file: UploadFile = File(...)):
    """Upload a document to the RAG knowledge base."""
    from src.core.rag_engine import ingest_document
    file_bytes = await file.read()
    result = await ingest_document(file_bytes, file.filename)
    return result


@app.get("/api/knowledge/search")
async def search_knowledge(q: str = ""):
    """Search the RAG knowledge base."""
    from src.core.rag_engine import search_knowledge_base
    if not q.strip():
        return {"results": []}
    results = await search_knowledge_base(q, top_k=5)
    return {"results": results, "query": q}


@app.get("/api/knowledge/documents")
async def list_knowledge_documents():
    """List all ingested documents."""
    from src.core.rag_engine import get_all_documents
    docs = await get_all_documents()
    return {"documents": docs, "total": len(docs)}


@app.delete("/api/knowledge/documents/{doc_hash}")
async def delete_knowledge_document(doc_hash: str):
    """Remove a document from the knowledge base."""
    from src.core.rag_engine import delete_document
    success = await delete_document(doc_hash)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "deleted", "doc_hash": doc_hash}


@app.get("/api/memory/preferences")
async def get_memory_preferences():
    """Get stored brand guidelines and preferences."""
    try:
        import sqlite3
        conn = sqlite3.connect("./data/memory.db")
        conn.execute("CREATE TABLE IF NOT EXISTS guidelines (id INTEGER PRIMARY KEY AUTOINCREMENT, guideline TEXT, created_at TEXT DEFAULT (datetime('now')))")
        rows = conn.execute("SELECT id, guideline, created_at FROM guidelines ORDER BY created_at DESC").fetchall()
        conn.close()
        return {"guidelines": [{"id": r[0], "guideline": r[1], "created_at": r[2]} for r in rows]}
    except Exception as e:
        return {"guidelines": [], "error": str(e)}


class GuidelineRequest(BaseModel):
    guideline: str


@app.post("/api/memory/guidelines")
async def add_brand_guideline(request: GuidelineRequest):
    """Add a brand guideline to the memory store."""
    import sqlite3
    conn = sqlite3.connect("./data/memory.db")
    conn.execute("CREATE TABLE IF NOT EXISTS guidelines (id INTEGER PRIMARY KEY AUTOINCREMENT, guideline TEXT, created_at TEXT DEFAULT (datetime('now')))")
    conn.execute("INSERT INTO guidelines (guideline) VALUES (?)", (request.guideline,))
    conn.commit()
    conn.close()
    return {"status": "saved", "guideline": request.guideline}


# ── Helpers ──────────────────────────────────────────────────────────────

# ── Memory API Endpoints ─────────────────────────────────────────────────────

@app.get("/api/memory/stats")
async def api_memory_stats():
    """Memory system statistics."""
    from src.core.memory_manager import get_memory_stats
    return await get_memory_stats()


@app.get("/api/memory/episodes")
async def api_get_episodes(council: str = "all", outcome: str = "approved", limit: int = 10):
    """Get episodic memory entries."""
    from src.core.memory_manager import get_recent_episodes
    return {"episodes": await get_recent_episodes(council, outcome, limit)}


@app.post("/api/memory/preferences")
async def api_save_preference(key: str, value: str, council: str = "all"):
    """Save a brand preference."""
    from src.core.memory_manager import save_preference
    return await save_preference(key, value, council)


@app.delete("/api/memory/guidelines/{guideline_id}")
async def api_delete_guideline(guideline_id: int):
    """Delete a brand guideline."""
    from src.core.memory_manager import delete_guideline
    await delete_guideline(guideline_id)
    return {"status": "deleted", "id": guideline_id}


# ── Publisher API Endpoints ───────────────────────────────────────────────────

@app.get("/api/platforms/status")
async def api_platform_status():
    """Check which social platforms have credentials configured."""
    from src.integrations.publisher import get_platform_status
    return await get_platform_status()


class PublishRequest(BaseModel):
    content: str
    platforms: list[str]
    media_url: Optional[str] = None


@app.post("/api/publish")
async def api_publish(request: PublishRequest):
    """Publish content to one or more social platforms immediately."""
    from src.integrations.publisher import publish_to_platforms
    return await publish_to_platforms(request.content, request.platforms, request.media_url)


# ── RunPod GPU Pod Management Endpoints ──────────────────────────────

@app.get("/api/runpod/pods")
async def list_runpod_pods_endpoint():
    """List all active and paused RunPod GPU instances under configured API key."""
    try:
        from src.integrations.runpod_manager import list_user_pods
        pods = await list_user_pods()
        return {"status": "ok", "pods": pods}
    except Exception as e:
        return {"status": "error", "error": str(e), "pods": []}


@app.get("/api/runpod/pods/{pod_id}")
async def get_runpod_pod_endpoint(pod_id: str):
    """Get status, uptime, IP and GPU metrics for a specific pod."""
    try:
        from src.integrations.runpod_manager import get_pod_status
        pod = await get_pod_status(pod_id)
        return {"status": "ok", "pod": pod}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/api/runpod/pods/{pod_id}/start")
async def start_runpod_pod_endpoint(pod_id: str):
    """Start a paused RunPod instance (podStart)."""
    try:
        from src.integrations.runpod_manager import start_pod
        res = await start_pod(pod_id)
        return {"status": "ok", "result": res}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/api/runpod/pods/{pod_id}/stop")
async def stop_runpod_pod_endpoint(pod_id: str):
    """Stop/Pause a running RunPod instance (podStop) to prevent idle billing."""
    try:
        from src.integrations.runpod_manager import stop_pod
        res = await stop_pod(pod_id)
        return {"status": "ok", "result": res}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── MCP Server Mount ──────────────────────────────────────────────────────────

try:
    from src.core.mcp_server import mcp
    app.mount("/mcp", mcp.http_app())
    print("[MCP] FastMCP server mounted at /mcp")
except Exception as mcp_err:
    print(f"[MCP] Mount skipped (non-fatal): {mcp_err}")


