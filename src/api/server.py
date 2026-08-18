"""Secure production API for the three-council AI Council OS release."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import (
    Cookie, Depends, FastAPI, File, Header, HTTPException, Query, Request,
    Response, UploadFile,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from src.api.dependencies import (
    RequestActor,
    allowed_browser_origins,
    auth_service,
    require_admin,
    require_admin_or_telegram,
)
from src.api.middleware import SecurityHeadersMiddleware
from src.api.schemas import (
    ApprovalActionRequest, BlenderPodActionRequest, BlenderTemplateJobRequest,
    ContentEngineRequest, CouncilRunRequest,
    IntegrationCredentialsRequest, KillSwitchRequest, LegacyApprovalRequest,
    LoginRequest, WorkflowIntegrationLinksRequest, WorkflowPatchRequest,
    WorkflowTriggerRequest,
)
from src.core.approvals import (
    ApprovalConflict, ApprovalInvalidAction, ApprovalNotFound, ApprovalService,
)
from src.core.audit import record_audit
from src.core.database import (
    async_session, database_ready, get_kill_switch_db, get_stats, init_db,
    set_kill_switch_db,
)
from src.core.jobs import JobService
from src.core import integration_vault
from src.core.integration_context import use_integration_configuration
from src.core.integration_models import WorkflowIntegrationModel
from src.core.integration_credentials import (
    WORKFLOW_REQUIRED_ENV,
    workflow_credential_fingerprint,
)
from src.core.llm_router import validate_approved_models
from src.core.models import (
    ApprovalModel, CouncilRunModel, KnowledgeDocumentModel,
    PublicationAttemptModel, TaskModel, WorkflowDefinitionModel,
    WorkflowRunModel, iso, utcnow,
)
from src.core.security import (
    CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, AuthInvalidCredentials, AuthLocked,
)

PRODUCTION_COUNCILS = frozenset({"grant", "sales", "content"})
SCHEDULE_PRESETS: dict[str, dict[str, Any]] = {
    "manual": {"type": "manual", "preset": "manual"},
    "every_5_minutes": {
        "type": "interval", "seconds": 300, "preset": "every_5_minutes",
    },
    "every_15_minutes": {
        "type": "interval", "seconds": 900, "preset": "every_15_minutes",
    },
    "every_30_minutes": {
        "type": "interval", "seconds": 1800, "preset": "every_30_minutes",
    },
    "hourly": {"type": "interval", "seconds": 3600, "preset": "hourly"},
    "every_3_hours": {
        "type": "interval", "seconds": 10800, "preset": "every_3_hours",
    },
    "every_6_hours": {
        "type": "interval", "seconds": 21600, "preset": "every_6_hours",
    },
    "every_12_hours": {
        "type": "interval", "seconds": 43200, "preset": "every_12_hours",
    },
    "daily": {"type": "interval", "seconds": 86400, "preset": "daily"},
}
WORKFLOW_SCHEDULE_PRESETS: dict[str, tuple[str, ...]] = {
    "instagram_comments": (
        "every_5_minutes", "every_15_minutes", "every_30_minutes", "hourly", "manual",
    ),
    "youtube_comments": (
        "every_15_minutes", "every_30_minutes", "hourly", "every_6_hours", "manual",
    ),
    "reddit_prospector": (
        "hourly", "every_3_hours", "every_6_hours", "every_12_hours", "daily", "manual",
    ),
}
WORKFLOW_SPECS: dict[str, dict[str, Any]] = {
    "telegram_control": {
        "display_name": "Telegram Control & Approval",
        "schedule": dict(SCHEDULE_PRESETS["manual"]),
        "required_env": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_IDS", "INTERNAL_SERVICE_TOKEN"],
    },
    "youtube_comments": {
        "display_name": "YouTube Comment Replies",
        "schedule": dict(SCHEDULE_PRESETS["every_30_minutes"]),
        "required_env": ["YOUTUBE_API_KEY", "YOUTUBE_CHANNEL_ID", "YOUTUBE_OAUTH_TOKEN"],
    },
    "reddit_prospector": {
        "display_name": "Reddit Lead Prospector",
        "schedule": dict(SCHEDULE_PRESETS["hourly"]),
        "required_env": ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"],
    },
    "youtube_descriptions": {
        "display_name": "YouTube Description Updater",
        "schedule": dict(SCHEDULE_PRESETS["manual"]),
        "required_env": ["YOUTUBE_API_KEY", "YOUTUBE_CHANNEL_ID", "YOUTUBE_OAUTH_TOKEN"],
    },
    "content_engine": {
        "display_name": "Multi-Platform Content Engine",
        "schedule": dict(SCHEDULE_PRESETS["manual"]),
        "required_env": ["OPENROUTER_API_KEY"],
    },
    "instagram_comments": {
        "display_name": "Instagram Comment Replies",
        "schedule": dict(SCHEDULE_PRESETS["every_5_minutes"]),
        "required_env": ["OPENROUTER_API_KEY", "META_ACCESS_TOKEN", "INSTAGRAM_BUSINESS_ID"],
    },
}
PUBLISHER_ENV: dict[str, tuple[str, ...]] = {
    "twitter": (
        "TWITTER_API_KEY", "TWITTER_API_SECRET",
        "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_SECRET",
    ),
    "linkedin": ("LINKEDIN_ACCESS_TOKEN",),
    "facebook": ("FACEBOOK_PAGE_ID",),
    "instagram": ("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_BUSINESS_ID"),
    "discord": ("DISCORD_WEBHOOK_URL",),
}
MAX_KNOWLEDGE_BYTES = 20 * 1024 * 1024
ALLOWED_KNOWLEDGE_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
job_service = JobService()
approval_service = ApprovalService()


def _is_production() -> bool:
    return os.getenv("ENVIRONMENT", "development").strip().lower() == "production"


def _cookie_secure() -> bool:
    return _is_production() or os.getenv("APP_ORIGIN", "").lower().startswith("https://")


def _secure_configuration() -> tuple[str, str]:
    username = os.getenv("ADMIN_USERNAME", "admin").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "")
    if len(password) < 12 or password.lower().startswith(("change-me", "password")):
        raise RuntimeError("ADMIN_PASSWORD must be a newly rotated password of at least 12 characters")
    if _is_production():
        if len(os.getenv("INTERNAL_SERVICE_TOKEN", "").strip()) < 32:
            raise RuntimeError("INTERNAL_SERVICE_TOKEN must contain at least 32 random characters")
        if not os.getenv("APP_ORIGIN", "").strip().startswith("https://"):
            raise RuntimeError("APP_ORIGIN must be an HTTPS origin in production")
        integration_vault.validate_encryption_key()
    return username, password


async def _seed_workflows() -> None:
    async with async_session() as session:
        for workflow_id, spec in WORKFLOW_SPECS.items():
            if await session.get(WorkflowDefinitionModel, workflow_id) is None:
                session.add(WorkflowDefinitionModel(
                    id=workflow_id, display_name=spec["display_name"],
                    is_enabled=False, is_paused=False, schedule=spec["schedule"],
                    settings={}, credential_status="untested",
                ))
        await session.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    username, password = _secure_configuration()
    await auth_service.ensure_admin(
        username, password,
        rotate_password=os.getenv("ROTATE_ADMIN_PASSWORD_ON_STARTUP", "0") == "1",
    )
    await _seed_workflows()
    yield


docs_enabled = not _is_production()
app = FastAPI(
    title="AI Council OS", version="1.0.0",
    description="Approval-gated Grant, Sales, and Content councils",
    docs_url="/docs" if docs_enabled else None, redoc_url=None,
    openapi_url="/openapi.json" if docs_enabled else None, lifespan=lifespan,
)
app.add_middleware(SecurityHeadersMiddleware)
origins = sorted(allowed_browser_origins())
app.add_middleware(
    CORSMiddleware, allow_origins=origins, allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID", "Idempotency-Key"],
)
hosts = [v.strip() for v in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if v.strip()]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)


def _api_error(code_status: int, code: str, message: str, **details: Any) -> HTTPException:
    return HTTPException(code_status, detail={"code": code, "message": message, "details": details})


@app.exception_handler(HTTPException)
async def handle_http_error(_: Request, exc: HTTPException):
    error = exc.detail if isinstance(exc.detail, dict) and "code" in exc.detail else {
        "code": "HTTP_ERROR", "message": str(exc.detail), "details": {},
    }
    return JSONResponse(status_code=exc.status_code, content={"error": error}, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError):
    fields = [
        {key: value for key, value in error.items() if key not in {"ctx", "url"}}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"error": {
        "code": "VALIDATION_ERROR", "message": "Request validation failed",
        "details": {"fields": fields},
    }})


def _mutation(resource: dict[str, Any], version: int, audit_event_id: str, **extra: Any) -> dict[str, Any]:
    return {"resource": resource, "version": version, "audit_event_id": audit_event_id, **extra}


def _blender_job_resource(job: WorkflowRunModel) -> dict[str, Any]:
    payload = job.payload or {}
    result = job.result or {}
    return {
        "id": job.id,
        "status": job.status,
        "stage": str(result.get("stage") or job.status),
        "pod_id": str(payload.get("pod_id", "")),
        "source_path": str(payload.get("source_path", "")),
        "output_name": str(payload.get("output_name", "")),
        "frame": int(payload.get("frame", 1) or 1),
        "samples": int(payload.get("samples", 64) or 64),
        "resolution_percent": int(payload.get("resolution_percent", 25) or 25),
        "auto_stop": bool(payload.get("auto_stop", True)),
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "error": job.error or str(result.get("error", "")),
        "result": result,
        "version": job.version,
        "created_at": iso(job.created_at),
        "updated_at": iso(job.updated_at),
        "finished_at": iso(job.finished_at),
    }


def _missing_config(workflow_id: str) -> list[str]:
    missing: list[str] = []
    for name in WORKFLOW_SPECS[workflow_id]["required_env"]:
        value = os.getenv(name, "").strip()
        if not value or (name == "YOUTUBE_OAUTH_TOKEN" and not Path(value).is_file()):
            missing.append(name)
    return missing


def _publisher_fingerprint(platform: str) -> str:
    names = PUBLISHER_ENV[platform]
    values = [os.getenv(name, "").strip() for name in names]
    if platform == "linkedin":
        values.append(
            os.getenv("LINKEDIN_PERSON_ID", "").strip()
            or os.getenv("LINKEDIN_ORGANIZATION_ID", "").strip()
        )
    elif platform == "facebook":
        values.append(
            os.getenv("META_ACCESS_TOKEN", "").strip()
            or os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
        )
    if not all(values):
        return ""
    return hashlib.sha256("\0".join(values).encode()).hexdigest()


async def _publishing_health() -> dict[str, dict[str, Any]]:
    from src.integrations.publisher import get_platform_status

    configured = await get_platform_status()
    vault_connections = {
        item["id"]: item for item in await integration_vault.list_connections()
    }
    async with async_session() as session:
        definition = await session.get(WorkflowDefinitionModel, "content_engine")
    records = ((definition.settings or {}).get("publishing_verifications", {}) if definition else {})
    health: dict[str, dict[str, Any]] = {}
    for platform in PUBLISHER_ENV:
        provider = {
            "twitter": "x",
            "linkedin": "linkedin",
            "facebook": "meta",
            "instagram": "meta",
            "discord": "discord",
        }[platform]
        connection = vault_connections.get(provider, {})
        if connection.get("configured"):
            linked = "content_engine" in connection.get("linked_workflows", [])
            verified = connection.get("status") == "verified" and linked
            health[platform] = {
                "configured": True,
                "credential_status": (
                    "verified" if verified else "configured" if linked else "unlinked"
                ),
                "message": (
                    "Connection verified"
                    if verified
                    else "Link this connection to Content Engine"
                    if not linked
                    else connection.get("last_error") or "Not verified"
                ),
                "verified_at": connection.get("verified_at") or "",
            }
            continue
        record = records.get(platform, {}) if isinstance(records, dict) else {}
        fingerprint_matches = bool(
            record.get("credential_fingerprint")
            and hmac.compare_digest(
                str(record.get("credential_fingerprint")),
                _publisher_fingerprint(platform),
            )
        )
        verified = record.get("status") == "verified" and fingerprint_matches
        health[platform] = {
            "configured": bool(configured.get(platform)),
            "credential_status": (
                "verified" if verified else "configured" if configured.get(platform) else "missing"
            ),
            "message": (
                str(record.get("message", ""))
                if fingerprint_matches
                else "Credentials changed since the last verification"
                if record
                else "Not verified"
            ),
            "verified_at": str(record.get("verified_at", "")) if fingerprint_matches else "",
        }
    return health


def _workflow_job_json(run: WorkflowRunModel) -> dict[str, Any]:
    return {
        "id": run.id,
        "workflow_id": run.workflow_id,
        "job_type": run.job_type,
        "status": run.status,
        "attempts": run.attempts,
        "max_attempts": run.max_attempts,
        "priority": run.priority,
        "result": run.result or {},
        "error": run.error,
        "version": run.version,
        "created_at": iso(run.created_at),
        "updated_at": iso(run.updated_at),
        "started_at": iso(run.started_at),
        "finished_at": iso(run.finished_at),
    }


def _public_schedule(schedule: dict[str, Any]) -> dict[str, Any]:
    """Return only the simple scheduling contract exposed by the portal."""
    schedule_type = str(schedule.get("type", ""))
    if schedule_type == "manual":
        return dict(SCHEDULE_PRESETS["manual"])
    if schedule_type == "interval":
        seconds = schedule.get("seconds")
        if isinstance(seconds, int) and seconds > 0:
            for preset, configured in SCHEDULE_PRESETS.items():
                if configured.get("type") == "interval" and configured.get("seconds") == seconds:
                    return dict(configured)
        return {"type": "needs_update", "preset": ""}
    # Old installations may contain a cron expression. Never expose that
    # technical value in the user-facing API; saving a preset replaces it.
    return {"type": "needs_update", "preset": ""}


def _workflow_json(
    item: WorkflowDefinitionModel, last_run: WorkflowRunModel | None = None
) -> dict[str, Any]:
    settings = dict(item.settings or {})
    # Knowledge documents are selected per Grant Council run. Older workflow
    # rows may still contain this retired key, but it must never be exposed as
    # an active automation setting.
    settings.pop("selected_document_hashes", None)
    payload = {
        "id": item.id, "display_name": item.display_name,
        "is_enabled": item.is_enabled, "is_paused": item.is_paused,
        "schedule": _public_schedule(item.schedule or {}), "settings": settings,
        "credential_status": item.credential_status, "version": item.version,
        "missing_configuration": (
            [] if item.credential_status == "verified" else _missing_config(item.id)
        ), "updated_at": iso(item.updated_at),
    }
    if last_run is not None:
        payload["last_run"] = _workflow_job_json(last_run)
    return payload


async def _workflow_credentials_current(
    session, definition: WorkflowDefinitionModel
) -> bool:
    """Accept verified vault links or a still-current legacy env verification."""
    if definition.credential_status != "verified":
        return False
    linked = (await session.execute(
        select(WorkflowIntegrationModel.provider).where(
            WorkflowIntegrationModel.workflow_id == definition.id
        )
    )).scalars().first()
    if linked:
        # Vault credential rotation atomically marks linked definitions
        # untested and disabled. workflow_environment rechecks every linked
        # provider immediately before execution.
        return await integration_vault.workflow_connections_verified(definition.id)
    if definition.id not in WORKFLOW_REQUIRED_ENV:
        return True
    stored = str((definition.settings or {}).get("credential_fingerprint", ""))
    current = workflow_credential_fingerprint(definition.id)
    return bool(stored and current and hmac.compare_digest(stored, current))


def _run_json(run: CouncilRunModel) -> dict[str, Any]:
    return {
        "id": run.id, "task_id": run.task_id, "council": run.council,
        "status": run.status, "priority": run.priority, "prompt": run.prompt,
        "context": run.context or {}, "final_output": run.final_output or {},
        "confidence_score": run.confidence_score,
        "total_input_tokens": run.total_input_tokens,
        "total_output_tokens": run.total_output_tokens,
        "total_cost_usd": run.total_cost_usd, "warning": run.warning,
        "error": run.error, "version": run.version,
        "created_at": iso(run.created_at), "updated_at": iso(run.updated_at),
    }


def _task_json(task: TaskModel, approval: ApprovalModel | None = None) -> dict[str, Any]:
    payload = task.to_dict()
    payload.update({
        "approval_id": approval.id if approval else None,
        "approval_status": approval.status if approval else None,
        "approval_version": approval.version if approval else None,
    })
    return payload


async def _task_and_approval(task_id: str) -> tuple[TaskModel, ApprovalModel | None]:
    async with async_session() as session:
        task = await session.get(TaskModel, task_id)
        if task is None:
            raise _api_error(404, "TASK_NOT_FOUND", "Task does not exist")
        result = await session.execute(select(ApprovalModel).where(
            ApprovalModel.resource_type == "task", ApprovalModel.resource_id == task_id,
        ))
        return task, result.scalar_one_or_none()


@app.get("/")
@app.get("/healthz")
async def health_check():
    return {"status": "online", "service": "AI Council OS", "version": "1.0.0"}


@app.get("/readyz")
async def readiness_check():
    db_ok = await database_ready()
    try:
        models = await validate_approved_models()
    except Exception as exc:
        models = {"ready": False, "error": f"{type(exc).__name__}: {exc}"}
    ready = db_ok and bool(models.get("ready"))
    return JSONResponse(status_code=200 if ready else 503, content={"ready": ready, "database": db_ok, "models": models})


# Authentication
@app.post("/api/auth/login")
async def login(request: Request, response: Response, credentials: LoginRequest):
    try:
        created = await auth_service.authenticate(
            credentials.username, credentials.password,
            client_ip=request.client.host if request.client else "unknown",
            user_agent=request.headers.get("user-agent", ""),
        )
    except AuthLocked as exc:
        raise _api_error(429, exc.code, str(exc), retry_after_seconds=exc.retry_after_seconds) from exc
    except AuthInvalidCredentials as exc:
        raise _api_error(401, exc.code, str(exc)) from exc
    max_age = max(1, int((created.expires_at - utcnow()).total_seconds()))
    options = {"secure": _cookie_secure(), "samesite": "strict", "path": "/", "max_age": max_age}
    response.set_cookie(SESSION_COOKIE_NAME, created.session_token, httponly=True, **options)
    response.set_cookie(CSRF_COOKIE_NAME, created.csrf_token, httponly=False, **options)
    return {"status": "authenticated", "user": created.user, "csrf_token": created.csrf_token, "expires_at": iso(created.expires_at)}


@app.get("/api/auth/session")
@app.get("/api/auth/me", deprecated=True)
async def get_session(
    actor: RequestActor = Depends(require_admin),
    csrf_cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE_NAME),
):
    if actor.actor_type != "user":
        raise _api_error(401, "USER_SESSION_REQUIRED", "A dashboard user session is required")
    return {"authenticated": True, "user": {"id": actor.user_id, "username": actor.username, "role": actor.role}, "csrf_token": csrf_cookie or ""}


@app.post("/api/auth/logout")
async def logout(
    response: Response, actor: RequestActor = Depends(require_admin),
    token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    if actor.actor_type == "user" and token:
        await auth_service.revoke_session(token)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    return {"status": "logged_out"}


# Tasks and council runs
@app.get("/api/tasks")
async def list_tasks(
    task_status: str | None = Query(default=None, alias="status"),
    council: str | None = None, _: RequestActor = Depends(require_admin),
):
    async with async_session() as session:
        query = select(TaskModel, ApprovalModel).outerjoin(
            ApprovalModel,
            (ApprovalModel.resource_type == "task") & (ApprovalModel.resource_id == TaskModel.task_id),
        ).order_by(TaskModel.created_at.desc())
        if task_status and task_status != "all":
            query = query.where(TaskModel.status == task_status)
        if council and council != "all":
            query = query.where(TaskModel.council == council)
        rows = (await session.execute(query)).all()
    tasks = [_task_json(task, approval) for task, approval in rows]
    return {"tasks": tasks, "total": len(tasks)}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str, _: RequestActor = Depends(require_admin_or_telegram)):
    task, approval = await _task_and_approval(task_id)
    return _task_json(task, approval)


@app.post("/api/council-runs")
@app.post("/api/councils/run", deprecated=True)
async def create_council_run(
    payload: CouncilRunRequest, request: Request,
    actor: RequestActor = Depends(require_admin_or_telegram),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if (await get_kill_switch_db())["is_active"]:
        raise _api_error(423, "KILL_SWITCH_ACTIVE", "Global kill switch is active")
    if idempotency_key and not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", idempotency_key):
        raise _api_error(422, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key has an invalid format")
    job_key = f"council:{idempotency_key or uuid.uuid4()}"
    async with async_session() as session:
        existing = (await session.execute(select(WorkflowRunModel).where(WorkflowRunModel.idempotency_key == job_key))).scalar_one_or_none()
        if existing:
            task = await session.get(TaskModel, existing.payload.get("task_id"))
            if task:
                return _mutation(task.to_dict(), task.version, "", replayed=True, job_id=existing.id)
        task_id = str(uuid.uuid4())
        context = dict(payload.context)
        # Selected knowledge is accepted only through the validated hash list,
        # never through an arbitrary context object.
        context.pop("selected_docs", None)
        if payload.selected_document_hashes:
            context["selected_docs"] = payload.selected_document_hashes
        task = TaskModel(
            task_id=task_id, council=payload.council, status="queued",
            task_description=payload.task_description, context=context,
        )
        run = CouncilRunModel(
            task_id=task_id, council=payload.council, status="queued",
            priority=payload.priority, prompt=payload.task_description, context=context,
        )
        approval = ApprovalModel(
            resource_type="task",
            resource_id=task_id,
            status="awaiting_approval",
            version=1,
        )
        session.add_all([task, run, approval])
        await session.flush()
        context["run_id"] = run.id
        context["priority"] = payload.priority
        task.context = context
        run.context = context
        job = WorkflowRunModel(
            workflow_id=f"{payload.council}-council", job_type="council.run",
            payload={"task_id": task_id, "run_id": run.id, "council": payload.council,
                     "task_description": payload.task_description, "context": context,
                     "priority": payload.priority},
            idempotency_key=job_key,
            priority=10 if payload.priority == "high" else 0,
        )
        session.add(job)
        await session.flush()
        event = await record_audit(
            session, action="council_run.queued", resource_type="task", resource_id=task_id,
            actor_type=actor.actor_type, actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"run_id": run.id, "council": payload.council, "job_id": job.id},
        )
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise _api_error(409, "COUNCIL_RUN_CONFLICT", "Council run could not be queued") from exc
    return _mutation(task.to_dict(), task.version, event.id, run=_run_json(run), job_id=job.id)


@app.get("/api/council-runs")
async def list_council_runs(_: RequestActor = Depends(require_admin)):
    async with async_session() as session:
        runs = (await session.execute(select(CouncilRunModel).order_by(CouncilRunModel.created_at.desc()))).scalars().all()
    return {"runs": [_run_json(run) for run in runs], "total": len(runs)}


@app.get("/api/council-runs/{run_id}")
async def get_council_run(run_id: str, _: RequestActor = Depends(require_admin)):
    async with async_session() as session:
        run = await session.get(CouncilRunModel, run_id)
    if not run:
        raise _api_error(404, "COUNCIL_RUN_NOT_FOUND", "Council run does not exist")
    return _run_json(run)


@app.get("/api/stats")
async def stats(_: RequestActor = Depends(require_admin)):
    return await get_stats()


# Approval state machine
async def _queue_after_approval(task: TaskModel, approval: ApprovalModel, action: str) -> None:
    if action == "retry":
        job_key = f"retry:{approval.id}:{approval.version}"
        async with async_session() as session:
            existing = (await session.execute(
                select(WorkflowRunModel).where(WorkflowRunModel.idempotency_key == job_key)
            )).scalar_one_or_none()
            if existing:
                return
            current = await session.get(TaskModel, task.task_id, with_for_update=True)
            if not current:
                return
            context = {
                **(current.context or {}),
                "priority": (current.context or {}).get("priority", "normal"),
                "retry_of_run_id": (current.context or {}).get("run_id", ""),
            }
            run = CouncilRunModel(
                task_id=current.task_id,
                council=current.council,
                status="queued",
                priority=str(context["priority"]),
                prompt=current.task_description,
                context=context,
            )
            session.add(run)
            await session.flush()
            context["run_id"] = run.id
            run.context = context
            current.context = context
            current.status = "queued"
            current.error = ""
            current.final_output = ""
            current.confidence_score = None
            current.iterations = 0
            current.version += 1
            session.add(WorkflowRunModel(
                workflow_id=f"{current.council}-council",
                job_type="council.run",
                payload={
                    "task_id": current.task_id,
                    "run_id": run.id,
                    "council": current.council,
                    "task_description": current.task_description,
                    "context": context,
                    "priority": context["priority"],
                },
                idempotency_key=job_key,
                priority=10 if context["priority"] == "high" else 0,
            ))
            await session.commit()
        return
    if action != "approve":
        return
    await _queue_hubspot_after_sales_approval(task, approval)
    context, workflow = task.context or {}, (task.context or {}).get("workflow", "")
    if not workflow or workflow == "reddit_prospector" or (workflow == "content_engine" and context.get("platform") == "reddit"):
        if workflow:
            async with async_session() as session:
                current = await session.get(TaskModel, task.task_id)
                if current:
                    current.context = {**(current.context or {}), "manual_ready": True}
                    current.version += 1
                    await session.commit()
        return
    if workflow == "youtube_comments":
        job_type, platform = "publish.youtube_comment", "youtube"
    elif workflow == "instagram_comments":
        job_type, platform = "publish.instagram_comment", "instagram"
    elif workflow == "youtube_descriptions":
        job_type, platform = "publish.youtube_description", "youtube"
    elif workflow == "content_engine" and str(context.get("platform", "")).lower() in {"x", "twitter", "linkedin", "facebook", "instagram", "discord"}:
        job_type, platform = "publish.social", str(context["platform"]).lower()
    else:
        return
    key = f"publish:{approval.id}:{approval.version}"
    async with async_session() as session:
        if (await session.execute(select(PublicationAttemptModel).where(PublicationAttemptModel.idempotency_key == key))).scalar_one_or_none():
            return
        attempt = PublicationAttemptModel(
            approval_id=approval.id, platform=platform, status="queued", idempotency_key=key,
            request_payload={"task_id": task.task_id, "content": task.final_output, "context": context},
        )
        session.add(attempt)
        await session.flush()
        session.add(WorkflowRunModel(
            workflow_id=workflow, job_type=job_type,
            payload={"task_id": task.task_id, "approval_id": approval.id,
                     "publication_attempt_id": attempt.id, "platform": platform,
                     "content": task.final_output, "context": context},
            idempotency_key=key,
            priority=5,
            # Most social/YouTube write APIs do not provide a portable
            # idempotency primitive. Never auto-retry an ambiguous write.
            max_attempts=1,
        ))
        await session.commit()


async def _queue_hubspot_after_sales_approval(
    task: TaskModel,
    approval: ApprovalModel,
) -> None:
    """Stage an idempotent HubSpot sync only for an explicitly linked target."""

    if task.council != "sales":
        return
    context = dict(task.context or {})
    workflow = str(context.get("workflow") or "")
    linked = await integration_vault.provider_linked_to_target(
        "hubspot",
        workflow_id=workflow if workflow == "reddit_prospector" else "",
        council_id="" if workflow == "reddit_prospector" else "sales",
    )
    if not linked:
        return

    from src.integrations.hubspot import extract_contact

    contact = extract_contact(task.to_dict())
    if not contact["email"]:
        async with async_session() as session:
            current = await session.get(TaskModel, task.task_id, with_for_update=True)
            if current:
                current.context = {
                    **(current.context or {}),
                    "hubspot_sync_status": "skipped_missing_email",
                    "hubspot_sync_message": (
                        "Approved successfully. HubSpot sync was skipped because no valid "
                        "contact email was supplied."
                    ),
                }
                current.version += 1
                await record_audit(
                    session,
                    action="hubspot.sync_skipped",
                    resource_type="task",
                    resource_id=current.task_id,
                    details={"reason": "missing_contact_email"},
                )
                await session.commit()
        return

    try:
        await integration_vault.decrypted_provider_env("hubspot")
    except integration_vault.VaultConfigurationError:
        async with async_session() as session:
            current = await session.get(TaskModel, task.task_id, with_for_update=True)
            if current:
                current.context = {
                    **(current.context or {}),
                    "hubspot_sync_status": "blocked_unverified",
                    "hubspot_sync_message": (
                        "Approved successfully. Re-verify the linked HubSpot connection "
                        "before CRM synchronization."
                    ),
                }
                current.version += 1
                await record_audit(
                    session,
                    action="hubspot.sync_blocked",
                    resource_type="task",
                    resource_id=current.task_id,
                    details={"reason": "connection_not_verified"},
                )
                await session.commit()
        return

    key = f"hubspot:{approval.id}:{approval.version}"
    async with async_session() as session:
        existing = (await session.execute(
            select(PublicationAttemptModel).where(
                PublicationAttemptModel.idempotency_key == key
            )
        )).scalar_one_or_none()
        if existing:
            return
        current = await session.get(TaskModel, task.task_id, with_for_update=True)
        if not current:
            return
        attempt = PublicationAttemptModel(
            approval_id=approval.id,
            platform="hubspot",
            status="queued",
            idempotency_key=key,
            request_payload={"task_id": task.task_id},
        )
        session.add(attempt)
        await session.flush()
        session.add(WorkflowRunModel(
            workflow_id=workflow or "sales_council",
            job_type="crm.hubspot_sync",
            payload={
                "task_id": task.task_id,
                "approval_id": approval.id,
                "publication_attempt_id": attempt.id,
                "target_type": "workflow" if workflow == "reddit_prospector" else "council",
                "target_id": workflow if workflow == "reddit_prospector" else "sales",
            },
            idempotency_key=key,
            priority=5,
            max_attempts=3,
        ))
        current.context = {
            **(current.context or {}),
            "hubspot_sync_status": "queued",
            "hubspot_sync_message": "Approved lead is queued for HubSpot synchronization.",
        }
        current.version += 1
        await record_audit(
            session,
            action="hubspot.sync_queued",
            resource_type="task",
            resource_id=current.task_id,
            details={"attempt_id": attempt.id},
        )
        try:
            await session.commit()
        except IntegrityError:
            # A concurrent replay may have inserted the same approval-version
            # key first. The unique constraint makes that replay a success.
            await session.rollback()


@app.post("/api/approvals/{task_id}/actions")
async def act_on_approval(
    task_id: str, payload: ApprovalActionRequest, request: Request,
    actor: RequestActor = Depends(require_admin_or_telegram),
):
    task, approval = await _task_and_approval(task_id)
    if not approval:
        raise _api_error(404, "APPROVAL_NOT_FOUND", "Task is not awaiting approval")
    if task.status in {"queued", "running"} and payload.action != "cancel":
        raise _api_error(
            409,
            "TASK_NOT_DECIDABLE",
            "A queued or running task can only be cancelled",
        )
    if (task.context or {}).get("publication_state") == "reconciliation_required":
        raise _api_error(
            409,
            "PUBLICATION_RECONCILIATION_REQUIRED",
            "The provider outcome is uncertain. Automatic retry is disabled to prevent a duplicate post; verify the destination manually.",
        )
    if task.status == "failed" and payload.action != "retry":
        raise _api_error(
            409,
            "TASK_RETRY_REQUIRED",
            "A failed task can only be retried",
        )
    context = task.context or {}
    workflow = str(context.get("workflow", ""))
    platform = str(context.get("platform", "")).lower()
    if payload.action == "approve" and workflow == "content_engine" and platform != "reddit":
        platform_key = "twitter" if platform == "x" else platform
        publisher_health = (await _publishing_health()).get(platform_key, {})
        if not publisher_health.get("configured", False):
            raise _api_error(
                409,
                "DESTINATION_NOT_CONFIGURED",
                f"{platform_key.title()} credentials must be configured before approval",
            )
        if publisher_health.get("credential_status") != "verified":
            raise _api_error(
                409,
                "DESTINATION_NOT_VERIFIED",
                f"{platform_key.title()} credentials must pass verification before approval",
            )
        if platform_key == "instagram" and not context.get("media_url"):
            raise _api_error(
                409,
                "MEDIA_REQUIRED",
                "Instagram publishing requires an approved public media URL",
            )
    if payload.action == "approve" and workflow == "instagram_comments":
        async with async_session() as session:
            definition = await session.get(WorkflowDefinitionModel, workflow)
            ready = bool(definition and await _workflow_credentials_current(session, definition))
        if not ready or not definition or not definition.is_enabled or definition.is_paused:
            raise _api_error(
                409,
                "INSTAGRAM_COMMENTS_NOT_READY",
                "Enable Instagram Comment Replies with verified Meta and OpenRouter connections before approval",
            )
    try:
        result = await approval_service.act(
            approval.id, action=payload.action, expected_version=payload.expected_version,
            idempotency_key=payload.idempotency_key, actor_user_id=actor.user_id,
            actor_type=actor.actor_type, actor_id=actor.actor_id,
            notes=payload.notes,
            edited_output={"content": payload.edited_output} if payload.edited_output else {},
            request_id=getattr(request.state, "request_id", ""),
        )
    except ApprovalNotFound as exc:
        raise _api_error(404, exc.code, str(exc)) from exc
    except ApprovalConflict as exc:
        raise _api_error(409, exc.code, str(exc)) from exc
    except ApprovalInvalidAction as exc:
        raise _api_error(422, exc.code, str(exc)) from exc
    task, approval = await _task_and_approval(task_id)
    if payload.edited_output and payload.action == "approve":
        async with async_session() as session:
            current = await session.get(TaskModel, task_id)
            if current:
                current.final_output, current.version = payload.edited_output, current.version + 1
                await session.commit()
        task, approval = await _task_and_approval(task_id)
    assert approval is not None
    # Queueing is itself idempotent. Re-run this bridge for replayed requests so
    # a crash after the approval commit but before job creation can self-heal.
    await _queue_after_approval(task, approval, payload.action)
    task, approval = await _task_and_approval(task_id)
    return _mutation(_task_json(task, approval), approval.version, result.audit_event_id, replayed=result.replayed)


@app.post("/api/tasks/{task_id}/approve", deprecated=True)
async def legacy_approval(
    task_id: str, payload: LegacyApprovalRequest, request: Request,
    actor: RequestActor = Depends(require_admin_or_telegram),
):
    _, approval = await _task_and_approval(task_id)
    if not approval:
        raise _api_error(404, "APPROVAL_NOT_FOUND", "Task is not awaiting approval")
    normalized = ApprovalActionRequest(
        action="approve" if payload.approved else "reject",
        expected_version=payload.expected_version or approval.version,
        idempotency_key=payload.idempotency_key or f"legacy:{uuid.uuid4()}",
        edited_output=payload.edited_output, notes=payload.notes,
    )
    return await act_on_approval(task_id, normalized, request, actor)


# Durable workflow management
@app.get("/api/workflows")
async def list_workflows(_: RequestActor = Depends(require_admin)):
    async with async_session() as session:
        items = (await session.execute(select(WorkflowDefinitionModel).order_by(WorkflowDefinitionModel.id))).scalars().all()
        runs = (await session.execute(
            select(WorkflowRunModel)
            .where(WorkflowRunModel.workflow_id.in_([item.id for item in items]))
            .order_by(WorkflowRunModel.created_at.desc())
        )).scalars().all()
    latest: dict[str, WorkflowRunModel] = {}
    for run in runs:
        latest.setdefault(run.workflow_id, run)
    return {"workflows": [_workflow_json(item, latest.get(item.id)) for item in items]}


@app.get("/api/workflows/{workflow_id}")
async def get_workflow(workflow_id: str, _: RequestActor = Depends(require_admin)):
    if workflow_id not in WORKFLOW_SPECS:
        raise _api_error(404, "WORKFLOW_NOT_FOUND", "Workflow does not exist")
    async with async_session() as session:
        item = await session.get(WorkflowDefinitionModel, workflow_id)
        runs = (await session.execute(
            select(WorkflowRunModel)
            .where(WorkflowRunModel.workflow_id == workflow_id)
            .order_by(WorkflowRunModel.created_at.desc())
            .limit(50)
        )).scalars().all()
        providers = (await session.execute(
            select(WorkflowIntegrationModel.provider)
            .where(WorkflowIntegrationModel.workflow_id == workflow_id)
            .order_by(WorkflowIntegrationModel.provider)
        )).scalars().all()
    if not item:
        raise _api_error(404, "WORKFLOW_NOT_FOUND", "Workflow does not exist")
    return {
        **_workflow_json(item),
        "runs": [_workflow_job_json(run) for run in runs],
        "integration_providers": list(providers),
    }


@app.patch("/api/workflows/{workflow_id}")
async def patch_workflow(
    workflow_id: str, payload: WorkflowPatchRequest, request: Request,
    actor: RequestActor = Depends(require_admin),
):
    if workflow_id not in WORKFLOW_SPECS:
        raise _api_error(404, "WORKFLOW_NOT_FOUND", "Workflow does not exist")
    if payload.selected_document_hashes:
        raise _api_error(
            422,
            "GRANT_ONLY_SETTING",
            "Knowledge documents can only be selected for an individual Grant Council run",
        )
    async with async_session() as session:
        item = await session.get(WorkflowDefinitionModel, workflow_id, with_for_update=True)
        if not item:
            raise _api_error(404, "WORKFLOW_NOT_FOUND", "Workflow does not exist")
        if payload.enabled is not None:
            if payload.enabled and not await _workflow_credentials_current(session, item):
                raise _api_error(409, "INTEGRATION_NOT_VERIFIED", "Verify credentials before enabling this workflow")
            item.is_enabled = payload.enabled
        if payload.paused is not None:
            item.is_paused = payload.paused
        if payload.schedule_preset is not None:
            allowed_presets = WORKFLOW_SCHEDULE_PRESETS.get(workflow_id, ())
            if payload.schedule_preset not in allowed_presets:
                raise _api_error(
                    422,
                    "INVALID_SCHEDULE_PRESET",
                    "Choose one of the scheduling options shown for this automation",
                    allowed_options=list(allowed_presets),
                )
            item.schedule = dict(SCHEDULE_PRESETS[payload.schedule_preset])
        settings = dict(item.settings or {})
        settings.pop("selected_document_hashes", None)
        if payload.custom_prompt is not None:
            settings["custom_prompt"] = payload.custom_prompt
        item.settings, item.version, item.updated_at = settings, item.version + 1, utcnow()
        event = await record_audit(
            session, action="workflow.updated", resource_type="workflow", resource_id=workflow_id,
            actor_type=actor.actor_type, actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details=payload.model_dump(exclude_none=True),
        )
        await session.commit()
        await session.refresh(item)
    return _mutation(_workflow_json(item), item.version, event.id)


@app.post("/api/workflows/{workflow_id}/trigger")
async def trigger_workflow(
    workflow_id: str, payload: WorkflowTriggerRequest, request: Request,
    actor: RequestActor = Depends(require_admin),
):
    if workflow_id not in WORKFLOW_SPECS or workflow_id == "telegram_control":
        raise _api_error(404, "WORKFLOW_NOT_TRIGGERABLE", "Workflow cannot be manually triggered")
    if payload.payload.get("selected_document_hashes"):
        raise _api_error(
            422,
            "GRANT_ONLY_SETTING",
            "Knowledge documents can only be selected for an individual Grant Council run",
        )
    if (await get_kill_switch_db())["is_active"]:
        raise _api_error(423, "KILL_SWITCH_ACTIVE", "Global kill switch is active")
    async with async_session() as session:
        definition = await session.get(WorkflowDefinitionModel, workflow_id)
        credentials_current = bool(
            definition and await _workflow_credentials_current(session, definition)
        )
    if not definition or not definition.is_enabled or definition.is_paused:
        raise _api_error(409, "WORKFLOW_INACTIVE", "Workflow is disabled or paused")
    if not credentials_current:
        raise _api_error(409, "INTEGRATION_NOT_VERIFIED", "Workflow credentials are not verified")
    job = await job_service.enqueue(
        workflow_id=workflow_id,
        job_type=f"workflow.{workflow_id}",
        payload={
            **{
                key: value
                for key, value in (definition.settings or {}).items()
                if key != "selected_document_hashes"
            },
            **{
                key: value
                for key, value in payload.payload.items()
                if key != "selected_document_hashes"
            },
        },
        idempotency_key=f"trigger:{workflow_id}:{payload.idempotency_key}",
    )
    async with async_session() as session:
        event = await record_audit(
            session, action="workflow.triggered", resource_type="workflow_run", resource_id=job.id,
            actor_type=actor.actor_type, actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""), details={"workflow_id": workflow_id},
        )
        await session.commit()
    return _mutation({"id": job.id, "workflow_id": job.workflow_id, "status": job.status, "version": job.version}, job.version, event.id)


@app.post("/api/workflows/content-engine", deprecated=True)
async def legacy_content_trigger(
    payload: ContentEngineRequest, request: Request,
    actor: RequestActor = Depends(require_admin),
):
    trigger = WorkflowTriggerRequest(payload=payload.model_dump(), idempotency_key=f"content:{uuid.uuid4()}")
    return await trigger_workflow("content_engine", trigger, request, actor)


# Kill switch
@app.get("/api/kill-switch")
async def get_kill_switch(_: RequestActor = Depends(require_admin_or_telegram)):
    return await get_kill_switch_db()


@app.put("/api/kill-switch")
async def put_kill_switch(
    payload: KillSwitchRequest, request: Request,
    actor: RequestActor = Depends(require_admin_or_telegram),
):
    resource = await set_kill_switch_db(payload.active, toggled_by=f"{actor.actor_type}:{actor.actor_id}", reason=payload.reason)
    async with async_session() as session:
        event = await record_audit(
            session, action="kill_switch.activated" if payload.active else "kill_switch.deactivated",
            resource_type="kill_switch", resource_id="global",
            actor_type=actor.actor_type, actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""), details={"reason": payload.reason},
        )
        await session.commit()
    return _mutation(resource, 1, event.id)


@app.post("/api/kill-switch/activate", deprecated=True)
async def legacy_activate(request: Request, reason: str = "Activated via dashboard", actor: RequestActor = Depends(require_admin)):
    return await put_kill_switch(KillSwitchRequest(active=True, reason=reason), request, actor)


@app.post("/api/kill-switch/deactivate", deprecated=True)
async def legacy_deactivate(request: Request, actor: RequestActor = Depends(require_admin)):
    return await put_kill_switch(KillSwitchRequest(active=False), request, actor)


# Integration verification and truthful health
async def _verify_integration(workflow_id: str) -> dict[str, Any]:
    if _missing_config(workflow_id):
        return {"verified": False, "message": "Required configuration is missing"}
    try:
        if workflow_id == "content_engine":
            result = await validate_approved_models(cache_seconds=0)
            if not result.get("ready"):
                return {"verified": False, "message": "An approved model is unavailable"}
        elif workflow_id == "telegram_control":
            import httpx
            raw_chat_ids = [
                value.strip()
                for value in os.environ["TELEGRAM_ALLOWED_CHAT_IDS"].split(",")
                if value.strip()
            ]
            if len(raw_chat_ids) != 1:
                return {"verified": False, "message": "Exactly one administrator private-chat ID is required"}
            try:
                int(raw_chat_ids[0])
            except ValueError:
                return {"verified": False, "message": "Administrator chat ID must be numeric"}
            token = os.environ["TELEGRAM_BOT_TOKEN"]
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(f"https://api.telegram.org/bot{token}/getMe")
                response.raise_for_status()
                if not response.json().get("ok"):
                    return {"verified": False, "message": "Telegram rejected the bot token"}
        elif workflow_id in {"youtube_comments", "youtube_descriptions"}:
            from src.integrations.youtube import verify_youtube_connection
            await asyncio.to_thread(
                verify_youtube_connection, os.environ["YOUTUBE_CHANNEL_ID"]
            )
        elif workflow_id == "reddit_prospector":
            from src.integrations.reddit import get_reddit_client
            client = get_reddit_client()
            await asyncio.to_thread(lambda: next(iter(client.subreddit("all").new(limit=1)), None))
        elif workflow_id == "instagram_comments":
            from src.integrations.instagram_comments import verify_comment_access

            await verify_comment_access()
        return {
            "verified": True,
            "message": "Connection verified",
            "credential_fingerprint": workflow_credential_fingerprint(workflow_id),
        }
    except Exception as exc:
        return {"verified": False, "message": f"{type(exc).__name__}: {str(exc)[:300]}"}


async def _verify_publisher(platform: str) -> dict[str, Any]:
    fingerprint = _publisher_fingerprint(platform)
    if not fingerprint:
        return {"verified": False, "message": "Required configuration is missing"}
    try:
        import httpx

        if platform == "discord":
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(os.environ["DISCORD_WEBHOOK_URL"])
                response.raise_for_status()
        elif platform == "instagram":
            graph_version = os.getenv("META_GRAPH_API_VERSION", "v23.0")
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    f"https://graph.facebook.com/{graph_version}/{os.environ['INSTAGRAM_BUSINESS_ID']}",
                    params={"fields": "id,username", "access_token": os.environ["INSTAGRAM_ACCESS_TOKEN"]},
                )
                response.raise_for_status()
        elif platform == "facebook":
            graph_version = os.getenv("META_GRAPH_API_VERSION", "v23.0")
            token = os.getenv("META_ACCESS_TOKEN") or os.getenv("INSTAGRAM_ACCESS_TOKEN")
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    f"https://graph.facebook.com/{graph_version}/{os.environ['FACEBOOK_PAGE_ID']}",
                    params={"fields": "id,name", "access_token": token},
                )
                response.raise_for_status()
        elif platform == "linkedin":
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    "https://api.linkedin.com/v2/me",
                    headers={"Authorization": f"Bearer {os.environ['LINKEDIN_ACCESS_TOKEN']}"},
                )
                response.raise_for_status()
        elif platform == "twitter":
            import tweepy

            def verify_twitter():
                client = tweepy.Client(
                    consumer_key=os.environ["TWITTER_API_KEY"],
                    consumer_secret=os.environ["TWITTER_API_SECRET"],
                    access_token=os.environ["TWITTER_ACCESS_TOKEN"],
                    access_token_secret=os.environ["TWITTER_ACCESS_SECRET"],
                )
                result = client.get_me(user_auth=True)
                if not result or result.data is None:
                    raise RuntimeError("X/Twitter did not return the authenticated account")

            await asyncio.to_thread(verify_twitter)
        return {
            "verified": True,
            "message": "Connection verified",
            "credential_fingerprint": fingerprint,
        }
    except Exception as exc:
        return {
            "verified": False,
            "message": f"{type(exc).__name__}: {str(exc)[:300]}",
            "credential_fingerprint": fingerprint,
        }


@app.post("/api/integrations/{workflow_id}/verify")
async def verify_integration(
    workflow_id: str, request: Request, actor: RequestActor = Depends(require_admin),
):
    if workflow_id not in WORKFLOW_SPECS:
        raise _api_error(404, "INTEGRATION_NOT_FOUND", "Integration does not exist")
    result = await _verify_integration(workflow_id)
    async with async_session() as session:
        item = await session.get(WorkflowDefinitionModel, workflow_id, with_for_update=True)
        assert item is not None
        item.credential_status = "verified" if result["verified"] else "failed"
        item.settings = {
            **(item.settings or {}),
            "verification_message": result["message"],
            "verified_at": iso(utcnow()) if result["verified"] else "",
            "credential_fingerprint": result.get("credential_fingerprint", ""),
        }
        item.version += 1
        event = await record_audit(
            session, action="integration.verified" if result["verified"] else "integration.failed",
            resource_type="workflow", resource_id=workflow_id,
            actor_type=actor.actor_type, actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""), details={"message": result["message"]},
        )
        await session.commit()
        await session.refresh(item)
    return _mutation(_workflow_json(item), item.version, event.id, verification=result)


@app.post("/api/integrations/publishing/{platform}/verify")
async def verify_publishing_integration(
    platform: str, request: Request, actor: RequestActor = Depends(require_admin),
):
    platform = platform.lower()
    if platform == "x":
        platform = "twitter"
    if platform not in PUBLISHER_ENV:
        raise _api_error(404, "PUBLISHING_INTEGRATION_NOT_FOUND", "Publishing destination does not exist")
    result = await _verify_publisher(platform)
    async with async_session() as session:
        definition = await session.get(WorkflowDefinitionModel, "content_engine", with_for_update=True)
        if not definition:
            raise _api_error(503, "WORKFLOW_NOT_INITIALIZED", "Content Engine is not initialized")
        settings = dict(definition.settings or {})
        verifications = dict(settings.get("publishing_verifications") or {})
        verifications[platform] = {
            "status": "verified" if result["verified"] else "failed",
            "message": result["message"],
            "verified_at": iso(utcnow()) if result["verified"] else "",
            "credential_fingerprint": result.get("credential_fingerprint", ""),
        }
        settings["publishing_verifications"] = verifications
        definition.settings = settings
        definition.version += 1
        event = await record_audit(
            session,
            action="publishing_integration.verified" if result["verified"] else "publishing_integration.failed",
            resource_type="publishing_integration",
            resource_id=platform,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"message": result["message"]},
        )
        await session.commit()
    health = (await _publishing_health())[platform]
    return _mutation({"platform": platform, **health}, definition.version, event.id)


def _connection_resource(item: dict[str, Any]) -> dict[str, Any]:
    """Return portal-safe connection metadata without credential values."""
    return {
        key: value
        for key, value in item.items()
        if key not in {"credentials", "encrypted_credentials", "credential_fingerprint"}
    }


@app.get("/api/integrations/catalog")
async def integration_catalog(_: RequestActor = Depends(require_admin)):
    """List reusable integration connections; secret values are write-only."""
    return {"integrations": [
        _connection_resource(item)
        for item in await integration_vault.list_connections()
    ]}


@app.put("/api/integrations/{provider}/credentials")
async def save_integration_credentials(
    provider: str,
    payload: IntegrationCredentialsRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    provider = provider.strip().lower()
    try:
        row = await integration_vault.put_credentials(
            provider,
            payload.credentials,
            display_name=payload.display_name,
        )
    except integration_vault.VaultConfigurationError as exc:
        raise _api_error(503, "INTEGRATION_VAULT_UNAVAILABLE", str(exc)) from exc
    except ValueError as exc:
        raise _api_error(422, "INVALID_INTEGRATION_CREDENTIALS", str(exc)) from exc
    async with async_session() as session:
        event = await record_audit(
            session,
            action="integration.credentials_saved",
            resource_type="integration",
            resource_id=provider,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"configured_fields": sorted(row.credential_fields or [])},
        )
        await session.commit()
    connection = next(
        item for item in await integration_vault.list_connections()
        if item["id"] == provider
    )
    return _mutation(_connection_resource(connection), row.version, event.id)


@app.delete("/api/integrations/{provider}/credentials")
async def remove_integration_credentials(
    provider: str,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    provider = provider.strip().lower()
    if provider not in integration_vault.PROVIDERS:
        raise _api_error(404, "INTEGRATION_NOT_FOUND", "Integration does not exist")
    if not await integration_vault.delete_credentials(provider):
        raise _api_error(404, "INTEGRATION_NOT_CONFIGURED", "Integration is not configured")
    async with async_session() as session:
        event = await record_audit(
            session,
            action="integration.credentials_removed",
            resource_type="integration",
            resource_id=provider,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={},
        )
        await session.commit()
    return _mutation({"id": provider, "status": "not_configured"}, 0, event.id)


async def _verify_vault_connection(provider: str) -> tuple[bool, str]:
    """Verify a provider with decrypted credentials scoped to this call only."""
    try:
        values = await integration_vault.decrypted_provider_env(
            provider, require_verified=False
        )
        with use_integration_configuration(values):
            if provider == "openrouter":
                result = await validate_approved_models(cache_seconds=0)
                if not result.get("ready"):
                    raise RuntimeError("Approved models are unavailable")
            elif provider == "telegram":
                import httpx

                chat_ids = [
                    value.strip()
                    for value in values["TELEGRAM_ALLOWED_CHAT_IDS"].split(",")
                    if value.strip()
                ]
                if len(chat_ids) != 1 or not re.fullmatch(r"-?\d+", chat_ids[0]):
                    raise RuntimeError("Exactly one numeric administrator chat ID is required")
                async with httpx.AsyncClient(timeout=15) as client:
                    base = f"https://api.telegram.org/bot{values['TELEGRAM_BOT_TOKEN']}"
                    response = await client.get(f"{base}/getMe")
                    response.raise_for_status()
                    if not response.json().get("ok"):
                        raise RuntimeError("Telegram rejected the bot token")
                    chat = await client.get(f"{base}/getChat", params={"chat_id": chat_ids[0]})
                    chat.raise_for_status()
                    chat_payload = chat.json()
                    if not chat_payload.get("ok") or (chat_payload.get("result") or {}).get("type") != "private":
                        raise RuntimeError("Telegram administrator target must be a reachable private chat")
            elif provider == "youtube":
                from src.integrations.youtube import verify_youtube_connection

                await asyncio.to_thread(
                    verify_youtube_connection,
                    values["YOUTUBE_CHANNEL_ID"],
                    values.get("YOUTUBE_OAUTH_TOKEN_JSON", ""),
                )
            elif provider == "reddit":
                import praw

                client = praw.Reddit(
                    client_id=values["REDDIT_CLIENT_ID"],
                    client_secret=values["REDDIT_CLIENT_SECRET"],
                    user_agent=values["REDDIT_USER_AGENT"],
                )
                await asyncio.to_thread(
                    lambda: next(iter(client.subreddit("all").new(limit=1)), None)
                )
            elif provider == "discord":
                import httpx

                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.get(values["DISCORD_WEBHOOK_URL"])
                    response.raise_for_status()
            elif provider == "linkedin":
                import httpx

                organization = values.get("LINKEDIN_ORGANIZATION_ID", "")
                endpoint = (
                    f"https://api.linkedin.com/v2/organizations/{organization}"
                    if organization else "https://api.linkedin.com/v2/me"
                )
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.get(
                        endpoint,
                        headers={"Authorization": f"Bearer {values['LINKEDIN_ACCESS_TOKEN']}"},
                    )
                    response.raise_for_status()
            elif provider == "meta":
                import httpx

                instagram_id = values.get("INSTAGRAM_BUSINESS_ID", "")
                target = instagram_id or values.get("FACEBOOK_PAGE_ID")
                version = values.get("META_GRAPH_API_VERSION", "v23.0")
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.get(
                        f"https://graph.facebook.com/{version}/{target}",
                        params={
                            "fields": (
                                "id,username,media.limit(1){id,comments.limit(1){id}}"
                                if instagram_id else "id,name"
                            ),
                            "access_token": values["META_ACCESS_TOKEN"],
                        },
                    )
                    response.raise_for_status()
                    app_id = values.get("META_APP_ID", "")
                    if app_id:
                        token_info = await client.get(
                            f"https://graph.facebook.com/{version}/debug_token",
                            params={
                                "input_token": values["META_ACCESS_TOKEN"],
                                "access_token": f"{app_id}|{values['META_APP_SECRET']}",
                            },
                        )
                        token_info.raise_for_status()
                        token_data = (token_info.json() or {}).get("data") or {}
                        if not token_data.get("is_valid"):
                            raise RuntimeError("Meta reported that the access token is invalid")
                        if instagram_id:
                            scopes = set(token_data.get("scopes") or [])
                            if not scopes.intersection({"instagram_manage_comments", "instagram_business_manage_comments"}):
                                raise RuntimeError("Meta token does not include Instagram comment-management permission")
            elif provider == "runpod":
                from src.integrations.runpod import verify_connection

                await verify_connection()
            elif provider == "hubspot":
                from src.integrations.hubspot import verify_connection

                await verify_connection()
            elif provider == "x":
                import tweepy

                def verify_x():
                    client = tweepy.Client(
                        consumer_key=values["TWITTER_API_KEY"],
                        consumer_secret=values["TWITTER_API_SECRET"],
                        access_token=values["TWITTER_ACCESS_TOKEN"],
                        access_token_secret=values["TWITTER_ACCESS_SECRET"],
                    )
                    result = client.get_me(user_auth=True)
                    if not result or result.data is None:
                        raise RuntimeError("X did not return the authenticated account")

                await asyncio.to_thread(verify_x)
            else:
                raise ValueError("Unsupported integration provider")
        return True, "Connection verified"
    except (integration_vault.VaultConfigurationError, KeyError, ValueError) as exc:
        return False, str(exc)[:300]
    except Exception as exc:
        if provider == "hubspot":
            from src.integrations.hubspot import HubSpotIntegrationError

            if isinstance(exc, HubSpotIntegrationError):
                return False, str(exc)[:300]
        # Provider exception text can contain a secret-bearing URL. Never return it.
        return False, "The provider rejected the credentials or could not be reached"


async def _provider_runtime(provider: str) -> dict[str, str]:
    try:
        return await integration_vault.decrypted_provider_env(provider)
    except integration_vault.VaultConfigurationError as exc:
        raise _api_error(
            409,
            "INTEGRATION_NOT_VERIFIED",
            f"Verify the {provider.title()} connection in Settings & Integrations first",
        ) from exc


@app.get("/api/blender/pods")
async def get_blender_pods(_: RequestActor = Depends(require_admin)):
    """Return live RunPod state; never fabricate placeholder machines or costs."""
    from src.integrations.runpod import RunPodError, list_pods

    values = await _provider_runtime("runpod")
    try:
        with use_integration_configuration(values):
            pods = await list_pods()
    except RunPodError as exc:
        raise _api_error(502, "RUNPOD_UNAVAILABLE", str(exc)) from exc
    return {"pods": pods, "provider": "runpod", "status": "verified"}


@app.post("/api/blender/pods/{pod_id}/actions")
async def act_on_blender_pod(
    pod_id: str,
    payload: BlenderPodActionRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    """Resume or stop a RunPod pod with a persisted administrator audit event."""
    from src.integrations.runpod import RunPodError, resume_pod, stop_pod

    if payload.action == "resume" and (await get_kill_switch_db())["is_active"]:
        raise _api_error(423, "KILL_SWITCH_ACTIVE", "The system is stopped; resume it before starting GPU billing")
    values = await _provider_runtime("runpod")
    try:
        with use_integration_configuration(values):
            pod = await (resume_pod(pod_id) if payload.action == "resume" else stop_pod(pod_id))
    except ValueError as exc:
        raise _api_error(422, "INVALID_POD_ID", str(exc)) from exc
    except RunPodError as exc:
        raise _api_error(502, "RUNPOD_ACTION_FAILED", str(exc)) from exc
    async with async_session() as session:
        event = await record_audit(
            session,
            action=f"blender.pod_{payload.action}",
            resource_type="runpod_pod",
            resource_id=pod_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"desired_status": pod.get("desired_status", "")},
        )
        await session.commit()
    return _mutation(pod, 1, event.id)


@app.get("/api/blender/jobs")
async def list_blender_jobs(_: RequestActor = Depends(require_admin)):
    async with async_session() as session:
        jobs = (await session.execute(
            select(WorkflowRunModel)
            .where(WorkflowRunModel.workflow_id == "blender_manager")
            .order_by(WorkflowRunModel.created_at.desc())
            .limit(50)
        )).scalars().all()
    return {"jobs": [_blender_job_resource(job) for job in jobs]}


@app.get("/api/blender/jobs/{job_id}")
async def get_blender_job(job_id: str, _: RequestActor = Depends(require_admin)):
    async with async_session() as session:
        job = await session.get(WorkflowRunModel, job_id)
    if job is None or job.workflow_id != "blender_manager":
        raise _api_error(404, "BLENDER_JOB_NOT_FOUND", "Blender job does not exist")
    return _blender_job_resource(job)


@app.post("/api/blender/jobs")
async def create_blender_job(
    payload: BlenderTemplateJobRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    """Queue an idempotent, allowlisted GPU repair job for a workspace template."""
    from src.integrations.runpod import RunPodError, list_pods

    if (await get_kill_switch_db())["is_active"]:
        raise _api_error(423, "KILL_SWITCH_ACTIVE", "The system is stopped; resume it before starting GPU work")
    values = await _provider_runtime("runpod")
    if len(values.get("BLENDER_AGENT_TOKEN", "")) < 32:
        raise _api_error(
            409,
            "BLENDER_AGENT_NOT_CONFIGURED",
            "Add a separate Blender agent token to the RunPod integration before running templates",
        )
    try:
        with use_integration_configuration(values):
            pods = await list_pods()
    except RunPodError as exc:
        raise _api_error(502, "RUNPOD_UNAVAILABLE", str(exc)) from exc
    if not any(pod.get("id") == payload.pod_id for pod in pods):
        raise _api_error(404, "RUNPOD_POD_NOT_FOUND", "The selected pod is not in the verified RunPod account")
    job = await job_service.enqueue(
        workflow_id="blender_manager",
        job_type="blender.template_repair",
        payload={
            "pod_id": payload.pod_id,
            "source_path": payload.source_path,
            "output_name": payload.output_name,
            "frame": payload.frame,
            "samples": payload.samples,
            "resolution_percent": payload.resolution_percent,
            "auto_stop": payload.auto_stop,
        },
        idempotency_key=f"blender:{payload.idempotency_key}",
        priority=10,
        max_attempts=3,
    )
    async with async_session() as session:
        event = await record_audit(
            session,
            action="blender.template_job_queued",
            resource_type="workflow_run",
            resource_id=job.id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"pod_id": payload.pod_id, "auto_stop": payload.auto_stop},
        )
        await session.commit()
    return _mutation(_blender_job_resource(job), job.version, event.id)


@app.post("/api/integrations/connections/{provider}/verify")
async def verify_vault_connection(
    provider: str,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    provider = provider.strip().lower()
    if provider not in integration_vault.PROVIDERS:
        raise _api_error(404, "INTEGRATION_NOT_FOUND", "Integration does not exist")
    verified, message = await _verify_vault_connection(provider)
    try:
        await integration_vault.mark_verification(provider, verified, "" if verified else message)
    except ValueError as exc:
        raise _api_error(409, "INTEGRATION_NOT_CONFIGURED", str(exc)) from exc
    async with async_session() as session:
        event = await record_audit(
            session,
            action="integration.verified" if verified else "integration.failed",
            resource_type="integration",
            resource_id=provider,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"message": message},
        )
        await session.commit()
    connection = next(
        item for item in await integration_vault.list_connections()
        if item["id"] == provider
    )
    return _mutation(
        _connection_resource(connection),
        connection["version"],
        event.id,
        verification={"verified": verified, "message": message},
    )


@app.patch("/api/workflows/{workflow_id}/integrations")
async def update_workflow_integrations(
    workflow_id: str,
    payload: WorkflowIntegrationLinksRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    if workflow_id not in WORKFLOW_SPECS:
        raise _api_error(404, "WORKFLOW_NOT_FOUND", "Workflow does not exist")
    try:
        providers = await integration_vault.set_workflow_links(
            workflow_id, payload.providers
        )
    except ValueError as exc:
        raise _api_error(422, "INVALID_WORKFLOW_INTEGRATIONS", str(exc)) from exc
    async with async_session() as session:
        definition = await session.get(WorkflowDefinitionModel, workflow_id)
        assert definition is not None
        event = await record_audit(
            session,
            action="workflow.integrations_updated",
            resource_type="workflow",
            resource_id=workflow_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"providers": providers},
        )
        await session.commit()
    resource = _workflow_json(definition)
    resource["integration_providers"] = providers
    return _mutation(resource, definition.version, event.id)


@app.patch("/api/councils/{council_id}/integrations")
async def update_council_integrations(
    council_id: str,
    payload: WorkflowIntegrationLinksRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    """Link a reusable verified destination to council approval output."""

    try:
        providers = await integration_vault.set_council_links(
            council_id, payload.providers
        )
    except ValueError as exc:
        raise _api_error(422, "INVALID_COUNCIL_INTEGRATIONS", str(exc)) from exc
    async with async_session() as session:
        event = await record_audit(
            session,
            action="council.integrations_updated",
            resource_type="council",
            resource_id=council_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"providers": providers},
        )
        await session.commit()
    resource = {
        "id": council_id,
        "integration_providers": providers,
    }
    return _mutation(resource, 1, event.id)


@app.get("/api/integrations/health")
@app.get("/api/integrations/status", deprecated=True)
async def integration_health(_: RequestActor = Depends(require_admin)):
    async with async_session() as session:
        items = (await session.execute(select(WorkflowDefinitionModel).order_by(WorkflowDefinitionModel.id))).scalars().all()
    connections = {item["id"]: item for item in await integration_vault.list_connections()}
    openrouter = connections.get("openrouter", {})
    return {
        "workflows": {item.id: {"credential_status": item.credential_status,
                                 "configured": not _missing_config(item.id),
                                 "enabled": item.is_enabled, "paused": item.is_paused,
                                 "message": (item.settings or {}).get("verification_message", "")}
                      for item in items},
        "publishing": await _publishing_health(),
        "model_gateway": {
            "configured": bool(openrouter.get("configured") or os.getenv("OPENROUTER_API_KEY", "").strip()),
            "status": openrouter.get("status", "configured" if os.getenv("OPENROUTER_API_KEY", "").strip() else "missing"),
        },
        "crm": {
            "hubspot": {
                "configured": bool(connections.get("hubspot", {}).get("configured")),
                "status": connections.get("hubspot", {}).get("status", "not_configured"),
                "message": connections.get("hubspot", {}).get("last_error", ""),
            }
        },
    }


# Knowledge base and Grant exports
@app.post("/api/knowledge/upload")
async def upload_knowledge(file: UploadFile = File(...), actor: RequestActor = Depends(require_admin)):
    filename = Path(file.filename or "document").name
    if Path(filename).suffix.lower() not in ALLOWED_KNOWLEDGE_EXTENSIONS:
        raise _api_error(415, "UNSUPPORTED_DOCUMENT_TYPE", "Only PDF, DOCX, TXT, and Markdown are accepted")
    contents = await file.read(MAX_KNOWLEDGE_BYTES + 1)
    if len(contents) > MAX_KNOWLEDGE_BYTES:
        raise _api_error(413, "DOCUMENT_TOO_LARGE", "Knowledge documents are limited to 20 MB")
    digest = hashlib.sha256(contents).hexdigest()
    async with async_session() as session:
        existing = (await session.execute(select(KnowledgeDocumentModel).where(KnowledgeDocumentModel.sha256 == digest))).scalar_one_or_none()
    if existing:
        raise _api_error(409, "DUPLICATE_DOCUMENT", "This document is already stored")
    from src.core.rag_engine import ingest_document
    try:
        ingest = await ingest_document(contents, filename)
    except Exception as exc:
        raise _api_error(422, "DOCUMENT_INGESTION_FAILED", str(exc)) from exc
    if ingest.get("status") not in {"ok", "duplicate"}:
        raise _api_error(
            422,
            "DOCUMENT_HAS_NO_INDEXABLE_TEXT",
            "The document did not contain extractable text",
        )
    async with async_session() as session:
        document = KnowledgeDocumentModel(
            filename=filename, content_type=file.content_type or "application/octet-stream",
            size_bytes=len(contents), sha256=digest,
            storage_key=str(ingest.get("doc_hash", digest)), status="ready",
        )
        session.add(document)
        await session.flush()
        event = await record_audit(
            session, action="knowledge.uploaded", resource_type="knowledge_document",
            resource_id=document.id, actor_type=actor.actor_type, actor_id=actor.actor_id,
            details={"filename": filename, "size_bytes": len(contents)},
        )
        await session.commit()
        await session.refresh(document)
    return _mutation({"id": document.id, "filename": document.filename, "sha256": document.sha256,
                      "status": document.status, "size_bytes": document.size_bytes}, 1, event.id)


@app.get("/api/knowledge/documents")
async def list_knowledge(_: RequestActor = Depends(require_admin)):
    async with async_session() as session:
        items = (await session.execute(select(KnowledgeDocumentModel).order_by(KnowledgeDocumentModel.created_at.desc()))).scalars().all()
        from src.core.models import KnowledgeChunkModel
        counts = dict((await session.execute(
            select(KnowledgeChunkModel.doc_hash, func.count(KnowledgeChunkModel.id))
            .group_by(KnowledgeChunkModel.doc_hash)
        )).all())
    documents = [{"id": i.id, "filename": i.filename, "doc_hash": i.storage_key,
                   "sha256": i.sha256, "status": i.status, "size_bytes": i.size_bytes,
                   "chunk_count": int(counts.get(i.storage_key, 0)),
                   "selected_for_grant": i.selected_for_grant, "warning": i.warning,
                   "created_at": iso(i.created_at)} for i in items]
    return {"documents": documents, "total": len(documents)}


@app.get("/api/knowledge/search")
async def search_knowledge(
    q: str = Query(min_length=1, max_length=1000),
    doc_hash: list[str] = Query(default=[]),
    _: RequestActor = Depends(require_admin),
):
    from src.core.rag_engine import search_knowledge_base
    return {
        "results": await search_knowledge_base(q, top_k=8, doc_hashes=doc_hash),
        "query": q,
        "scope": doc_hash,
    }


@app.delete("/api/knowledge/documents/{document_id}")
async def delete_knowledge(document_id: str, actor: RequestActor = Depends(require_admin)):
    from src.core.rag_engine import delete_document
    async with async_session() as session:
        document = await session.get(KnowledgeDocumentModel, document_id)
        if not document:
            raise _api_error(404, "DOCUMENT_NOT_FOUND", "Knowledge document does not exist")
        await delete_document(document.storage_key)
        await session.delete(document)
        event = await record_audit(
            session, action="knowledge.deleted", resource_type="knowledge_document",
            resource_id=document_id, actor_type=actor.actor_type, actor_id=actor.actor_id,
            details={"filename": document.filename},
        )
        await session.commit()
    return _mutation({"id": document_id, "status": "deleted"}, 1, event.id)


async def _grant_task(task_id: str) -> TaskModel:
    task, _ = await _task_and_approval(task_id)
    if task.council != "grant":
        raise _api_error(404, "GRANT_NOT_FOUND", "Grant task does not exist")
    if not task.final_output:
        raise _api_error(409, "GRANT_NOT_READY", "Grant output has not been generated")
    return task


@app.get("/api/grants/{task_id}/export.docx")
@app.get("/api/tasks/{task_id}/export/docx", deprecated=True)
async def export_grant_docx(task_id: str, _: RequestActor = Depends(require_admin)):
    from src.integrations.docx_export import build_task_docx, build_task_docx_filename
    data = (await _grant_task(task_id)).to_dict()
    return Response(content=build_task_docx(data),
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="{build_task_docx_filename(data)}"'})


@app.get("/api/grants/{task_id}/export.pdf")
async def export_grant_pdf(task_id: str, _: RequestActor = Depends(require_admin)):
    from src.integrations.docx_export import build_task_pdf, build_task_pdf_filename
    data = (await _grant_task(task_id)).to_dict()
    return Response(content=build_task_pdf(data), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{build_task_pdf_filename(data)}"'})


# Verified provider webhook ingress; payloads are parsed into bounded durable jobs.
async def _webhook_values(provider: str) -> dict[str, str]:
    try:
        return await integration_vault.decrypted_provider_env(provider)
    except integration_vault.VaultConfigurationError:
        if provider == "telegram":
            return {
                "TELEGRAM_WEBHOOK_SECRET": os.getenv("TELEGRAM_WEBHOOK_SECRET", ""),
            }
        if provider == "meta":
            return {
                "META_APP_SECRET": os.getenv("META_APP_SECRET", ""),
                "META_WEBHOOK_VERIFY_TOKEN": os.getenv("META_WEBHOOK_VERIFY_TOKEN", ""),
            }
        return {}


@app.get("/api/webhooks/meta")
async def verify_meta_webhook(
    mode: str = Query(default="", alias="hub.mode"),
    verify_token: str = Query(default="", alias="hub.verify_token"),
    challenge: str = Query(default="", alias="hub.challenge"),
):
    values = await _webhook_values("meta")
    expected = values.get("META_WEBHOOK_VERIFY_TOKEN", "").strip()
    if mode != "subscribe" or not expected or not hmac.compare_digest(expected, verify_token):
        raise _api_error(403, "WEBHOOK_VERIFICATION_FAILED", "Meta webhook verification failed")
    return Response(content=challenge, media_type="text/plain")


def _instagram_webhook_comments(payload: Any) -> list[dict[str, str]]:
    comments: list[dict[str, str]] = []
    if not isinstance(payload, dict) or payload.get("object") not in {"instagram", "page"}:
        return comments
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict) or change.get("field") not in {"comments", "live_comments"}:
                continue
            value = change.get("value") or {}
            values = value if isinstance(value, list) else [value]
            for item in values:
                if not isinstance(item, dict):
                    continue
                comment_id = str(item.get("id") or item.get("comment_id") or "").strip()
                comment_text = str(item.get("text") or "").strip()
                if not comment_id or not comment_text:
                    continue
                author = item.get("from") if isinstance(item.get("from"), dict) else {}
                media = item.get("media") if isinstance(item.get("media"), dict) else {}
                comments.append({
                    "comment_id": comment_id,
                    "comment_text": comment_text,
                    "username": str(item.get("username") or author.get("username") or "instagram_user"),
                    "media_id": str(item.get("media_id") or media.get("id") or ""),
                    "caption": "",
                    "timestamp": str(item.get("timestamp") or ""),
                })
    return comments[:100]


@app.post("/api/webhooks/{provider}")
async def receive_webhook(
    provider: str, request: Request,
    telegram_secret: str | None = Header(default=None, alias="X-Telegram-Bot-Api-Secret-Token"),
    signature: str | None = Header(default=None, alias="X-Hub-Signature-256"),
):
    provider, body = provider.lower(), await request.body()
    if len(body) > 2 * 1024 * 1024:
        raise _api_error(413, "WEBHOOK_TOO_LARGE", "Webhook payload is too large")
    if provider == "telegram":
        values = await _webhook_values("telegram")
        expected = values.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
        valid = bool(expected and telegram_secret and hmac.compare_digest(expected, telegram_secret))
    elif provider == "meta":
        values = await _webhook_values("meta")
        secret = values.get("META_APP_SECRET", "").encode()
        expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest() if secret else ""
        valid = bool(expected and signature and hmac.compare_digest(expected, signature))
    elif provider == "youtube":
        expected, supplied = os.getenv("YOUTUBE_WEBHOOK_SECRET", "").strip(), request.headers.get("X-Webhook-Secret", "")
        valid = bool(expected and supplied and hmac.compare_digest(expected, supplied))
    else:
        raise _api_error(404, "WEBHOOK_NOT_FOUND", "Webhook provider is unsupported")
    if not valid:
        raise _api_error(401, "INVALID_WEBHOOK_SIGNATURE", "Webhook signature is invalid")
    event_id = request.headers.get("X-Event-ID", "")[:128] or hashlib.sha256(body).hexdigest()
    if provider == "meta":
        try:
            parsed = await request.json()
        except ValueError as exc:
            raise _api_error(422, "INVALID_WEBHOOK_PAYLOAD", "Meta webhook body is not valid JSON") from exc
        comments = _instagram_webhook_comments(parsed)
        if not comments:
            return {"accepted": True, "ignored": True, "reason": "no_supported_comment_events"}
        job = await job_service.enqueue(
            workflow_id="instagram_comments",
            job_type="workflow.instagram_comments",
            payload={"webhook_comments": comments},
            idempotency_key=f"webhook:{provider}:{event_id}",
            priority=8,
        )
    else:
        job = await job_service.enqueue(
            workflow_id=f"webhook-{provider}", job_type=f"webhook.{provider}",
            payload={"body_sha256": hashlib.sha256(body).hexdigest()},
            idempotency_key=f"webhook:{provider}:{event_id}",
        )
    return {"accepted": True, "job_id": job.id}
