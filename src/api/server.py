"""Secure production API for the three-council AI Council OS release."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import io
import json
import os
import re
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, select, text, update
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
    ApprovalActionRequest,
    BlenderPodActionRequest,
    BlenderPodProvisionRequest,
    BlenderFlamencoProcessRequest,
    BlenderRenderActionRequest,
    BlenderRenderJobRequest,
    BlenderTemplateJobRequest,
    ContentEngineRequest,
    CouncilRunRequest,
    IntegrationCredentialsRequest,
    KillSwitchRequest,
    LegacyApprovalRequest,
    LoginRequest,
    WorkflowIntegrationLinksRequest,
    WorkflowPatchRequest,
    WorkflowTriggerRequest,
    BrainReviewActionRequest,
    KnowledgeBindingsRequest,
    KnowledgeCollectionPatch,
    KnowledgeCollectionRequest,
    KnowledgeSearchRequest,
    LearningActionRequest,
    MarkdownImportRequest,
    MCPTokenRequest,
    MCPTokenRevokeRequest,
    SkillRequest,
    SkillRevisionActionRequest,
    VersionedMutationRequest,
)
from src.core.approvals import (
    ApprovalConflict,
    ApprovalInvalidAction,
    ApprovalNotFound,
    ApprovalService,
)
from src.core.audit import record_audit
from src.core.database import (
    async_session,
    database_ready,
    get_kill_switch_db,
    get_stats,
    init_db,
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
    ApprovalModel,
    BrainConflictModel,
    BrainEntityModel,
    BrainFactModel,
    BrainGapModel,
    BrainRelationshipModel,
    CouncilRunModel,
    KnowledgeBindingModel,
    KnowledgeBindingStateModel,
    KnowledgeChunkModel,
    KnowledgeCollectionDocumentModel,
    KnowledgeCollectionModel,
    KnowledgeDocumentModel,
    LearningSuggestionModel,
    IdempotencyRecordModel,
    MCPCallModel,
    MCPTokenModel,
    RetrievalCacheModel,
    SkillModel,
    SkillRevisionModel,
    PublicationAttemptModel,
    RenderFrameModel,
    RenderJobModel,
    TaskModel,
    WorkflowDefinitionModel,
    WorkflowRunModel,
    iso,
    utcnow,
)
from src.core.security import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    AuthInvalidCredentials,
    AuthLocked,
)

PRODUCTION_COUNCILS = frozenset({"grant", "sales", "content"})
SCHEDULE_PRESETS: dict[str, dict[str, Any]] = {
    "manual": {"type": "manual", "preset": "manual"},
    "every_5_minutes": {
        "type": "interval",
        "seconds": 300,
        "preset": "every_5_minutes",
    },
    "every_15_minutes": {
        "type": "interval",
        "seconds": 900,
        "preset": "every_15_minutes",
    },
    "every_30_minutes": {
        "type": "interval",
        "seconds": 1800,
        "preset": "every_30_minutes",
    },
    "hourly": {"type": "interval", "seconds": 3600, "preset": "hourly"},
    "every_3_hours": {
        "type": "interval",
        "seconds": 10800,
        "preset": "every_3_hours",
    },
    "every_6_hours": {
        "type": "interval",
        "seconds": 21600,
        "preset": "every_6_hours",
    },
    "every_12_hours": {
        "type": "interval",
        "seconds": 43200,
        "preset": "every_12_hours",
    },
    "daily": {"type": "interval", "seconds": 86400, "preset": "daily"},
}
WORKFLOW_SCHEDULE_PRESETS: dict[str, tuple[str, ...]] = {
    "instagram_comments": (
        "every_5_minutes",
        "every_15_minutes",
        "every_30_minutes",
        "hourly",
        "manual",
    ),
    "youtube_comments": (
        "every_15_minutes",
        "every_30_minutes",
        "hourly",
        "every_6_hours",
        "manual",
    ),
    "reddit_prospector": (
        "hourly",
        "every_3_hours",
        "every_6_hours",
        "every_12_hours",
        "daily",
        "manual",
    ),
}
WORKFLOW_SPECS: dict[str, dict[str, Any]] = {
    "telegram_control": {
        "display_name": "Telegram Control & Approval",
        "schedule": dict(SCHEDULE_PRESETS["manual"]),
        "required_env": [
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_ALLOWED_CHAT_IDS",
            "INTERNAL_SERVICE_TOKEN",
        ],
    },
    "youtube_comments": {
        "display_name": "YouTube Comment Replies",
        "schedule": dict(SCHEDULE_PRESETS["every_30_minutes"]),
        "required_env": [
            "YOUTUBE_API_KEY",
            "YOUTUBE_CHANNEL_ID",
            "YOUTUBE_OAUTH_TOKEN",
        ],
    },
    "reddit_prospector": {
        "display_name": "Reddit Lead Prospector",
        "schedule": dict(SCHEDULE_PRESETS["hourly"]),
        "required_env": ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"],
    },
    "youtube_descriptions": {
        "display_name": "YouTube Description Updater",
        "schedule": dict(SCHEDULE_PRESETS["manual"]),
        "required_env": [
            "YOUTUBE_API_KEY",
            "YOUTUBE_CHANNEL_ID",
            "YOUTUBE_OAUTH_TOKEN",
        ],
    },
    "content_engine": {
        "display_name": "Multi-Platform Content Engine",
        "schedule": dict(SCHEDULE_PRESETS["manual"]),
        "required_env": ["OPENROUTER_API_KEY"],
    },
    "instagram_comments": {
        "display_name": "Instagram Comment Replies",
        "schedule": dict(SCHEDULE_PRESETS["every_5_minutes"]),
        "required_env": [
            "OPENROUTER_API_KEY",
            "META_ACCESS_TOKEN",
            "INSTAGRAM_BUSINESS_ID",
        ],
    },
}
PUBLISHER_ENV: dict[str, tuple[str, ...]] = {
    "twitter": (
        "TWITTER_API_KEY",
        "TWITTER_API_SECRET",
        "TWITTER_ACCESS_TOKEN",
        "TWITTER_ACCESS_SECRET",
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
    return _is_production() or os.getenv("APP_ORIGIN", "").lower().startswith(
        "https://"
    )


def _secure_configuration() -> tuple[str, str]:
    username = os.getenv("ADMIN_USERNAME", "admin").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "")
    if len(password) < 12 or password.lower().startswith(("change-me", "password")):
        raise RuntimeError(
            "ADMIN_PASSWORD must be a newly rotated password of at least 12 characters"
        )
    if _is_production():
        if len(os.getenv("INTERNAL_SERVICE_TOKEN", "").strip()) < 32:
            raise RuntimeError(
                "INTERNAL_SERVICE_TOKEN must contain at least 32 random characters"
            )
        if not os.getenv("APP_ORIGIN", "").strip().startswith("https://"):
            raise RuntimeError("APP_ORIGIN must be an HTTPS origin in production")
        integration_vault.validate_encryption_key()
    return username, password


async def _seed_workflows() -> None:
    async with async_session() as session:
        for workflow_id, spec in WORKFLOW_SPECS.items():
            if await session.get(WorkflowDefinitionModel, workflow_id) is None:
                session.add(
                    WorkflowDefinitionModel(
                        id=workflow_id,
                        display_name=spec["display_name"],
                        is_enabled=False,
                        is_paused=False,
                        schedule=spec["schedule"],
                        settings={},
                        credential_status="untested",
                    )
                )
        await session.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    username, password = _secure_configuration()
    await auth_service.ensure_admin(
        username,
        password,
        rotate_password=os.getenv("ROTATE_ADMIN_PASSWORD_ON_STARTUP", "0") == "1",
    )
    await _seed_workflows()
    yield


docs_enabled = not _is_production()
app = FastAPI(
    title="AI Council OS",
    version="1.0.0",
    description="Approval-gated Grant, Sales, and Content councils",
    docs_url="/docs" if docs_enabled else None,
    redoc_url=None,
    openapi_url="/openapi.json" if docs_enabled else None,
    lifespan=lifespan,
)
app.add_middleware(SecurityHeadersMiddleware)
origins = sorted(allowed_browser_origins())
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID", "Idempotency-Key"],
)
hosts = [
    v.strip()
    for v in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
    if v.strip()
]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)


def _api_error(
    code_status: int, code: str, message: str, **details: Any
) -> HTTPException:
    return HTTPException(
        code_status, detail={"code": code, "message": message, "details": details}
    )


@app.exception_handler(HTTPException)
async def handle_http_error(_: Request, exc: HTTPException):
    error = (
        exc.detail
        if isinstance(exc.detail, dict) and "code" in exc.detail
        else {
            "code": "HTTP_ERROR",
            "message": str(exc.detail),
            "details": {},
        }
    )
    return JSONResponse(
        status_code=exc.status_code, content={"error": error}, headers=exc.headers
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError):
    fields = [
        {key: value for key, value in error.items() if key not in {"ctx", "url"}}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": {"fields": fields},
            }
        },
    )


def _mutation(
    resource: dict[str, Any], version: int, audit_event_id: str, **extra: Any
) -> dict[str, Any]:
    return {
        "resource": resource,
        "version": version,
        "audit_event_id": audit_event_id,
        **extra,
    }


def _mutation_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


async def _mutation_replay(
    scope: str,
    idempotency_key: str,
    request_payload: dict[str, Any],
    *,
    session=None,
) -> dict[str, Any] | None:
    async def read(active_session):
        record = (
            await active_session.execute(
                select(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.scope == scope,
                    IdempotencyRecordModel.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if not record:
            return None
        if record.request_hash != _mutation_hash(request_payload):
            raise _api_error(
                409,
                "IDEMPOTENCY_KEY_REUSED",
                "Idempotency key was reused with a different request",
            )
        return {**(record.response_payload or {}), "replayed": True}

    if session is not None:
        return await read(session)
    async with async_session() as owned_session:
        return await read(owned_session)


async def _store_mutation_replay(
    scope: str,
    idempotency_key: str,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any],
    resource_id: str,
    *,
    session=None,
) -> None:
    record = IdempotencyRecordModel(
        scope=scope,
        idempotency_key=idempotency_key,
        request_hash=_mutation_hash(request_payload),
        response_payload=response_payload,
        resource_id=resource_id,
        expires_at=utcnow() + timedelta(days=30),
    )
    if session is not None:
        session.add(record)
        return
    async with async_session() as owned_session:
        owned_session.add(record)
        await owned_session.commit()


async def _commit_idempotent_mutation(
    session,
    *,
    scope: str,
    idempotency_key: str,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any],
    resource_id: str,
) -> dict[str, Any]:
    """Commit resource, audit event, and replay record in one transaction.

    If two identical requests race, the losing transaction rolls back all of
    its resource changes and returns the winner's persisted response.
    """
    await _store_mutation_replay(
        scope,
        idempotency_key,
        request_payload,
        response_payload,
        resource_id,
        session=session,
    )
    try:
        await session.commit()
        return response_payload
    except IntegrityError:
        await session.rollback()
        replay = await _mutation_replay(scope, idempotency_key, request_payload)
        if replay is not None:
            return replay
        raise


async def _begin_idempotent_mutation(
    session,
    *,
    scope: str,
    idempotency_key: str,
    request_payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Serialize one mutation key and read its replay in the same transaction.

    PostgreSQL advisory transaction locks prevent two workers from performing
    the same side effect before either can persist the unique replay record.
    SQLite is development-only; its unique constraint still makes the losing
    transaction roll back atomically in ``_commit_idempotent_mutation``.
    """
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"{scope}:{idempotency_key}"},
        )
    return await _mutation_replay(
        scope,
        idempotency_key,
        request_payload,
        session=session,
    )


def _new_job(
    *,
    workflow_id: str,
    job_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
    max_attempts: int = 5,
    priority: int = 0,
) -> WorkflowRunModel:
    """Build a durable job that can be committed with its parent mutation."""
    return WorkflowRunModel(
        workflow_id=workflow_id,
        job_type=job_type,
        payload=payload,
        idempotency_key=idempotency_key,
        max_attempts=max_attempts,
        priority=priority,
    )


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
    records = (
        (definition.settings or {}).get("publishing_verifications", {})
        if definition
        else {}
    )
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
                "verified"
                if verified
                else "configured"
                if configured.get(platform)
                else "missing"
            ),
            "message": (
                str(record.get("message", ""))
                if fingerprint_matches
                else "Credentials changed since the last verification"
                if record
                else "Not verified"
            ),
            "verified_at": str(record.get("verified_at", ""))
            if fingerprint_matches
            else "",
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
                if (
                    configured.get("type") == "interval"
                    and configured.get("seconds") == seconds
                ):
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
        "id": item.id,
        "display_name": item.display_name,
        "is_enabled": item.is_enabled,
        "is_paused": item.is_paused,
        "schedule": _public_schedule(item.schedule or {}),
        "settings": settings,
        "credential_status": item.credential_status,
        "version": item.version,
        "missing_configuration": (
            [] if item.credential_status == "verified" else _missing_config(item.id)
        ),
        "updated_at": iso(item.updated_at),
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
    linked = (
        (
            await session.execute(
                select(WorkflowIntegrationModel.provider).where(
                    WorkflowIntegrationModel.workflow_id == definition.id
                )
            )
        )
        .scalars()
        .first()
    )
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
        "id": run.id,
        "task_id": run.task_id,
        "council": run.council,
        "status": run.status,
        "priority": run.priority,
        "prompt": run.prompt,
        "context": run.context or {},
        "final_output": run.final_output or {},
        "confidence_score": run.confidence_score,
        "total_input_tokens": run.total_input_tokens,
        "total_output_tokens": run.total_output_tokens,
        "total_cost_usd": run.total_cost_usd,
        "warning": run.warning,
        "error": run.error,
        "version": run.version,
        "created_at": iso(run.created_at),
        "updated_at": iso(run.updated_at),
    }


def _task_json(
    task: TaskModel, approval: ApprovalModel | None = None
) -> dict[str, Any]:
    payload = task.to_dict()
    payload.update(
        {
            "approval_id": approval.id if approval else None,
            "approval_status": approval.status if approval else None,
            "approval_version": approval.version if approval else None,
        }
    )
    return payload


async def _task_and_approval(task_id: str) -> tuple[TaskModel, ApprovalModel | None]:
    async with async_session() as session:
        task = await session.get(TaskModel, task_id)
        if task is None:
            raise _api_error(404, "TASK_NOT_FOUND", "Task does not exist")
        result = await session.execute(
            select(ApprovalModel).where(
                ApprovalModel.resource_type == "task",
                ApprovalModel.resource_id == task_id,
            )
        )
        return task, result.scalar_one_or_none()


@app.get("/")
@app.get("/healthz")
async def health_check():
    return {"status": "online", "service": "AI Council OS", "version": "1.0.0"}


@app.get("/readyz")
async def readiness_check():
    db_ok = await database_ready()
    try:
        # Production credentials live in the encrypted integration vault, not
        # necessarily in process environment variables. Readiness must test
        # the same verified credential source used by durable council jobs.
        try:
            model_configuration = await integration_vault.decrypted_provider_env(
                "openrouter"
            )
        except integration_vault.VaultConfigurationError:
            model_configuration = {}
        with use_integration_configuration(model_configuration):
            models = await validate_approved_models()
    except Exception as exc:
        models = {"ready": False, "error": f"{type(exc).__name__}: {exc}"}
    ready = db_ok and bool(models.get("ready"))
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"ready": ready, "database": db_ok, "models": models},
    )


# Authentication
@app.post("/api/auth/login")
async def login(request: Request, response: Response, credentials: LoginRequest):
    try:
        created = await auth_service.authenticate(
            credentials.username,
            credentials.password,
            client_ip=request.client.host if request.client else "unknown",
            user_agent=request.headers.get("user-agent", ""),
        )
    except AuthLocked as exc:
        raise _api_error(
            429, exc.code, str(exc), retry_after_seconds=exc.retry_after_seconds
        ) from exc
    except AuthInvalidCredentials as exc:
        raise _api_error(401, exc.code, str(exc)) from exc
    max_age = max(1, int((created.expires_at - utcnow()).total_seconds()))
    options = {
        "secure": _cookie_secure(),
        "samesite": "strict",
        "path": "/",
        "max_age": max_age,
    }
    response.set_cookie(
        SESSION_COOKIE_NAME, created.session_token, httponly=True, **options
    )
    response.set_cookie(CSRF_COOKIE_NAME, created.csrf_token, httponly=False, **options)
    return {
        "status": "authenticated",
        "user": created.user,
        "csrf_token": created.csrf_token,
        "expires_at": iso(created.expires_at),
    }


@app.get("/api/auth/session")
@app.get("/api/auth/me", deprecated=True)
async def get_session(
    actor: RequestActor = Depends(require_admin),
    csrf_cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE_NAME),
):
    if actor.actor_type != "user":
        raise _api_error(
            401, "USER_SESSION_REQUIRED", "A dashboard user session is required"
        )
    return {
        "authenticated": True,
        "user": {"id": actor.user_id, "username": actor.username, "role": actor.role},
        "csrf_token": csrf_cookie or "",
    }


@app.post("/api/auth/logout")
async def logout(
    response: Response,
    actor: RequestActor = Depends(require_admin),
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
    council: str | None = None,
    _: RequestActor = Depends(require_admin),
):
    async with async_session() as session:
        query = (
            select(TaskModel, ApprovalModel)
            .outerjoin(
                ApprovalModel,
                (ApprovalModel.resource_type == "task")
                & (ApprovalModel.resource_id == TaskModel.task_id),
            )
            .order_by(TaskModel.created_at.desc())
        )
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
    payload: CouncilRunRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin_or_telegram),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if (await get_kill_switch_db())["is_active"]:
        raise _api_error(423, "KILL_SWITCH_ACTIVE", "Global kill switch is active")
    if idempotency_key and not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", idempotency_key):
        raise _api_error(
            422, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key has an invalid format"
        )
    if payload.council != "grant" and (
        payload.selected_document_hashes or payload.selected_collection_ids
    ):
        raise _api_error(
            422,
            "GRANT_ONLY_SETTING",
            "Per-run evidence selection is available only for Grant Council; configure Sales and Content collections in Knowledge.",
        )
    if payload.selected_collection_ids:
        async with async_session() as session:
            found = int(
                await session.scalar(
                    select(func.count(KnowledgeCollectionModel.id)).where(
                        KnowledgeCollectionModel.id.in_(payload.selected_collection_ids)
                    )
                )
                or 0
            )
        if found != len(payload.selected_collection_ids):
            raise _api_error(
                404,
                "COLLECTION_NOT_FOUND",
                "One or more selected collections do not exist",
            )
    job_key = f"council:{idempotency_key or uuid.uuid4()}"
    async with async_session() as session:
        existing = (
            await session.execute(
                select(WorkflowRunModel).where(
                    WorkflowRunModel.idempotency_key == job_key
                )
            )
        ).scalar_one_or_none()
        if existing:
            task = await session.get(TaskModel, existing.payload.get("task_id"))
            if task:
                return _mutation(
                    task.to_dict(), task.version, "", replayed=True, job_id=existing.id
                )
        task_id = str(uuid.uuid4())
        context = dict(payload.context)
        # Selected knowledge is accepted only through the validated hash list,
        # never through an arbitrary context object.
        context.pop("selected_docs", None)
        context.pop("selected_collection_ids", None)
        if payload.selected_document_hashes:
            context["selected_docs"] = payload.selected_document_hashes
        if payload.selected_collection_ids:
            context["selected_collection_ids"] = payload.selected_collection_ids
        task = TaskModel(
            task_id=task_id,
            council=payload.council,
            status="queued",
            task_description=payload.task_description,
            context=context,
        )
        run = CouncilRunModel(
            task_id=task_id,
            council=payload.council,
            status="queued",
            priority=payload.priority,
            prompt=payload.task_description,
            context=context,
        )
        approval = ApprovalModel(
            resource_type="task",
            resource_id=task_id,
            status="awaiting_approval",
            version=1,
        )
        # SQLAlchemy cannot infer flush ordering from bare foreign-key values
        # when no ORM relationship is present.  PostgreSQL enforces the
        # council_runs.task_id foreign key immediately, so persist the parent
        # task before inserting the run and approval rows.
        session.add(task)
        await session.flush()
        session.add_all([run, approval])
        await session.flush()
        context["run_id"] = run.id
        context["priority"] = payload.priority
        task.context = context
        run.context = context
        job = WorkflowRunModel(
            workflow_id=f"{payload.council}-council",
            job_type="council.run",
            payload={
                "task_id": task_id,
                "run_id": run.id,
                "council": payload.council,
                "task_description": payload.task_description,
                "context": context,
                "priority": payload.priority,
            },
            idempotency_key=job_key,
            priority=10 if payload.priority == "high" else 0,
        )
        session.add(job)
        await session.flush()
        event = await record_audit(
            session,
            action="council_run.queued",
            resource_type="task",
            resource_id=task_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"run_id": run.id, "council": payload.council, "job_id": job.id},
        )
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise _api_error(
                409, "COUNCIL_RUN_CONFLICT", "Council run could not be queued"
            ) from exc
    return _mutation(
        task.to_dict(), task.version, event.id, run=_run_json(run), job_id=job.id
    )


@app.get("/api/council-runs")
async def list_council_runs(_: RequestActor = Depends(require_admin)):
    async with async_session() as session:
        runs = (
            (
                await session.execute(
                    select(CouncilRunModel).order_by(CouncilRunModel.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
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
async def _queue_after_approval(
    task: TaskModel, approval: ApprovalModel, action: str
) -> None:
    if action == "retry":
        job_key = f"retry:{approval.id}:{approval.version}"
        async with async_session() as session:
            existing = (
                await session.execute(
                    select(WorkflowRunModel).where(
                        WorkflowRunModel.idempotency_key == job_key
                    )
                )
            ).scalar_one_or_none()
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
            session.add(
                WorkflowRunModel(
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
                )
            )
            await session.commit()
        return
    if action != "approve":
        return
    await _queue_hubspot_after_sales_approval(task, approval)
    context, workflow = task.context or {}, (task.context or {}).get("workflow", "")
    if (
        not workflow
        or workflow == "reddit_prospector"
        or (workflow == "content_engine" and context.get("platform") == "reddit")
    ):
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
    elif workflow == "content_engine" and str(context.get("platform", "")).lower() in {
        "x",
        "twitter",
        "linkedin",
        "facebook",
        "instagram",
        "discord",
    }:
        job_type, platform = "publish.social", str(context["platform"]).lower()
    else:
        return
    key = f"publish:{approval.id}:{approval.version}"
    async with async_session() as session:
        if (
            await session.execute(
                select(PublicationAttemptModel).where(
                    PublicationAttemptModel.idempotency_key == key
                )
            )
        ).scalar_one_or_none():
            return
        attempt = PublicationAttemptModel(
            approval_id=approval.id,
            platform=platform,
            status="queued",
            idempotency_key=key,
            request_payload={
                "task_id": task.task_id,
                "content": task.final_output,
                "context": context,
            },
        )
        session.add(attempt)
        await session.flush()
        session.add(
            WorkflowRunModel(
                workflow_id=workflow,
                job_type=job_type,
                payload={
                    "task_id": task.task_id,
                    "approval_id": approval.id,
                    "publication_attempt_id": attempt.id,
                    "platform": platform,
                    "content": task.final_output,
                    "context": context,
                },
                idempotency_key=key,
                priority=5,
                # Most social/YouTube write APIs do not provide a portable
                # idempotency primitive. Never auto-retry an ambiguous write.
                max_attempts=1,
            )
        )
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
        existing = (
            await session.execute(
                select(PublicationAttemptModel).where(
                    PublicationAttemptModel.idempotency_key == key
                )
            )
        ).scalar_one_or_none()
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
        session.add(
            WorkflowRunModel(
                workflow_id=workflow or "sales_council",
                job_type="crm.hubspot_sync",
                payload={
                    "task_id": task.task_id,
                    "approval_id": approval.id,
                    "publication_attempt_id": attempt.id,
                    "target_type": "workflow"
                    if workflow == "reddit_prospector"
                    else "council",
                    "target_id": workflow
                    if workflow == "reddit_prospector"
                    else "sales",
                },
                idempotency_key=key,
                priority=5,
                max_attempts=3,
            )
        )
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
    task_id: str,
    payload: ApprovalActionRequest,
    request: Request,
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
    if (
        payload.action == "approve"
        and workflow == "content_engine"
        and platform != "reddit"
    ):
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
            ready = bool(
                definition and await _workflow_credentials_current(session, definition)
            )
        if (
            not ready
            or not definition
            or not definition.is_enabled
            or definition.is_paused
        ):
            raise _api_error(
                409,
                "INSTAGRAM_COMMENTS_NOT_READY",
                "Enable Instagram Comment Replies with verified Meta and OpenRouter connections before approval",
            )
    try:
        result = await approval_service.act(
            approval.id,
            action=payload.action,
            expected_version=payload.expected_version,
            idempotency_key=payload.idempotency_key,
            actor_user_id=actor.user_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            notes=payload.notes,
            edited_output={"content": payload.edited_output}
            if payload.edited_output
            else {},
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
                current.final_output, current.version = (
                    payload.edited_output,
                    current.version + 1,
                )
                await session.commit()
        task, approval = await _task_and_approval(task_id)
    assert approval is not None
    # Queueing is itself idempotent. Re-run this bridge for replayed requests so
    # a crash after the approval commit but before job creation can self-heal.
    await _queue_after_approval(task, approval, payload.action)
    if payload.action == "approve":
        await job_service.enqueue(
            workflow_id="brain",
            job_type="brain.learn",
            payload={"task_id": task_id},
            idempotency_key=f"brain.learn:{task_id}:approval-v{approval.version}",
            priority=-1,
            max_attempts=3,
        )
    task, approval = await _task_and_approval(task_id)
    return _mutation(
        _task_json(task, approval),
        approval.version,
        result.audit_event_id,
        replayed=result.replayed,
    )


@app.post("/api/tasks/{task_id}/approve", deprecated=True)
async def legacy_approval(
    task_id: str,
    payload: LegacyApprovalRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin_or_telegram),
):
    _, approval = await _task_and_approval(task_id)
    if not approval:
        raise _api_error(404, "APPROVAL_NOT_FOUND", "Task is not awaiting approval")
    normalized = ApprovalActionRequest(
        action="approve" if payload.approved else "reject",
        expected_version=payload.expected_version or approval.version,
        idempotency_key=payload.idempotency_key or f"legacy:{uuid.uuid4()}",
        edited_output=payload.edited_output,
        notes=payload.notes,
    )
    return await act_on_approval(task_id, normalized, request, actor)


# Durable workflow management
@app.get("/api/workflows")
async def list_workflows(_: RequestActor = Depends(require_admin)):
    async with async_session() as session:
        items = (
            (
                await session.execute(
                    select(WorkflowDefinitionModel).order_by(WorkflowDefinitionModel.id)
                )
            )
            .scalars()
            .all()
        )
        runs = (
            (
                await session.execute(
                    select(WorkflowRunModel)
                    .where(
                        WorkflowRunModel.workflow_id.in_([item.id for item in items])
                    )
                    .order_by(WorkflowRunModel.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
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
        runs = (
            (
                await session.execute(
                    select(WorkflowRunModel)
                    .where(WorkflowRunModel.workflow_id == workflow_id)
                    .order_by(WorkflowRunModel.created_at.desc())
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
        providers = (
            (
                await session.execute(
                    select(WorkflowIntegrationModel.provider)
                    .where(WorkflowIntegrationModel.workflow_id == workflow_id)
                    .order_by(WorkflowIntegrationModel.provider)
                )
            )
            .scalars()
            .all()
        )
    if not item:
        raise _api_error(404, "WORKFLOW_NOT_FOUND", "Workflow does not exist")
    return {
        **_workflow_json(item),
        "runs": [_workflow_job_json(run) for run in runs],
        "integration_providers": list(providers),
    }


@app.patch("/api/workflows/{workflow_id}")
async def patch_workflow(
    workflow_id: str,
    payload: WorkflowPatchRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    if workflow_id not in WORKFLOW_SPECS:
        raise _api_error(404, "WORKFLOW_NOT_FOUND", "Workflow does not exist")
    if payload.selected_document_hashes or payload.selected_collection_ids:
        raise _api_error(
            422,
            "GRANT_ONLY_SETTING",
            "Workflow knowledge is controlled only by administrator collection bindings",
        )
    async with async_session() as session:
        item = await session.get(
            WorkflowDefinitionModel, workflow_id, with_for_update=True
        )
        if not item:
            raise _api_error(404, "WORKFLOW_NOT_FOUND", "Workflow does not exist")
        if payload.enabled is not None:
            if payload.enabled and not await _workflow_credentials_current(
                session, item
            ):
                raise _api_error(
                    409,
                    "INTEGRATION_NOT_VERIFIED",
                    "Verify credentials before enabling this workflow",
                )
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
        for retired_scope_key in (
            "selected_document_hashes",
            "selected_collection_ids",
            "collection_ids",
        ):
            settings.pop(retired_scope_key, None)
        if payload.custom_prompt is not None:
            settings["custom_prompt"] = payload.custom_prompt
        item.settings, item.version, item.updated_at = (
            settings,
            item.version + 1,
            utcnow(),
        )
        event = await record_audit(
            session,
            action="workflow.updated",
            resource_type="workflow",
            resource_id=workflow_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details=payload.model_dump(exclude_none=True),
        )
        await session.commit()
        await session.refresh(item)
    return _mutation(_workflow_json(item), item.version, event.id)


@app.post("/api/workflows/{workflow_id}/trigger")
async def trigger_workflow(
    workflow_id: str,
    payload: WorkflowTriggerRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    if workflow_id not in WORKFLOW_SPECS or workflow_id == "telegram_control":
        raise _api_error(
            404, "WORKFLOW_NOT_TRIGGERABLE", "Workflow cannot be manually triggered"
        )
    if any(
        payload.payload.get(key)
        for key in (
            "selected_document_hashes",
            "selected_collection_ids",
            "collection_ids",
        )
    ):
        raise _api_error(
            422,
            "GRANT_ONLY_SETTING",
            "Workflow knowledge is controlled only by administrator collection bindings",
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
        raise _api_error(
            409, "INTEGRATION_NOT_VERIFIED", "Workflow credentials are not verified"
        )
    job = await job_service.enqueue(
        workflow_id=workflow_id,
        job_type=f"workflow.{workflow_id}",
        payload={
            **{
                key: value
                for key, value in (definition.settings or {}).items()
                if key
                not in {
                    "selected_document_hashes",
                    "selected_collection_ids",
                    "collection_ids",
                }
            },
            **{
                key: value
                for key, value in payload.payload.items()
                if key
                not in {
                    "selected_document_hashes",
                    "selected_collection_ids",
                    "collection_ids",
                }
            },
        },
        idempotency_key=f"trigger:{workflow_id}:{payload.idempotency_key}",
    )
    async with async_session() as session:
        event = await record_audit(
            session,
            action="workflow.triggered",
            resource_type="workflow_run",
            resource_id=job.id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"workflow_id": workflow_id},
        )
        await session.commit()
    return _mutation(
        {
            "id": job.id,
            "workflow_id": job.workflow_id,
            "status": job.status,
            "version": job.version,
        },
        job.version,
        event.id,
    )


@app.post("/api/workflows/content-engine", deprecated=True)
async def legacy_content_trigger(
    payload: ContentEngineRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    trigger = WorkflowTriggerRequest(
        payload=payload.model_dump(), idempotency_key=f"content:{uuid.uuid4()}"
    )
    return await trigger_workflow("content_engine", trigger, request, actor)


# Kill switch
@app.get("/api/kill-switch")
async def get_kill_switch(_: RequestActor = Depends(require_admin_or_telegram)):
    return await get_kill_switch_db()


@app.put("/api/kill-switch")
async def put_kill_switch(
    payload: KillSwitchRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin_or_telegram),
):
    resource = await set_kill_switch_db(
        payload.active,
        toggled_by=f"{actor.actor_type}:{actor.actor_id}",
        reason=payload.reason,
    )
    async with async_session() as session:
        event = await record_audit(
            session,
            action="kill_switch.activated"
            if payload.active
            else "kill_switch.deactivated",
            resource_type="kill_switch",
            resource_id="global",
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"reason": payload.reason},
        )
        await session.commit()
    return _mutation(resource, 1, event.id)


@app.post("/api/kill-switch/activate", deprecated=True)
async def legacy_activate(
    request: Request,
    reason: str = "Activated via dashboard",
    actor: RequestActor = Depends(require_admin),
):
    return await put_kill_switch(
        KillSwitchRequest(active=True, reason=reason), request, actor
    )


@app.post("/api/kill-switch/deactivate", deprecated=True)
async def legacy_deactivate(
    request: Request, actor: RequestActor = Depends(require_admin)
):
    return await put_kill_switch(KillSwitchRequest(active=False), request, actor)


# Integration verification and truthful health
async def _verify_integration(workflow_id: str) -> dict[str, Any]:
    if _missing_config(workflow_id):
        return {"verified": False, "message": "Required configuration is missing"}
    try:
        if workflow_id == "content_engine":
            result = await validate_approved_models(cache_seconds=0)
            if not result.get("ready"):
                return {
                    "verified": False,
                    "message": "An approved model is unavailable",
                }
        elif workflow_id == "telegram_control":
            import httpx

            raw_chat_ids = [
                value.strip()
                for value in os.environ["TELEGRAM_ALLOWED_CHAT_IDS"].split(",")
                if value.strip()
            ]
            if len(raw_chat_ids) != 1:
                return {
                    "verified": False,
                    "message": "Exactly one administrator private-chat ID is required",
                }
            try:
                int(raw_chat_ids[0])
            except ValueError:
                return {
                    "verified": False,
                    "message": "Administrator chat ID must be numeric",
                }
            token = os.environ["TELEGRAM_BOT_TOKEN"]
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    f"https://api.telegram.org/bot{token}/getMe"
                )
                response.raise_for_status()
                if not response.json().get("ok"):
                    return {
                        "verified": False,
                        "message": "Telegram rejected the bot token",
                    }
        elif workflow_id in {"youtube_comments", "youtube_descriptions"}:
            from src.integrations.youtube import verify_youtube_connection

            await asyncio.to_thread(
                verify_youtube_connection, os.environ["YOUTUBE_CHANNEL_ID"]
            )
        elif workflow_id == "reddit_prospector":
            from src.integrations.reddit import get_reddit_client

            client = get_reddit_client()
            await asyncio.to_thread(
                lambda: next(iter(client.subreddit("all").new(limit=1)), None)
            )
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
                    params={
                        "fields": "id,username",
                        "access_token": os.environ["INSTAGRAM_ACCESS_TOKEN"],
                    },
                )
                response.raise_for_status()
        elif platform == "facebook":
            graph_version = os.getenv("META_GRAPH_API_VERSION", "v23.0")
            token = os.getenv("META_ACCESS_TOKEN") or os.getenv(
                "INSTAGRAM_ACCESS_TOKEN"
            )
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
                    headers={
                        "Authorization": f"Bearer {os.environ['LINKEDIN_ACCESS_TOKEN']}"
                    },
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
                    raise RuntimeError(
                        "X/Twitter did not return the authenticated account"
                    )

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
    workflow_id: str,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    if workflow_id not in WORKFLOW_SPECS:
        raise _api_error(404, "INTEGRATION_NOT_FOUND", "Integration does not exist")
    result = await _verify_integration(workflow_id)
    async with async_session() as session:
        item = await session.get(
            WorkflowDefinitionModel, workflow_id, with_for_update=True
        )
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
            session,
            action="integration.verified"
            if result["verified"]
            else "integration.failed",
            resource_type="workflow",
            resource_id=workflow_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"message": result["message"]},
        )
        await session.commit()
        await session.refresh(item)
    return _mutation(_workflow_json(item), item.version, event.id, verification=result)


@app.post("/api/integrations/publishing/{platform}/verify")
async def verify_publishing_integration(
    platform: str,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    platform = platform.lower()
    if platform == "x":
        platform = "twitter"
    if platform not in PUBLISHER_ENV:
        raise _api_error(
            404,
            "PUBLISHING_INTEGRATION_NOT_FOUND",
            "Publishing destination does not exist",
        )
    result = await _verify_publisher(platform)
    async with async_session() as session:
        definition = await session.get(
            WorkflowDefinitionModel, "content_engine", with_for_update=True
        )
        if not definition:
            raise _api_error(
                503, "WORKFLOW_NOT_INITIALIZED", "Content Engine is not initialized"
            )
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
            action="publishing_integration.verified"
            if result["verified"]
            else "publishing_integration.failed",
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
    return {
        "integrations": [
            _connection_resource(item)
            for item in await integration_vault.list_connections()
        ]
    }


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
        item
        for item in await integration_vault.list_connections()
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
        raise _api_error(
            404, "INTEGRATION_NOT_CONFIGURED", "Integration is not configured"
        )
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
                    raise RuntimeError(
                        "Exactly one numeric administrator chat ID is required"
                    )
                async with httpx.AsyncClient(timeout=15) as client:
                    base = f"https://api.telegram.org/bot{values['TELEGRAM_BOT_TOKEN']}"
                    response = await client.get(f"{base}/getMe")
                    response.raise_for_status()
                    if not response.json().get("ok"):
                        raise RuntimeError("Telegram rejected the bot token")
                    chat = await client.get(
                        f"{base}/getChat", params={"chat_id": chat_ids[0]}
                    )
                    chat.raise_for_status()
                    chat_payload = chat.json()
                    if (
                        not chat_payload.get("ok")
                        or (chat_payload.get("result") or {}).get("type") != "private"
                    ):
                        raise RuntimeError(
                            "Telegram administrator target must be a reachable private chat"
                        )
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
                    if organization
                    else "https://api.linkedin.com/v2/me"
                )
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.get(
                        endpoint,
                        headers={
                            "Authorization": f"Bearer {values['LINKEDIN_ACCESS_TOKEN']}"
                        },
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
                                if instagram_id
                                else "id,name"
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
                            raise RuntimeError(
                                "Meta reported that the access token is invalid"
                            )
                        if instagram_id:
                            scopes = set(token_data.get("scopes") or [])
                            if not scopes.intersection(
                                {
                                    "instagram_manage_comments",
                                    "instagram_business_manage_comments",
                                }
                            ):
                                raise RuntimeError(
                                    "Meta token does not include Instagram comment-management permission"
                                )
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


async def _blender_runtime_release_status() -> dict[str, object]:
    """Return a truthful, non-secret release gate for pod provisioning/updates."""
    from src.integrations.runpod import (
        RunPodError,
        validate_blender_image,
        verify_blender_image_manifest,
    )

    image_name = os.getenv("BLENDER_RUNPOD_IMAGE", "").strip()
    if not image_name:
        return {
            "ready": False,
            "code": "BLENDER_IMAGE_NOT_PUBLISHED",
            "message": "No immutable Blender/Kasm image is configured.",
            "image_name": "",
            "digest": "",
        }
    try:
        image_name = validate_blender_image(image_name)
    except ValueError as exc:
        return {
            "ready": False,
            "code": "BLENDER_IMAGE_INVALID",
            "message": str(exc),
            "image_name": "",
            "digest": "",
        }
    approved_sha = os.getenv("BLENDER_RUNPOD_SMOKE_APPROVED_SHA", "").strip().lower()
    image_sha = image_name.rsplit(":", 1)[-1]
    if not (
        re.fullmatch(r"[a-f0-9]{40}", approved_sha)
        and hmac.compare_digest(image_sha, approved_sha)
    ):
        return {
            "ready": False,
            "code": "BLENDER_IMAGE_SMOKE_NOT_APPROVED",
            "message": "The configured image has not passed the controlled desktop and GPU smoke gate.",
            "image_name": image_name,
            "digest": "",
        }
    try:
        manifest = await verify_blender_image_manifest(image_name)
    except RunPodError as exc:
        return {
            "ready": False,
            "code": exc.code,
            "message": str(exc),
            "image_name": image_name,
            "digest": "",
        }
    return {
        "ready": True,
        "code": "BLENDER_RUNTIME_APPROVED",
        "message": "The immutable Blender/Kasm image is smoke-approved and publicly pullable.",
        "image_name": image_name,
        "digest": manifest["digest"],
    }


async def _require_blender_runtime_release() -> dict[str, object]:
    release = await _blender_runtime_release_status()
    if not release["ready"]:
        raise _api_error(503, str(release["code"]), str(release["message"]))
    return release


@app.get("/api/blender/pods")
async def get_blender_pods(_: RequestActor = Depends(require_admin)):
    """Return live RunPod state; never fabricate placeholder machines or costs."""
    from src.integrations.runpod import RunPodError, get_blender_runtime, list_pods

    values = await _provider_runtime("runpod")
    try:
        with use_integration_configuration(values):
            pods = await list_pods()
            for pod in pods:
                pod["agent_status"] = "not_running"
                pod["local_runtime"] = {}
                if pod.get("desired_status") != "RUNNING":
                    continue
                try:
                    pod["local_runtime"] = await asyncio.wait_for(
                        get_blender_runtime(str(pod.get("id", ""))), timeout=6
                    )
                    pod["agent_status"] = "live"
                except (TimeoutError, RunPodError):
                    pod["agent_status"] = "unavailable"
    except RunPodError as exc:
        raise _api_error(502, "RUNPOD_UNAVAILABLE", str(exc)) from exc
    return {
        "pods": pods,
        "provider": "runpod",
        "status": "verified",
        "approved_runtime": await _blender_runtime_release_status(),
    }


@app.post("/api/blender/pods")
async def provision_blender_pod(
    payload: BlenderPodProvisionRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    """Create one explicitly confirmed, on-demand RTX A6000 Kasm workstation."""
    from src.integrations.runpod import (
        RunPodError,
        create_a6000_pod,
        ensure_blender_template,
    )

    if (await get_kill_switch_db())["is_active"]:
        raise _api_error(
            423,
            "KILL_SWITCH_ACTIVE",
            "The system is stopped; resume it before creating a billable GPU Pod",
        )
    release = await _require_blender_runtime_release()
    image_name = str(release["image_name"])
    request_payload = {
        "confirm_billing": payload.confirm_billing,
        "image_name": image_name,
    }
    scope = f"blender.pod_provision:{actor.actor_id}"
    replay = await _mutation_replay(scope, payload.idempotency_key, request_payload)
    if replay is not None:
        return replay
    values = await _provider_runtime("runpod")
    try:
        with use_integration_configuration(values):
            template = await ensure_blender_template(image_name=image_name)
            pod = await create_a6000_pod(
                template_id=template["id"],
                image_name=image_name,
                agent_token=values["BLENDER_AGENT_TOKEN"],
                flamenco_proxy_token=values["FLAMENCO_WORKER_PROXY_TOKEN"],
                kasm_password=values["VNC_PW"],
                idempotency_key=payload.idempotency_key,
            )
    except (KeyError, ValueError) as exc:
        raise _api_error(422, "RUNPOD_PROVISION_INVALID", str(exc)) from exc
    except RunPodError as exc:
        raise _api_error(502, "RUNPOD_PROVISION_FAILED", str(exc)) from exc
    async with async_session() as session:
        event = await record_audit(
            session,
            action="blender.pod_provisioned",
            resource_type="runpod_pod",
            resource_id=pod.get("id", ""),
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={
                "template_id": template["id"],
                "image_name": image_name,
                "gpu_type": "NVIDIA RTX A6000",
                "gpu_count": 1,
                "cloud_type": "SECURE",
                "interruptible": False,
                "billing_confirmed": True,
            },
        )
        result = _mutation(pod, 1, event.id, template=template)
        await _store_mutation_replay(
            scope,
            payload.idempotency_key,
            request_payload,
            result,
            pod.get("id", ""),
            session=session,
        )
        await session.commit()
    return result


@app.post("/api/blender/pods/{pod_id}/actions")
async def act_on_blender_pod(
    pod_id: str,
    payload: BlenderPodActionRequest,
    request: Request,
    response: Response,
    actor: RequestActor = Depends(require_admin),
):
    """Operate or safely prepare a verified RunPod pod."""
    from src.integrations.runpod import (
        RunPodError,
        list_pods,
        resume_pod,
        stop_pod,
        update_pod_runtime,
    )

    if payload.action == "resume" and (await get_kill_switch_db())["is_active"]:
        raise _api_error(
            423,
            "KILL_SWITCH_ACTIVE",
            "The system is stopped; resume it before starting GPU billing",
        )
    values = await _provider_runtime("runpod")
    try:
        with use_integration_configuration(values):
            if payload.action in {"prepare_runtime", "reveal_access"}:
                pods = await list_pods()
                pod = next((item for item in pods if item.get("id") == pod_id), None)
                if pod is None:
                    raise _api_error(
                        404,
                        "RUNPOD_POD_NOT_FOUND",
                        "The selected pod is not in the verified RunPod account",
                    )
                if payload.action == "prepare_runtime":
                    if pod.get("desired_status") == "RUNNING":
                        raise _api_error(
                            409,
                            "RUNPOD_POD_MUST_BE_STOPPED",
                            "Stop the pod before replacing its container image; /workspace will remain preserved",
                        )
                    if not payload.inventory_confirmed:
                        raise _api_error(
                            409,
                            "RUNPOD_INVENTORY_REQUIRED",
                            "Before replacing the container, inventory /workspace and copy any critical files from container storage into /workspace",
                        )
                    release = await _require_blender_runtime_release()
                    image_name = str(release["image_name"])
                    pod = await update_pod_runtime(
                        pod_id,
                        image_name=image_name,
                        agent_token=values["BLENDER_AGENT_TOKEN"],
                        flamenco_proxy_token=values["FLAMENCO_WORKER_PROXY_TOKEN"],
                        kasm_password=values["VNC_PW"],
                    )
                    pod["runtime_prepared"] = True
            elif payload.action == "resume":
                pod = await resume_pod(pod_id)
            else:
                pod = await stop_pod(pod_id)
    except ValueError as exc:
        code = (
            "RUNPOD_RUNTIME_INVALID"
            if payload.action == "prepare_runtime"
            else "INVALID_POD_ID"
        )
        raise _api_error(422, code, str(exc)) from exc
    except RunPodError as exc:
        raise _api_error(
            exc.http_status,
            exc.code,
            str(exc),
            provider_status=exc.provider_status,
        ) from exc
    async with async_session() as session:
        event = await record_audit(
            session,
            action=f"blender.pod_{payload.action}",
            resource_type="runpod_pod",
            resource_id=pod_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={
                "desired_status": pod.get("desired_status", ""),
                "image_name": pod.get("image_name", "")
                if payload.action == "prepare_runtime"
                else "",
                "inventory_confirmed": bool(
                    payload.inventory_confirmed and payload.action == "prepare_runtime"
                ),
            },
        )
        await session.commit()
    result = _mutation(pod, 1, event.id)
    if payload.action == "reveal_access":
        response.headers["Cache-Control"] = "no-store"
        result["access"] = {
            "username": "kasm_user",
            "password": values["VNC_PW"],
            "url": pod.get("proxy_url", "")
            or f"https://{pod_id}-6901.proxy.runpod.net",
        }
    return result


@app.get("/api/blender/jobs")
async def list_blender_jobs(_: RequestActor = Depends(require_admin)):
    async with async_session() as session:
        jobs = (
            (
                await session.execute(
                    select(WorkflowRunModel)
                    .where(WorkflowRunModel.workflow_id == "blender_manager")
                    .order_by(WorkflowRunModel.created_at.desc())
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
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
        raise _api_error(
            423,
            "KILL_SWITCH_ACTIVE",
            "The system is stopped; resume it before starting GPU work",
        )
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
        raise _api_error(
            404,
            "RUNPOD_POD_NOT_FOUND",
            "The selected pod is not in the verified RunPod account",
        )
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


@app.get("/api/blender/render-jobs")
async def list_blender_render_jobs(_: RequestActor = Depends(require_admin)):
    from src.core.rendering import list_jobs

    return {"render_jobs": await list_jobs()}


@app.get("/api/blender/flamenco/status")
async def get_blender_flamenco_status(
    pod_id: str = Query(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9_-]+$"),
    _: RequestActor = Depends(require_admin),
):
    """Read Flamenco state through the authenticated pod agent."""
    from src.integrations.flamenco import get_flamenco_status
    from src.integrations.runpod import RunPodError

    values = await _provider_runtime("runpod")
    try:
        with use_integration_configuration(values):
            return await get_flamenco_status(pod_id)
    except RunPodError as exc:
        raise _api_error(502, "FLAMENCO_UNAVAILABLE", str(exc)) from exc


@app.post("/api/blender/flamenco/processes")
async def control_blender_flamenco_processes(
    payload: BlenderFlamencoProcessRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    """Start/stop the allowlisted Manager and Worker without exposing its API."""
    from src.integrations.flamenco import start_flamenco, stop_flamenco_process
    from src.integrations.runpod import RunPodError

    if payload.action == "start" and (await get_kill_switch_db())["is_active"]:
        raise _api_error(
            423, "KILL_SWITCH_ACTIVE", "Resume the system before starting Flamenco"
        )
    request_payload = payload.model_dump(mode="json")
    scope = f"blender.flamenco.process:{payload.pod_id}:{payload.role}:{payload.action}"
    async with async_session() as session:
        replay = await _begin_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=payload.idempotency_key,
            request_payload=request_payload,
        )
        if replay is not None:
            return replay
        values = await _provider_runtime("runpod")
        try:
            with use_integration_configuration(values):
                if payload.action == "start":
                    if payload.role == "manager":
                        raise _api_error(
                            422,
                            "INVALID_FLAMENCO_ROLE",
                            "Start the coordinator so Manager and its local Worker are brought up together",
                        )
                    resource = await start_flamenco(payload.pod_id, payload.role)
                elif payload.role == "coordinator":
                    worker = await stop_flamenco_process(payload.pod_id, "worker")
                    manager = await stop_flamenco_process(payload.pod_id, "manager")
                    resource = {"worker": worker, "manager": manager}
                else:
                    resource = await stop_flamenco_process(payload.pod_id, payload.role)
        except RunPodError as exc:
            raise _api_error(502, "FLAMENCO_ACTION_FAILED", str(exc)) from exc

        event = await record_audit(
            session,
            action=f"blender.flamenco_{payload.action}",
            resource_type="runpod_pod",
            resource_id=payload.pod_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"role": payload.role},
        )
        response_payload = _mutation(resource, 1, event.id)
        return await _commit_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=payload.idempotency_key,
            request_payload=request_payload,
            response_payload=response_payload,
            resource_id=payload.pod_id,
        )


@app.get("/api/blender/flamenco/logs/{role}")
async def get_blender_flamenco_logs(
    role: str,
    pod_id: str = Query(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9_-]+$"),
    _: RequestActor = Depends(require_admin),
):
    from src.integrations.flamenco import get_flamenco_logs
    from src.integrations.runpod import RunPodError

    if role not in {"manager", "worker"}:
        raise _api_error(422, "INVALID_FLAMENCO_ROLE", "Role must be manager or worker")
    values = await _provider_runtime("runpod")
    try:
        with use_integration_configuration(values):
            return await get_flamenco_logs(pod_id, role)
    except RunPodError as exc:
        raise _api_error(502, "FLAMENCO_UNAVAILABLE", str(exc)) from exc


@app.get("/api/blender/render-jobs/{render_job_id}")
async def get_blender_render_job(
    render_job_id: str,
    _: RequestActor = Depends(require_admin),
):
    from src.core.rendering import job_resource

    async with async_session() as session:
        job = await session.get(RenderJobModel, render_job_id)
    if job is None:
        raise _api_error(404, "RENDER_JOB_NOT_FOUND", "Render job does not exist")
    return job_resource(job)


@app.get("/api/blender/render-jobs/{render_job_id}/frames")
async def get_blender_render_frames(
    render_job_id: str,
    _: RequestActor = Depends(require_admin),
):
    from src.core.rendering import list_frames

    async with async_session() as session:
        exists = await session.get(RenderJobModel, render_job_id)
    if exists is None:
        raise _api_error(404, "RENDER_JOB_NOT_FOUND", "Render job does not exist")
    return {"frames": await list_frames(render_job_id)}


@app.get("/api/blender/render-jobs/{render_job_id}/telemetry")
async def get_blender_render_telemetry(
    render_job_id: str,
    limit: int = Query(default=600, ge=1, le=2000),
    _: RequestActor = Depends(require_admin),
):
    from src.core.rendering import list_telemetry

    async with async_session() as session:
        exists = await session.get(RenderJobModel, render_job_id)
    if exists is None:
        raise _api_error(404, "RENDER_JOB_NOT_FOUND", "Render job does not exist")
    return {"telemetry": await list_telemetry(render_job_id, limit)}


@app.get("/api/blender/render-jobs/{render_job_id}/artifacts")
async def get_blender_render_artifacts(
    render_job_id: str,
    _: RequestActor = Depends(require_admin),
):
    from src.core.rendering import list_artifacts

    async with async_session() as session:
        exists = await session.get(RenderJobModel, render_job_id)
    if exists is None:
        raise _api_error(404, "RENDER_JOB_NOT_FOUND", "Render job does not exist")
    return {"artifacts": await list_artifacts(render_job_id)}


@app.post("/api/blender/render-jobs")
async def create_blender_render_job(
    payload: BlenderRenderJobRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    """Create a one-GPU production render and atomically queue preflight."""
    from src.core.rendering import job_resource
    from src.integrations.runpod import RunPodError, list_pods

    if (await get_kill_switch_db())["is_active"]:
        raise _api_error(
            423, "KILL_SWITCH_ACTIVE", "Resume the system before starting GPU work"
        )
    if payload.scheduler == "flamenco" and payload.render_mode != "headless":
        raise _api_error(
            422,
            "FLAMENCO_HEADLESS_ONLY",
            "Flamenco schedules restartable headless batches; use the native mode for manual Kasm rendering",
        )
    values = await _provider_runtime("runpod")
    if len(values.get("BLENDER_AGENT_TOKEN", "")) < 32:
        raise _api_error(
            409,
            "BLENDER_AGENT_NOT_CONFIGURED",
            "Save the RunPod API key again so Council OS can generate the pod agent credentials",
        )
    try:
        with use_integration_configuration(values):
            pods = await list_pods()
    except RunPodError as exc:
        raise _api_error(502, "RUNPOD_UNAVAILABLE", str(exc)) from exc
    if not any(pod.get("id") == payload.pod_id for pod in pods):
        raise _api_error(
            404,
            "RUNPOD_POD_NOT_FOUND",
            "The selected pod is not in the verified account",
        )

    request_payload = payload.model_dump(mode="json")
    scope = "blender.render.create"
    async with async_session() as session:
        replay = await _begin_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=payload.idempotency_key,
            request_payload=request_payload,
        )
        if replay is not None:
            return replay
        render_job = RenderJobModel(
            pod_id=payload.pod_id,
            source_path=payload.source_path,
            status="queued",
            stage="render.preflight",
            render_mode=payload.render_mode,
            scheduler=payload.scheduler,
            coordinator_pod_id=payload.pod_id
            if payload.scheduler == "flamenco"
            else "",
            worker_pod_ids=[payload.pod_id] if payload.scheduler == "flamenco" else [],
            output_profile=payload.output_profile,
            frame_start=payload.frame_start,
            frame_end=payload.frame_end,
            frame_step=payload.frame_step,
            settings={
                "requested_frame_start": payload.frame_start,
                "requested_frame_end": payload.frame_end,
                "requested_frame_step": payload.frame_step,
                "samples": payload.samples,
                "resolution_percent": payload.resolution_percent,
                "persistent_data": False,
                "require_drive": payload.require_drive,
                "drive_path": payload.drive_path,
                "single_gpu_only": True,
                "scheduler": payload.scheduler,
            },
            auto_stop=payload.auto_stop,
        )
        session.add(render_job)
        await session.flush()
        stage_job = _new_job(
            workflow_id="blender_manager",
            job_type="blender.render_stage",
            payload={
                "render_job_id": render_job.id,
                "stage": "render.preflight",
                "frames": [],
            },
            idempotency_key=f"render:{render_job.id}:render.preflight",
            max_attempts=3,
            priority=20,
        )
        session.add(stage_job)
        event = await record_audit(
            session,
            action="blender.render_created",
            resource_type="render_job",
            resource_id=render_job.id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={
                "pod_id": payload.pod_id,
                "render_mode": payload.render_mode,
                "output_profile": payload.output_profile,
                "scheduler": payload.scheduler,
                "require_drive": payload.require_drive,
            },
        )
        response_payload = _mutation(
            job_resource(render_job), render_job.version, event.id
        )
        return await _commit_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=payload.idempotency_key,
            request_payload=request_payload,
            response_payload=response_payload,
            resource_id=render_job.id,
        )


@app.post("/api/blender/render-jobs/{render_job_id}/actions")
async def act_on_blender_render_job(
    render_job_id: str,
    payload: BlenderRenderActionRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    """Apply an optimistic, idempotent administrator render action."""
    from src.core.rendering import frame_batches, job_resource
    from src.integrations.flamenco import act_on_flamenco_job
    from src.integrations.runpod import RunPodError, stop_pod

    if payload.action in {
        "run_preflight",
        "approve_benchmark",
        "resume",
        "retry_failed_frames",
        "retry_delivery",
    }:
        if (await get_kill_switch_db())["is_active"]:
            raise _api_error(
                423, "KILL_SWITCH_ACTIVE", "Resume the system before starting GPU work"
            )
    request_payload = payload.model_dump(mode="json")
    scope = f"blender.render.action:{render_job_id}"
    stop_requested = False
    async with async_session() as session:
        replay = await _begin_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=payload.idempotency_key,
            request_payload=request_payload,
        )
        if replay is not None:
            return replay
        job = await session.get(RenderJobModel, render_job_id, with_for_update=True)
        if job is None:
            raise _api_error(404, "RENDER_JOB_NOT_FOUND", "Render job does not exist")
        if job.version != payload.expected_version:
            raise _api_error(
                409, "VERSION_CONFLICT", "Render job changed; refresh and try again"
            )

        new_jobs: list[WorkflowRunModel] = []
        batch_size = max(
            1,
            min(int((job.benchmark or {}).get("recommended_batch_size") or 1), 50),
        )
        if payload.action == "run_preflight":
            job.status, job.stage, job.error = "queued", "render.preflight", ""
            new_jobs.append(
                _new_job(
                    workflow_id="blender_manager",
                    job_type="blender.render_stage",
                    payload={
                        "render_job_id": job.id,
                        "stage": "render.preflight",
                        "frames": [],
                    },
                    idempotency_key=f"render:{job.id}:render.preflight:{payload.idempotency_key}",
                    priority=20,
                )
            )
        elif payload.action == "approve_benchmark":
            if job.status != "awaiting_benchmark_approval":
                raise _api_error(
                    409,
                    "RENDER_NOT_AWAITING_APPROVAL",
                    "Benchmark is not awaiting approval",
                )
            job.approved_at = utcnow()
            job.error = ""
            if job.render_mode == "kasm_gui":
                job.status, job.stage = "awaiting_kasm_render", "render.observe_gui"
                new_jobs.append(
                    _new_job(
                        workflow_id="blender_manager",
                        job_type="blender.render_stage",
                        payload={
                            "render_job_id": job.id,
                            "stage": "render.observe_gui",
                            "frames": [],
                        },
                        idempotency_key=f"render:{job.id}:render.observe_gui:{payload.idempotency_key}",
                        priority=20,
                        max_attempts=2,
                    )
                )
            else:
                if job.frame_start is None or job.frame_end is None:
                    raise _api_error(
                        409, "RENDER_RANGE_UNKNOWN", "Scene frame range is unavailable"
                    )
                if job.scheduler == "flamenco":
                    job.status, job.stage = (
                        "preparing_flamenco",
                        "render.prepare_flamenco",
                    )
                    new_jobs.append(
                        _new_job(
                            workflow_id="blender_manager",
                            job_type="blender.render_stage",
                            payload={
                                "render_job_id": job.id,
                                "stage": "render.prepare_flamenco",
                                "frames": [],
                            },
                            idempotency_key=f"render:{job.id}:render.prepare_flamenco:{payload.idempotency_key}",
                            priority=20,
                        )
                    )
                else:
                    numbers = list(
                        range(job.frame_start, job.frame_end + 1, job.frame_step)
                    )
                    job.status, job.stage = "rendering", "render.frame_batch"
                    batch = frame_batches(numbers, batch_size)[0]
                    digest = hashlib.sha256(
                        ",".join(map(str, batch)).encode()
                    ).hexdigest()[:16]
                    await session.execute(
                        update(RenderFrameModel)
                        .where(
                            RenderFrameModel.render_job_id == job.id,
                            RenderFrameModel.frame_number.in_(batch),
                        )
                        .values(batch_key=digest, status="pending")
                    )
                    new_jobs.append(
                        _new_job(
                            workflow_id="blender_manager",
                            job_type="blender.render_stage",
                            payload={
                                "render_job_id": job.id,
                                "stage": "render.frame_batch",
                                "frames": batch,
                            },
                            idempotency_key=f"render:{job.id}:render.frame_batch:{digest}",
                            priority=20,
                        )
                    )
        elif payload.action == "pause":
            if job.status in {"completed", "cancelled"}:
                raise _api_error(
                    409,
                    "RENDER_NOT_PAUSABLE",
                    "Completed or cancelled render cannot be paused",
                )
            if job.scheduler == "flamenco" and job.scheduler_job_id:
                values = await _provider_runtime("runpod")
                try:
                    with use_integration_configuration(values):
                        await act_on_flamenco_job(
                            job.coordinator_pod_id or job.pod_id,
                            job.scheduler_job_id,
                            "pause",
                            reason="Paused by Council OS administrator",
                        )
                except RunPodError as exc:
                    raise _api_error(502, "FLAMENCO_ACTION_FAILED", str(exc)) from exc
                job.status = "pausing"
                sequence = (
                    int((job.scheduler_state or {}).get("monitor_sequence") or 0) + 1
                )
                new_jobs.append(
                    _new_job(
                        workflow_id="blender_manager",
                        job_type="blender.flamenco_monitor",
                        payload={"render_job_id": job.id, "sequence": sequence},
                        idempotency_key=f"render:{job.id}:flamenco.monitor:{sequence}:{payload.idempotency_key}",
                        priority=20,
                    )
                )
            else:
                job.status = "paused"
        elif payload.action == "resume":
            if job.status != "paused":
                raise _api_error(409, "RENDER_NOT_PAUSED", "Render is not paused")
            if job.scheduler == "flamenco" and job.scheduler_job_id:
                values = await _provider_runtime("runpod")
                try:
                    with use_integration_configuration(values):
                        await act_on_flamenco_job(
                            job.coordinator_pod_id or job.pod_id,
                            job.scheduler_job_id,
                            "resume",
                            reason="Resumed by Council OS administrator",
                        )
                except RunPodError as exc:
                    raise _api_error(502, "FLAMENCO_ACTION_FAILED", str(exc)) from exc
                job.status, job.stage = "rendering", "render.flamenco"
                sequence = (
                    int((job.scheduler_state or {}).get("monitor_sequence") or 0) + 1
                )
                new_jobs.append(
                    _new_job(
                        workflow_id="blender_manager",
                        job_type="blender.flamenco_monitor",
                        payload={"render_job_id": job.id, "sequence": sequence},
                        idempotency_key=f"render:{job.id}:flamenco.monitor:{sequence}:{payload.idempotency_key}",
                        priority=20,
                    )
                )
            else:
                stage = (
                    job.stage if job.stage.startswith("render.") else "render.preflight"
                )
                if job.scheduler == "flamenco" and stage in {
                    "render.prepare_flamenco",
                    "render.flamenco_submit",
                    "render.flamenco",
                }:
                    stage = "render.prepare_flamenco"
            if job.scheduler != "flamenco" and stage == "render.frame_batch":
                remaining = (
                    (
                        await session.execute(
                            select(RenderFrameModel.frame_number)
                            .where(
                                RenderFrameModel.render_job_id == job.id,
                                RenderFrameModel.status.in_(
                                    ("pending", "failed", "rendering")
                                ),
                            )
                            .order_by(RenderFrameModel.frame_number)
                        )
                    )
                    .scalars()
                    .all()
                )
                if not remaining:
                    stage = "render.validate"
                    new_jobs.append(
                        _new_job(
                            workflow_id="blender_manager",
                            job_type="blender.render_stage",
                            payload={
                                "render_job_id": job.id,
                                "stage": stage,
                                "frames": [],
                            },
                            idempotency_key=f"render:{job.id}:{stage}:{payload.idempotency_key}",
                            priority=20,
                        )
                    )
                else:
                    await session.execute(
                        update(RenderFrameModel)
                        .where(
                            RenderFrameModel.render_job_id == job.id,
                            RenderFrameModel.frame_number.in_(remaining),
                        )
                        .values(status="pending")
                    )
                    batch = frame_batches(remaining, batch_size)[0]
                    digest = hashlib.sha256(
                        ",".join(map(str, batch)).encode()
                    ).hexdigest()[:16]
                    await session.execute(
                        update(RenderFrameModel)
                        .where(
                            RenderFrameModel.render_job_id == job.id,
                            RenderFrameModel.frame_number.in_(batch),
                        )
                        .values(batch_key=digest)
                    )
                    new_jobs.append(
                        _new_job(
                            workflow_id="blender_manager",
                            job_type="blender.render_stage",
                            payload={
                                "render_job_id": job.id,
                                "stage": stage,
                                "frames": batch,
                            },
                            idempotency_key=f"render:{job.id}:resume:{digest}:{payload.idempotency_key}",
                            priority=20,
                        )
                    )
            elif not (job.scheduler == "flamenco" and job.scheduler_job_id):
                new_jobs.append(
                    _new_job(
                        workflow_id="blender_manager",
                        job_type="blender.render_stage",
                        payload={"render_job_id": job.id, "stage": stage, "frames": []},
                        idempotency_key=f"render:{job.id}:{stage}:{payload.idempotency_key}",
                        priority=20,
                    )
                )
            if not (job.scheduler == "flamenco" and job.scheduler_job_id):
                job.status = (
                    "awaiting_kasm_render"
                    if stage == "render.observe_gui"
                    else "queued"
                )
        elif payload.action == "cancel":
            if job.status == "completed":
                raise _api_error(
                    409,
                    "RENDER_ALREADY_COMPLETED",
                    "Completed render cannot be cancelled",
                )
            if job.scheduler == "flamenco" and job.scheduler_job_id:
                values = await _provider_runtime("runpod")
                try:
                    with use_integration_configuration(values):
                        await act_on_flamenco_job(
                            job.coordinator_pod_id or job.pod_id,
                            job.scheduler_job_id,
                            "cancel",
                            reason="Cancelled by Council OS administrator",
                        )
                except RunPodError as exc:
                    raise _api_error(502, "FLAMENCO_ACTION_FAILED", str(exc)) from exc
                job.status, job.stage, job.error = "cancelling", "render.flamenco", ""
                sequence = (
                    int((job.scheduler_state or {}).get("monitor_sequence") or 0) + 1
                )
                new_jobs.append(
                    _new_job(
                        workflow_id="blender_manager",
                        job_type="blender.flamenco_monitor",
                        payload={"render_job_id": job.id, "sequence": sequence},
                        idempotency_key=f"render:{job.id}:flamenco.monitor:{sequence}:{payload.idempotency_key}",
                        priority=20,
                    )
                )
            else:
                job.status, job.stage, job.error = (
                    "cancelled",
                    "cancelled",
                    "Cancelled by administrator",
                )
                job.finished_at = utcnow()
        elif payload.action == "retry_failed_frames":
            frames = (
                (
                    await session.execute(
                        select(RenderFrameModel.frame_number)
                        .where(
                            RenderFrameModel.render_job_id == job.id,
                            RenderFrameModel.status.in_(("failed", "pending")),
                        )
                        .order_by(RenderFrameModel.frame_number)
                    )
                )
                .scalars()
                .all()
            )
            if not frames:
                raise _api_error(
                    409, "NO_FAILED_FRAMES", "No failed or missing frames need retry"
                )
            if job.scheduler == "flamenco":
                if not job.scheduler_job_id:
                    raise _api_error(
                        409,
                        "FLAMENCO_JOB_MISSING",
                        "Flamenco job has not been submitted",
                    )
                values = await _provider_runtime("runpod")
                try:
                    with use_integration_configuration(values):
                        await act_on_flamenco_job(
                            job.coordinator_pod_id or job.pod_id,
                            job.scheduler_job_id,
                            "retry",
                            reason="Retry requested by Council OS administrator",
                        )
                except RunPodError as exc:
                    raise _api_error(502, "FLAMENCO_ACTION_FAILED", str(exc)) from exc
                job.status, job.stage, job.error = "rendering", "render.flamenco", ""
                sequence = (
                    int((job.scheduler_state or {}).get("monitor_sequence") or 0) + 1
                )
                new_jobs.append(
                    _new_job(
                        workflow_id="blender_manager",
                        job_type="blender.flamenco_monitor",
                        payload={"render_job_id": job.id, "sequence": sequence},
                        idempotency_key=f"render:{job.id}:flamenco.monitor:{sequence}:{payload.idempotency_key}",
                        priority=20,
                    )
                )
            else:
                job.status, job.stage, job.error = "rendering", "render.frame_batch", ""
            await session.execute(
                update(RenderFrameModel)
                .where(
                    RenderFrameModel.render_job_id == job.id,
                    RenderFrameModel.frame_number.in_(frames),
                )
                .values(status="pending")
            )
            if job.scheduler != "flamenco":
                batch = frame_batches(frames, batch_size)[0]
                digest = hashlib.sha256(",".join(map(str, batch)).encode()).hexdigest()[
                    :16
                ]
                await session.execute(
                    update(RenderFrameModel)
                    .where(
                        RenderFrameModel.render_job_id == job.id,
                        RenderFrameModel.frame_number.in_(batch),
                    )
                    .values(batch_key=digest)
                )
                new_jobs.append(
                    _new_job(
                        workflow_id="blender_manager",
                        job_type="blender.render_stage",
                        payload={
                            "render_job_id": job.id,
                            "stage": "render.frame_batch",
                            "frames": batch,
                        },
                        idempotency_key=f"render:{job.id}:retry:{digest}:{payload.idempotency_key}",
                        priority=20,
                    )
                )
        elif payload.action == "retry_delivery":
            job.status, job.stage, job.error = "delivering", "render.deliver", ""
            new_jobs.append(
                _new_job(
                    workflow_id="blender_manager",
                    job_type="blender.render_stage",
                    payload={
                        "render_job_id": job.id,
                        "stage": "render.deliver",
                        "frames": [],
                    },
                    idempotency_key=f"render:{job.id}:render.deliver:{payload.idempotency_key}",
                    priority=20,
                    max_attempts=8,
                )
            )
        else:
            stop_requested = True

        if stop_requested:
            values = await _provider_runtime("runpod")
            try:
                with use_integration_configuration(values):
                    await stop_pod(job.pod_id)
            except RunPodError as exc:
                raise _api_error(502, "RUNPOD_ACTION_FAILED", str(exc)) from exc

        session.add_all(new_jobs)
        job.version += 1
        event = await record_audit(
            session,
            action=f"blender.render_{payload.action}",
            resource_type="render_job",
            resource_id=job.id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"status": job.status, "stage": job.stage},
        )
        response_payload = _mutation(job_resource(job), job.version, event.id)
        response_payload = await _commit_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=payload.idempotency_key,
            request_payload=request_payload,
            response_payload=response_payload,
            resource_id=job.id,
        )

    return response_payload


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
        await integration_vault.mark_verification(
            provider, verified, "" if verified else message
        )
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
        item
        for item in await integration_vault.list_connections()
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
        items = (
            (
                await session.execute(
                    select(WorkflowDefinitionModel).order_by(WorkflowDefinitionModel.id)
                )
            )
            .scalars()
            .all()
        )
    connections = {
        item["id"]: item for item in await integration_vault.list_connections()
    }
    openrouter = connections.get("openrouter", {})
    return {
        "workflows": {
            item.id: {
                "credential_status": item.credential_status,
                "configured": not _missing_config(item.id),
                "enabled": item.is_enabled,
                "paused": item.is_paused,
                "message": (item.settings or {}).get("verification_message", ""),
            }
            for item in items
        },
        "publishing": await _publishing_health(),
        "model_gateway": {
            "configured": bool(
                openrouter.get("configured")
                or os.getenv("OPENROUTER_API_KEY", "").strip()
            ),
            "status": openrouter.get(
                "status",
                "configured"
                if os.getenv("OPENROUTER_API_KEY", "").strip()
                else "missing",
            ),
        },
        "crm": {
            "hubspot": {
                "configured": bool(connections.get("hubspot", {}).get("configured")),
                "status": connections.get("hubspot", {}).get(
                    "status", "not_configured"
                ),
                "message": connections.get("hubspot", {}).get("last_error", ""),
            }
        },
    }


# Native Council Brain knowledge base and Grant exports
@app.post("/api/knowledge/documents")
@app.post("/api/knowledge/upload", deprecated=True)
async def upload_knowledge(
    request: Request,
    file: UploadFile = File(...),
    idempotency_key: str = Header(
        alias="Idempotency-Key", min_length=8, max_length=128
    ),
    actor: RequestActor = Depends(require_admin),
):
    filename = Path(file.filename or "document").name
    if Path(filename).suffix.lower() not in ALLOWED_KNOWLEDGE_EXTENSIONS:
        raise _api_error(
            415,
            "UNSUPPORTED_DOCUMENT_TYPE",
            "Only PDF, DOCX, TXT, and Markdown are accepted",
        )
    contents = await file.read(MAX_KNOWLEDGE_BYTES + 1)
    if len(contents) > MAX_KNOWLEDGE_BYTES:
        raise _api_error(
            413, "DOCUMENT_TOO_LARGE", "Knowledge documents are limited to 20 MB"
        )
    digest = hashlib.sha256(contents).hexdigest()
    scope = "knowledge:upload"
    request_payload = {
        "filename": filename,
        "sha256": digest,
        "size_bytes": len(contents),
    }
    async with async_session() as session:
        replay = await _begin_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=idempotency_key,
            request_payload=request_payload,
        )
        if replay:
            return replay
        existing = (
            await session.execute(
                select(KnowledgeDocumentModel).where(
                    KnowledgeDocumentModel.sha256 == digest
                )
            )
        ).scalar_one_or_none()
        if existing:
            raise _api_error(
                409, "DUPLICATE_DOCUMENT", "This document is already stored"
            )
        document = KnowledgeDocumentModel(
            filename=filename,
            content_type=file.content_type or "application/octet-stream",
            size_bytes=len(contents),
            sha256=digest,
            storage_key=digest,
            raw_content=contents,
            status="pending",
            metadata_json={"uploaded_by": actor.actor_id},
        )
        session.add(document)
        await session.flush()
        job = _new_job(
            workflow_id="knowledge",
            job_type="knowledge.ingest",
            payload={"document_id": document.id},
            idempotency_key=f"knowledge.ingest:{document.id}:v1",
            max_attempts=4,
        )
        session.add(job)
        await session.flush()
        document.ingestion_job_id = job.id
        document.version += 1
        event = await record_audit(
            session,
            action="knowledge.uploaded",
            resource_type="knowledge_document",
            resource_id=document.id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={
                "filename": filename,
                "size_bytes": len(contents),
                "idempotency_key": idempotency_key,
            },
        )
        await session.flush()
        response = _mutation(_document_json(document, 0), document.version, event.id)
        return await _commit_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=idempotency_key,
            request_payload=request_payload,
            response_payload=response,
            resource_id=document.id,
        )


def _document_json(
    document: KnowledgeDocumentModel, chunk_count: int
) -> dict[str, Any]:
    return {
        "id": document.id,
        "filename": document.filename,
        "doc_hash": document.sha256,
        "sha256": document.sha256,
        "status": document.status,
        "size_bytes": document.size_bytes,
        "chunk_count": int(chunk_count),
        "selected_for_grant": document.selected_for_grant,
        "warning": document.warning,
        "warnings": document.extraction_warnings or [],
        "error": document.error,
        "index_version": document.indexing_version,
        "embedding_model": document.embedding_model,
        "ingestion_job_id": document.ingestion_job_id,
        "metadata": document.metadata_json or {},
        "version": document.version,
        "created_at": iso(document.created_at),
        "updated_at": iso(document.updated_at),
    }


@app.get("/api/knowledge/documents")
async def list_knowledge(_: RequestActor = Depends(require_admin)):
    async with async_session() as session:
        items = (
            (
                await session.execute(
                    select(KnowledgeDocumentModel).order_by(
                        KnowledgeDocumentModel.created_at.desc()
                    )
                )
            )
            .scalars()
            .all()
        )
        from src.core.models import KnowledgeChunkModel

        counts = dict(
            (
                await session.execute(
                    select(
                        KnowledgeChunkModel.doc_hash, func.count(KnowledgeChunkModel.id)
                    ).group_by(KnowledgeChunkModel.doc_hash)
                )
            ).all()
        )
    documents = [
        _document_json(item, int(counts.get(item.sha256, 0))) for item in items
    ]
    return {"documents": documents, "total": len(documents)}


@app.get("/api/knowledge/documents/{document_id}")
async def get_knowledge_document(
    document_id: str, _: RequestActor = Depends(require_admin)
):
    async with async_session() as session:
        document = await session.get(KnowledgeDocumentModel, document_id)
        if not document:
            raise _api_error(
                404, "DOCUMENT_NOT_FOUND", "Knowledge document does not exist"
            )
        count = await session.scalar(
            select(func.count(KnowledgeChunkModel.id)).where(
                KnowledgeChunkModel.document_id == document_id
            )
        )
    return _document_json(document, int(count or 0))


@app.post("/api/knowledge/documents/{document_id}/reindex")
async def reindex_knowledge_document(
    document_id: str,
    body: VersionedMutationRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    from src.core.rag_engine import INDEX_VERSION

    scope = f"knowledge:reindex:{document_id}"
    request_payload = body.model_dump(mode="json")
    async with async_session() as session:
        replay = await _begin_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
        )
        if replay:
            return replay
        document = await session.get(KnowledgeDocumentModel, document_id)
        if not document:
            raise _api_error(
                404, "DOCUMENT_NOT_FOUND", "Knowledge document does not exist"
            )
        if not document.raw_content:
            raise _api_error(
                409,
                "SOURCE_CONTENT_REQUIRED",
                "This legacy source must be uploaded again before it can use the new embedding index.",
            )
        if document.version != body.expected_version:
            raise _api_error(
                409, "VERSION_CONFLICT", "Knowledge document changed; refresh and retry"
            )
        document.status, document.error = "pending", ""
        document.version += 1
        job = _new_job(
            workflow_id="knowledge",
            job_type="knowledge.ingest",
            payload={"document_id": document_id},
            idempotency_key=(
                f"knowledge.reindex:{document_id}:index-v{INDEX_VERSION}:"
                f"resource-v{document.version}"
            ),
            max_attempts=4,
        )
        session.add(job)
        await session.flush()
        document.ingestion_job_id = job.id
        event = await record_audit(
            session,
            action="knowledge.reindex_queued",
            resource_type="knowledge_document",
            resource_id=document.id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={
                "from_index_version": document.indexing_version,
                "to_index_version": INDEX_VERSION,
            },
        )
        await session.flush()
        response = _mutation(_document_json(document, 0), document.version, event.id)
        return await _commit_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
            response_payload=response,
            resource_id=document_id,
        )


@app.get("/api/knowledge/search")
async def search_knowledge(
    q: str = Query(min_length=1, max_length=1000),
    doc_hash: list[str] = Query(default=[]),
    _: RequestActor = Depends(require_admin),
):
    from src.core.rag_engine import KnowledgeRetrievalError, search_knowledge_base

    try:
        results = await search_knowledge_base(q, top_k=8, doc_hashes=doc_hash)
    except ValueError as exc:
        raise _api_error(422, "INVALID_KNOWLEDGE_SCOPE", str(exc)) from exc
    except KnowledgeRetrievalError as exc:
        raise _api_error(503, "KNOWLEDGE_RETRIEVAL_FAILED", str(exc)) from exc
    return {"results": results, "query": q, "scope": doc_hash}


@app.post("/api/knowledge/search")
async def inspect_knowledge_search(
    body: KnowledgeSearchRequest,
    _: RequestActor = Depends(require_admin),
):
    from src.core.rag_engine import KnowledgeRetrievalError, search_knowledge

    async with async_session() as session:
        documents = (
            (
                await session.execute(
                    select(KnowledgeDocumentModel).where(
                        KnowledgeDocumentModel.id.in_(body.document_ids)
                    )
                )
            )
            .scalars()
            .all()
            if body.document_ids
            else []
        )
    if len(documents) != len(set(body.document_ids)):
        raise _api_error(
            404, "DOCUMENT_NOT_FOUND", "One or more scoped documents do not exist"
        )
    try:
        return await search_knowledge(
            body.query,
            top_k=body.top_k,
            document_hashes=[document.sha256 for document in documents],
            collection_ids=body.collection_ids,
            graph_expansion=body.graph_expansion,
        )
    except ValueError as exc:
        raise _api_error(422, "INVALID_KNOWLEDGE_SCOPE", str(exc)) from exc
    except KnowledgeRetrievalError as exc:
        raise _api_error(503, "KNOWLEDGE_RETRIEVAL_FAILED", str(exc)) from exc


@app.delete("/api/knowledge/documents/{document_id}")
async def delete_knowledge(
    document_id: str,
    body: VersionedMutationRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    from src.core.rag_engine import delete_document_in_session

    scope = f"knowledge:delete:{document_id}"
    request_payload = body.model_dump(mode="json")
    async with async_session() as session:
        replay = await _begin_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
        )
        if replay:
            return replay
        document = await session.get(KnowledgeDocumentModel, document_id)
        if not document:
            raise _api_error(
                404, "DOCUMENT_NOT_FOUND", "Knowledge document does not exist"
            )
        if document.version != body.expected_version:
            raise _api_error(
                409, "VERSION_CONFLICT", "Knowledge document changed; refresh and retry"
            )
        next_version = document.version + 1
        filename = document.filename
        await delete_document_in_session(session, document.sha256)
        event = await record_audit(
            session,
            action="knowledge.deleted",
            resource_type="knowledge_document",
            resource_id=document_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"filename": filename, "idempotency_key": body.idempotency_key},
        )
        response = _mutation(
            {"id": document_id, "status": "deleted"},
            next_version,
            event.id,
        )
        return await _commit_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
            response_payload=response,
            resource_id=document_id,
        )


def _collection_json(
    collection: KnowledgeCollectionModel,
    document_ids: list[str],
    bindings: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "id": collection.id,
        "name": collection.name,
        "description": collection.description,
        "metadata": collection.metadata_json or {},
        "document_ids": document_ids,
        "document_count": len(document_ids),
        "bindings": bindings or [],
        "version": collection.version,
        "created_at": iso(collection.created_at),
        "updated_at": iso(collection.updated_at),
    }


@app.get("/api/knowledge/collections")
async def list_knowledge_collections(_: RequestActor = Depends(require_admin)):
    async with async_session() as session:
        collections = (
            (
                await session.execute(
                    select(KnowledgeCollectionModel).order_by(
                        KnowledgeCollectionModel.name
                    )
                )
            )
            .scalars()
            .all()
        )
        memberships = (
            await session.execute(
                select(
                    KnowledgeCollectionDocumentModel.collection_id,
                    KnowledgeCollectionDocumentModel.document_id,
                )
            )
        ).all()
        bindings = (
            await session.execute(
                select(
                    KnowledgeBindingModel.collection_id,
                    KnowledgeBindingModel.target_type,
                    KnowledgeBindingModel.target_id,
                )
            )
        ).all()
    grouped: dict[str, list[str]] = {}
    for collection_id, document_id in memberships:
        grouped.setdefault(collection_id, []).append(document_id)
    binding_groups: dict[str, list[dict[str, str]]] = {}
    for collection_id, target_type, target_id in bindings:
        binding_groups.setdefault(collection_id, []).append(
            {
                "target_type": target_type,
                "target_id": target_id,
            }
        )
    return {
        "collections": [
            _collection_json(
                item, grouped.get(item.id, []), binding_groups.get(item.id, [])
            )
            for item in collections
        ]
    }


@app.post("/api/knowledge/collections")
async def create_knowledge_collection(
    body: KnowledgeCollectionRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    scope = "knowledge_collection:create"
    request_payload = body.model_dump(mode="json")
    async with async_session() as session:
        replay = await _begin_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
        )
        if replay:
            return replay
        existing_count = (
            int(
                await session.scalar(
                    select(func.count(KnowledgeDocumentModel.id)).where(
                        KnowledgeDocumentModel.id.in_(body.document_ids)
                    )
                )
                or 0
            )
            if body.document_ids
            else 0
        )
        if existing_count != len(set(body.document_ids)):
            raise _api_error(
                404,
                "DOCUMENT_NOT_FOUND",
                "One or more collection documents do not exist",
            )
        collection = KnowledgeCollectionModel(
            name=body.name,
            description=body.description,
            metadata_json=body.metadata,
        )
        session.add(collection)
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            raise _api_error(
                409,
                "COLLECTION_NAME_EXISTS",
                "A collection with this name already exists",
            ) from exc
        for document_id in dict.fromkeys(body.document_ids):
            session.add(
                KnowledgeCollectionDocumentModel(
                    collection_id=collection.id,
                    document_id=document_id,
                )
            )
        event = await record_audit(
            session,
            action="knowledge.collection_created",
            resource_type="knowledge_collection",
            resource_id=collection.id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"document_count": len(set(body.document_ids))},
        )
        await session.flush()
        response = _mutation(
            _collection_json(collection, list(dict.fromkeys(body.document_ids))),
            collection.version,
            event.id,
        )
        return await _commit_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
            response_payload=response,
            resource_id=collection.id,
        )


@app.patch("/api/knowledge/collections/{collection_id}")
async def update_knowledge_collection(
    collection_id: str,
    body: KnowledgeCollectionPatch,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    scope = f"knowledge_collection:update:{collection_id}"
    request_payload = body.model_dump(mode="json")
    async with async_session() as session:
        replay = await _begin_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
        )
        if replay:
            return replay
        collection = await session.get(KnowledgeCollectionModel, collection_id)
        if not collection:
            raise _api_error(
                404, "COLLECTION_NOT_FOUND", "Knowledge collection does not exist"
            )
        if collection.version != body.expected_version:
            raise _api_error(
                409, "VERSION_CONFLICT", "Collection changed; refresh before saving"
            )
        if body.document_ids is not None:
            count = (
                int(
                    await session.scalar(
                        select(func.count(KnowledgeDocumentModel.id)).where(
                            KnowledgeDocumentModel.id.in_(body.document_ids)
                        )
                    )
                    or 0
                )
                if body.document_ids
                else 0
            )
            if count != len(set(body.document_ids)):
                raise _api_error(
                    404,
                    "DOCUMENT_NOT_FOUND",
                    "One or more collection documents do not exist",
                )
            await session.execute(
                KnowledgeCollectionDocumentModel.__table__.delete().where(
                    KnowledgeCollectionDocumentModel.collection_id == collection_id
                )
            )
            for document_id in dict.fromkeys(body.document_ids):
                session.add(
                    KnowledgeCollectionDocumentModel(
                        collection_id=collection_id, document_id=document_id
                    )
                )
        if body.name is not None:
            collection.name = body.name
        if body.description is not None:
            collection.description = body.description
        if body.metadata is not None:
            collection.metadata_json = body.metadata
        collection.version += 1
        event = await record_audit(
            session,
            action="knowledge.collection_updated",
            resource_type="knowledge_collection",
            resource_id=collection_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={},
        )
        await session.flush()
        document_ids = (
            (
                await session.execute(
                    select(KnowledgeCollectionDocumentModel.document_id).where(
                        KnowledgeCollectionDocumentModel.collection_id == collection_id
                    )
                )
            )
            .scalars()
            .all()
        )
        response = _mutation(
            _collection_json(collection, list(document_ids)),
            collection.version,
            event.id,
        )
        return await _commit_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
            response_payload=response,
            resource_id=collection.id,
        )


async def _replace_knowledge_bindings(
    target_type: str,
    target_id: str,
    body: KnowledgeBindingsRequest,
    request: Request,
    actor: RequestActor,
):
    collection_ids = body.collection_ids
    scope = f"knowledge_binding:{target_type}:{target_id}"
    request_payload = body.model_dump(mode="json")
    async with async_session() as session:
        replay = await _begin_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
        )
        if replay:
            return replay
        state = (
            await session.execute(
                select(KnowledgeBindingStateModel)
                .where(
                    KnowledgeBindingStateModel.target_type == target_type,
                    KnowledgeBindingStateModel.target_id == target_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if state is None:
            state = KnowledgeBindingStateModel(
                target_type=target_type,
                target_id=target_id,
                version=1,
            )
            session.add(state)
            await session.flush()
        if state.version != body.expected_version:
            raise _api_error(
                409,
                "VERSION_CONFLICT",
                "Knowledge bindings changed; refresh before saving",
            )
        count = (
            int(
                await session.scalar(
                    select(func.count(KnowledgeCollectionModel.id)).where(
                        KnowledgeCollectionModel.id.in_(collection_ids)
                    )
                )
                or 0
            )
            if collection_ids
            else 0
        )
        if count != len(set(collection_ids)):
            raise _api_error(
                404, "COLLECTION_NOT_FOUND", "One or more collections do not exist"
            )
        await session.execute(
            KnowledgeBindingModel.__table__.delete().where(
                KnowledgeBindingModel.target_type == target_type,
                KnowledgeBindingModel.target_id == target_id,
            )
        )
        for collection_id in dict.fromkeys(collection_ids):
            session.add(
                KnowledgeBindingModel(
                    target_type=target_type,
                    target_id=target_id,
                    collection_id=collection_id,
                )
            )
        event = await record_audit(
            session,
            action="knowledge.bindings_updated",
            resource_type=target_type,
            resource_id=target_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"collection_ids": list(dict.fromkeys(collection_ids))},
        )
        state.version += 1
        await session.flush()
        resource = {
            "target_type": target_type,
            "target_id": target_id,
            "collection_ids": list(dict.fromkeys(collection_ids)),
            "version": state.version,
        }
        response = _mutation(resource, state.version, event.id)
        return await _commit_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
            response_payload=response,
            resource_id=target_id,
        )


@app.get("/api/knowledge/bindings/{target_type}/{target_id}")
async def get_knowledge_bindings(
    target_type: str,
    target_id: str,
    _: RequestActor = Depends(require_admin),
):
    if target_type not in {"council", "workflow"}:
        raise _api_error(
            404, "BINDING_TARGET_NOT_FOUND", "Knowledge binding target does not exist"
        )
    async with async_session() as session:
        state = (
            await session.execute(
                select(KnowledgeBindingStateModel).where(
                    KnowledgeBindingStateModel.target_type == target_type,
                    KnowledgeBindingStateModel.target_id == target_id,
                )
            )
        ).scalar_one_or_none()
        collection_ids = (
            (
                await session.execute(
                    select(KnowledgeBindingModel.collection_id).where(
                        KnowledgeBindingModel.target_type == target_type,
                        KnowledgeBindingModel.target_id == target_id,
                    )
                )
            )
            .scalars()
            .all()
        )
    return {
        "target_type": target_type,
        "target_id": target_id,
        "collection_ids": list(collection_ids),
        "version": state.version if state else 1,
    }


@app.put("/api/councils/{council_id}/knowledge-bindings")
async def put_council_knowledge_bindings(
    council_id: str,
    body: KnowledgeBindingsRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    if council_id not in PRODUCTION_COUNCILS:
        raise _api_error(404, "COUNCIL_NOT_FOUND", "Council does not exist")
    return await _replace_knowledge_bindings(
        "council", council_id, body, request, actor
    )


@app.put("/api/workflows/{workflow_id}/knowledge-bindings")
async def put_workflow_knowledge_bindings(
    workflow_id: str,
    body: KnowledgeBindingsRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    async with async_session() as session:
        if not await session.get(WorkflowDefinitionModel, workflow_id):
            raise _api_error(404, "WORKFLOW_NOT_FOUND", "Workflow does not exist")
    return await _replace_knowledge_bindings(
        "workflow", workflow_id, body, request, actor
    )


@app.get("/api/brain/graph")
async def get_brain_graph(
    status: str | None = Query(default=None), _: RequestActor = Depends(require_admin)
):
    from src.core.brain import graph_snapshot

    return await graph_snapshot(status)


@app.get("/api/brain/conflicts")
async def get_brain_conflicts(_: RequestActor = Depends(require_admin)):
    async with async_session() as session:
        items = (
            (
                await session.execute(
                    select(BrainConflictModel).order_by(
                        BrainConflictModel.created_at.desc()
                    )
                )
            )
            .scalars()
            .all()
        )
    return {
        "conflicts": [
            {
                "id": item.id,
                "fact_a_id": item.fact_a_id,
                "fact_b_id": item.fact_b_id,
                "reason": item.reason,
                "severity": item.severity,
                "status": item.status,
                "resolution": item.resolution,
                "version": item.version,
                "created_at": iso(item.created_at),
            }
            for item in items
        ]
    }


@app.get("/api/brain/gaps")
async def get_brain_gaps(_: RequestActor = Depends(require_admin)):
    async with async_session() as session:
        items = (
            (
                await session.execute(
                    select(BrainGapModel).order_by(BrainGapModel.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
    return {
        "gaps": [
            {
                "id": item.id,
                "question": item.question,
                "context": item.context,
                "status": item.status,
                "version": item.version,
                "created_at": iso(item.created_at),
            }
            for item in items
        ]
    }


@app.post("/api/brain/review-actions")
async def brain_review_action(
    body: BrainReviewActionRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    scope = f"brain_review:{body.resource_type}:{body.resource_id}"
    request_payload = body.model_dump(mode="json")
    model_map = {
        "entity": BrainEntityModel,
        "fact": BrainFactModel,
        "relationship": BrainRelationshipModel,
        "conflict": BrainConflictModel,
        "gap": BrainGapModel,
    }
    replacement_id: str | None = None
    async with async_session() as session:
        replay = await _begin_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
        )
        if replay:
            return replay
        resource = await session.get(model_map[body.resource_type], body.resource_id)
        if not resource:
            raise _api_error(
                404, "BRAIN_RESOURCE_NOT_FOUND", "Brain review resource does not exist"
            )
        if resource.version != body.expected_version:
            raise _api_error(
                409, "VERSION_CONFLICT", "Resource changed; refresh before reviewing"
            )
        if body.action in {"verify", "reject"}:
            if body.resource_type not in {"entity", "fact", "relationship"}:
                raise _api_error(
                    409,
                    "INVALID_REVIEW_ACTION",
                    "This action is not valid for the resource",
                )
            resource.status = "verified" if body.action == "verify" else "rejected"
            if (
                body.resource_type == "fact"
                and body.action == "verify"
                and not (resource.source_document_id or resource.approval_id)
            ):
                raise _api_error(
                    409,
                    "PROVENANCE_REQUIRED",
                    "A fact cannot be verified without provenance",
                )
        elif body.action in {"resolve", "reopen"}:
            if body.resource_type not in {"conflict", "gap"}:
                raise _api_error(
                    409,
                    "INVALID_REVIEW_ACTION",
                    "This action is not valid for the resource",
                )
            resource.status = "resolved" if body.action == "resolve" else "open"
            if isinstance(resource, BrainConflictModel):
                resource.resolution = body.notes
        elif body.action == "supersede":
            if not isinstance(resource, BrainFactModel) or not body.replacement_value:
                raise _api_error(
                    409,
                    "REPLACEMENT_REQUIRED",
                    "Superseding a fact requires a replacement value",
                )
            replacement = BrainFactModel(
                subject_entity_id=resource.subject_entity_id,
                predicate=resource.predicate,
                value_text=body.replacement_value,
                normalized_value=re.sub(
                    r"\s+", " ", body.replacement_value.lower()
                ).strip(),
                status="proposed",
                confidence=1.0,
                supersedes_fact_id=resource.id,
                source_document_id=resource.source_document_id,
                source_chunk_id=resource.source_chunk_id,
                council_run_id=resource.council_run_id,
                approval_id=resource.approval_id,
                citation_text="",
                review_reason="Administrator-proposed correction requires verification.",
            )
            resource.effective_to = utcnow()
            resource.status = "superseded"
            session.add(replacement)
            await session.flush()
            replacement_id = replacement.id
        resource.version += 1
        # Cached graph candidates must never outlive a review decision.
        await session.execute(delete(RetrievalCacheModel))
        event = await record_audit(
            session,
            action=f"brain.{body.action}",
            resource_type=body.resource_type,
            resource_id=body.resource_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"notes": body.notes, "idempotency_key": body.idempotency_key},
        )
        await session.flush()
        response = _mutation(
            {
                "id": body.resource_id,
                "status": resource.status,
                "version": resource.version,
                "replacement_fact_id": replacement_id,
            },
            resource.version,
            event.id,
        )
        return await _commit_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
            response_payload=response,
            resource_id=body.resource_id,
        )


@app.get("/api/skills")
async def list_skills(_: RequestActor = Depends(require_admin)):
    async with async_session() as session:
        items = (
            (await session.execute(select(SkillModel).order_by(SkillModel.name)))
            .scalars()
            .all()
        )
    return {
        "skills": [
            {
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "scope_type": item.scope_type,
                "scope_id": item.scope_id,
                "tags": item.tags or [],
                "active_revision_id": item.active_revision_id,
                "version": item.version,
                "created_at": iso(item.created_at),
                "updated_at": iso(item.updated_at),
            }
            for item in items
        ]
    }


@app.post("/api/skills")
async def create_skill(
    body: SkillRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    from src.core.rag_engine import get_embedding

    scope = f"skill_create:{body.scope_type}:{body.scope_id}"
    request_payload = body.model_dump(mode="json")
    async with async_session() as session:
        replay = await _begin_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
        )
        if replay:
            return replay
        skill = SkillModel(
            name=body.name,
            description=body.description,
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            tags=list(dict.fromkeys(body.tags)),
        )
        session.add(skill)
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            raise _api_error(
                409, "SKILL_EXISTS", "A skill with this name and scope already exists"
            ) from exc
        revision = SkillRevisionModel(
            skill_id=skill.id,
            revision_number=1,
            instructions=body.instructions,
            token_count=max(1, (len(body.instructions) + 3) // 4),
            vector=await get_embedding(body.instructions),
            evidence={
                "created_by_admin": True,
                "idempotency_key": body.idempotency_key,
            },
            created_by=actor.actor_id,
        )
        session.add(revision)
        await session.flush()
        skill.active_revision_id = revision.id
        event = await record_audit(
            session,
            action="skill.created",
            resource_type="skill",
            resource_id=skill.id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"revision_id": revision.id},
        )
        await session.flush()
        response = _mutation(
            {
                "id": skill.id,
                "name": skill.name,
                "active_revision_id": revision.id,
                "version": skill.version,
            },
            skill.version,
            event.id,
        )
        return await _commit_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
            response_payload=response,
            resource_id=skill.id,
        )


@app.get("/api/skills/{skill_id}/revisions")
async def list_skill_revisions(skill_id: str, _: RequestActor = Depends(require_admin)):
    async with async_session() as session:
        if not await session.get(SkillModel, skill_id):
            raise _api_error(404, "SKILL_NOT_FOUND", "Skill does not exist")
        items = (
            (
                await session.execute(
                    select(SkillRevisionModel)
                    .where(SkillRevisionModel.skill_id == skill_id)
                    .order_by(SkillRevisionModel.revision_number.desc())
                )
            )
            .scalars()
            .all()
        )
    return {
        "revisions": [
            {
                "id": item.id,
                "revision_number": item.revision_number,
                "instructions": item.instructions,
                "token_count": item.token_count,
                "evidence": item.evidence or {},
                "created_by": item.created_by,
                "created_at": iso(item.created_at),
            }
            for item in items
        ]
    }


@app.post("/api/skills/{skill_id}/revisions/{revision_id}/activate")
async def activate_skill_revision(
    skill_id: str,
    revision_id: str,
    body: SkillRevisionActionRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    """Rollback by moving only the active pointer; revisions remain immutable."""
    scope = f"skill_activate:{skill_id}"
    request_payload = body.model_dump(mode="json") | {"revision_id": revision_id}
    async with async_session() as session:
        replay = await _begin_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
        )
        if replay:
            return replay
        skill = await session.get(SkillModel, skill_id)
        revision = await session.get(SkillRevisionModel, revision_id)
        if not skill or not revision or revision.skill_id != skill_id:
            raise _api_error(
                404, "SKILL_REVISION_NOT_FOUND", "Skill revision does not exist"
            )
        if skill.version != body.expected_version:
            raise _api_error(
                409,
                "VERSION_CONFLICT",
                "Skill changed; refresh before activating a revision",
            )
        skill.active_revision_id, skill.version = revision.id, skill.version + 1
        event = await record_audit(
            session,
            action="skill.revision_activated",
            resource_type="skill",
            resource_id=skill.id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={
                "revision_id": revision.id,
                "revision_number": revision.revision_number,
                "idempotency_key": body.idempotency_key,
            },
        )
        await session.flush()
        response = _mutation(
            {
                "id": skill.id,
                "active_revision_id": revision.id,
                "revision_number": revision.revision_number,
                "version": skill.version,
            },
            skill.version,
            event.id,
        )
        return await _commit_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
            response_payload=response,
            resource_id=skill.id,
        )


@app.get("/api/learning-suggestions")
async def list_learning_suggestions(_: RequestActor = Depends(require_admin)):
    async with async_session() as session:
        items = (
            (
                await session.execute(
                    select(LearningSuggestionModel).order_by(
                        LearningSuggestionModel.created_at.desc()
                    )
                )
            )
            .scalars()
            .all()
        )
    return {
        "suggestions": [
            {
                "id": item.id,
                "source_task_id": item.source_task_id,
                "skill_id": item.skill_id,
                "scope_type": item.scope_type,
                "scope_id": item.scope_id,
                "title": item.title,
                "rationale": item.rationale,
                "proposed_instructions": item.proposed_instructions,
                "diff": item.diff_text,
                "evidence": item.evidence or {},
                "status": item.status,
                "version": item.version,
                "created_at": iso(item.created_at),
            }
            for item in items
        ]
    }


@app.post("/api/learning-suggestions/{suggestion_id}/actions")
async def act_on_learning_suggestion(
    suggestion_id: str,
    body: LearningActionRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    from src.core.brain import activate_learning_suggestion_in_session

    scope = f"learning_action:{suggestion_id}"
    request_payload = body.model_dump(mode="json")
    async with async_session() as session:
        replay = await _begin_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
        )
        if replay:
            return replay
        if body.action == "approve":
            try:
                resource = await activate_learning_suggestion_in_session(
                    session,
                    suggestion_id,
                    body.expected_version,
                )
            except KeyError as exc:
                raise _api_error(
                    404,
                    "LEARNING_SUGGESTION_NOT_FOUND",
                    "Learning suggestion does not exist",
                ) from exc
            except RuntimeError as exc:
                if str(exc) == "VERSION_CONFLICT":
                    raise _api_error(
                        409,
                        "VERSION_CONFLICT",
                        "Suggestion changed; refresh before reviewing",
                    ) from exc
                raise
            except ValueError as exc:
                raise _api_error(409, "INVALID_LEARNING_ACTION", str(exc)) from exc
        else:
            suggestion = await session.get(LearningSuggestionModel, suggestion_id)
            if not suggestion:
                raise _api_error(
                    404,
                    "LEARNING_SUGGESTION_NOT_FOUND",
                    "Learning suggestion does not exist",
                )
            if suggestion.version != body.expected_version:
                raise _api_error(
                    409,
                    "VERSION_CONFLICT",
                    "Suggestion changed; refresh before reviewing",
                )
            suggestion.status, suggestion.version = "rejected", suggestion.version + 1
            resource = {"suggestion_id": suggestion.id, "status": suggestion.status}
        event = await record_audit(
            session,
            action=f"learning_suggestion.{body.action}",
            resource_type="learning_suggestion",
            resource_id=suggestion_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"notes": body.notes, "idempotency_key": body.idempotency_key},
        )
        await session.flush()
        response = _mutation(resource, body.expected_version + 1, event.id)
        return await _commit_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
            response_payload=response,
            resource_id=suggestion_id,
        )


@app.post("/api/knowledge/import/markdown")
async def import_markdown_bundle(
    body: MarkdownImportRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    """User-triggered Obsidian-compatible import; no filesystem watcher exists."""
    scope = "knowledge:markdown_import"
    request_payload = body.model_dump(mode="json")
    created: list[KnowledgeDocumentModel] = []
    imported: list[KnowledgeDocumentModel] = []
    async with async_session() as session:
        replay = await _begin_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
        )
        if replay:
            return replay
        collection = (
            await session.execute(
                select(KnowledgeCollectionModel).where(
                    KnowledgeCollectionModel.name == body.collection_name
                )
            )
        ).scalar_one_or_none()
        if collection is None:
            collection = KnowledgeCollectionModel(
                name=body.collection_name,
                description="User-triggered Markdown/Obsidian import.",
                metadata_json={"source": "markdown_import"},
            )
            session.add(collection)
            await session.flush()
        for item in body.documents:
            filename = Path(item.get("path") or item.get("filename") or "note.md").name
            if not filename.lower().endswith(".md"):
                filename += ".md"
            content = str(item.get("content") or "").encode()
            if not content:
                continue
            digest = hashlib.sha256(content).hexdigest()
            existing = (
                await session.execute(
                    select(KnowledgeDocumentModel).where(
                        KnowledgeDocumentModel.sha256 == digest
                    )
                )
            ).scalar_one_or_none()
            document = existing or KnowledgeDocumentModel(
                filename=filename,
                content_type="text/markdown",
                size_bytes=len(content),
                sha256=digest,
                storage_key=digest,
                raw_content=content,
                status="pending",
                metadata_json={
                    "source": "markdown_import",
                    "original_path": item.get("path", filename),
                },
            )
            if not existing:
                session.add(document)
                await session.flush()
                created.append(document)
            imported.append(document)
            if (
                document.status in {"pending", "failed"}
                and not document.ingestion_job_id
            ):
                job = _new_job(
                    workflow_id="knowledge",
                    job_type="knowledge.ingest",
                    payload={"document_id": document.id},
                    idempotency_key=f"knowledge.ingest:{document.id}:v1",
                    max_attempts=4,
                )
                session.add(job)
                await session.flush()
                document.ingestion_job_id = job.id
                document.version += 1
            membership = await session.scalar(
                select(func.count(KnowledgeCollectionDocumentModel.id)).where(
                    KnowledgeCollectionDocumentModel.collection_id == collection.id,
                    KnowledgeCollectionDocumentModel.document_id == document.id,
                )
            )
            if not membership:
                session.add(
                    KnowledgeCollectionDocumentModel(
                        collection_id=collection.id,
                        document_id=document.id,
                    )
                )
        event = await record_audit(
            session,
            action="knowledge.markdown_imported",
            resource_type="knowledge_collection",
            resource_id=collection.id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={"created_documents": len(created)},
        )
        await session.flush()
        resource = {
            "collection_id": collection.id,
            "document_ids": [item.id for item in imported],
            "created_document_ids": [item.id for item in created],
            "status": "pending",
        }
        response = _mutation(resource, collection.version, event.id)
        return await _commit_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
            response_payload=response,
            resource_id=collection.id,
        )


@app.get("/api/knowledge/export/markdown.zip")
async def export_markdown_bundle(_: RequestActor = Depends(require_admin)):
    async with async_session() as session:
        documents = (
            (
                await session.execute(
                    select(KnowledgeDocumentModel)
                    .where(KnowledgeDocumentModel.status == "ready")
                    .order_by(KnowledgeDocumentModel.filename)
                )
            )
            .scalars()
            .all()
        )
    output = io.BytesIO()
    manifest: list[dict[str, Any]] = []
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        used_names: set[str] = set()
        for document in documents:
            stem = (
                re.sub(r"[^A-Za-z0-9._-]+", "_", Path(document.filename).stem)[:120]
                or document.id
            )
            name = f"{stem}.md"
            if name in used_names:
                name = f"{stem}-{document.id[:8]}.md"
            used_names.add(name)
            frontmatter = (
                "---\n"
                f"council_os_id: {document.id}\n"
                f"sha256: {document.sha256}\n"
                f"index_version: {document.indexing_version}\n"
                "---\n\n"
            )
            archive.writestr(name, frontmatter + document.normalized_text)
            manifest.append(
                {"id": document.id, "filename": name, "sha256": document.sha256}
            )
        archive.writestr(
            "council-os-manifest.json", json.dumps({"documents": manifest}, indent=2)
        )
    return Response(
        content=output.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="council-os-knowledge.zip"'
        },
    )


@app.post("/api/mcp/tokens")
async def create_mcp_token(
    body: MCPTokenRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    scope = "mcp_token:create"
    request_payload = body.model_dump(mode="json")
    secret = (
        os.getenv("SESSION_SECRET", "").strip()
        or os.getenv("INTERNAL_SERVICE_TOKEN", "").strip()
        or os.getenv("INTEGRATION_ENCRYPTION_KEY", "").strip()
    )
    if len(secret) < 32:
        raise _api_error(
            503,
            "MCP_TOKEN_KEY_UNAVAILABLE",
            "A rotated server secret is required for MCP token creation",
        )
    token_bytes = hmac.new(
        secret.encode(),
        f"mcp-token:{body.idempotency_key}".encode(),
        hashlib.sha256,
    ).digest()
    raw_token = "cos_mcp_" + base64.urlsafe_b64encode(token_bytes).decode().rstrip("=")
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    async with async_session() as session:
        replay = await _begin_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
        )
        if replay:
            replay_resource = dict(replay.get("resource") or {})
            replay_resource["token"] = raw_token
            replay["resource"] = replay_resource
            return replay
        token = MCPTokenModel(
            name=body.name,
            token_hash=token_hash,
            prefix=raw_token[:12],
            scopes=list(dict.fromkeys(body.scopes)),
            expires_at=utcnow() + timedelta(days=body.expires_in_days),
        )
        session.add(token)
        await session.flush()
        event = await record_audit(
            session,
            action="mcp.token_created",
            resource_type="mcp_token",
            resource_id=token.id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={
                "name": body.name,
                "scopes": token.scopes,
                "expires_at": iso(token.expires_at),
            },
        )
        await session.flush()
        # The raw token is reconstructable from the idempotency key but is
        # never persisted in either the token row or replay record.
        persisted_response = _mutation(
            {
                "id": token.id,
                "name": token.name,
                "prefix": token.prefix,
                "scopes": token.scopes,
                "expires_at": iso(token.expires_at),
                "version": token.version,
            },
            token.version,
            event.id,
        )
        committed = await _commit_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
            response_payload=persisted_response,
            resource_id=token.id,
        )
        resource = dict(committed.get("resource") or {})
        resource["token"] = raw_token
        return {**committed, "resource": resource}


@app.delete("/api/mcp/tokens/{token_id}")
async def revoke_mcp_token(
    token_id: str,
    body: MCPTokenRevokeRequest,
    request: Request,
    actor: RequestActor = Depends(require_admin),
):
    scope = f"mcp_token:revoke:{token_id}"
    request_payload = body.model_dump(mode="json")
    async with async_session() as session:
        replay = await _begin_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
        )
        if replay:
            return replay
        token = await session.get(MCPTokenModel, token_id)
        if not token:
            raise _api_error(404, "MCP_TOKEN_NOT_FOUND", "MCP token does not exist")
        if token.version != body.expected_version:
            raise _api_error(
                409, "VERSION_CONFLICT", "MCP token changed; refresh and retry"
            )
        if token.revoked_at is not None:
            raise _api_error(
                409, "MCP_TOKEN_ALREADY_REVOKED", "MCP token is already revoked"
            )
        token.revoked_at, token.version = utcnow(), token.version + 1
        event = await record_audit(
            session,
            action="mcp.token_revoked",
            resource_type="mcp_token",
            resource_id=token_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            request_id=getattr(request.state, "request_id", ""),
            details={},
        )
        await session.flush()
        response = _mutation(
            {"id": token_id, "status": "revoked"},
            token.version,
            event.id,
        )
        return await _commit_idempotent_mutation(
            session,
            scope=scope,
            idempotency_key=body.idempotency_key,
            request_payload=request_payload,
            response_payload=response,
            resource_id=token_id,
        )


async def _authenticate_mcp(request: Request) -> MCPTokenModel:
    if request.query_params.get("token") or request.query_params.get("mcp_token"):
        raise _api_error(
            401,
            "QUERY_TOKEN_REJECTED",
            "MCP tokens are accepted only in the Authorization header",
        )
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise _api_error(401, "MCP_AUTH_REQUIRED", "Bearer token is required")
    supplied = authorization.removeprefix("Bearer ").strip()
    digest = hashlib.sha256(supplied.encode()).hexdigest()
    async with async_session() as session:
        token = (
            await session.execute(
                select(MCPTokenModel).where(
                    MCPTokenModel.token_hash == digest,
                    MCPTokenModel.revoked_at.is_(None),
                    MCPTokenModel.expires_at > utcnow(),
                )
            )
        ).scalar_one_or_none()
        if not token:
            raise _api_error(
                401, "MCP_TOKEN_INVALID", "MCP token is invalid, expired, or revoked"
            )
        since = utcnow() - timedelta(minutes=1)
        recent = int(
            await session.scalar(
                select(func.count(MCPCallModel.id)).where(
                    MCPCallModel.token_id == token.id,
                    MCPCallModel.created_at >= since,
                )
            )
            or 0
        )
        if recent >= 60:
            raise _api_error(
                429, "MCP_RATE_LIMITED", "MCP token exceeded 60 calls per minute"
            )
        token.last_used_at = utcnow()
        await session.commit()
        return token


def _mcp_result(request_id: Any, value: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


@app.post("/mcp")
async def streamable_http_mcp(request: Request):
    """Scoped MCP Streamable HTTP JSON-RPC endpoint (read/propose only)."""
    token = await _authenticate_mcp(request)
    try:
        payload = await request.json()
    except ValueError as exc:
        raise _api_error(
            400, "MCP_INVALID_JSON", "MCP request is not valid JSON"
        ) from exc
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        raise _api_error(400, "MCP_INVALID_REQUEST", "MCP request must be JSON-RPC 2.0")
    method, request_id = str(payload.get("method") or ""), payload.get("id")
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    success, detail = True, {}
    try:
        if method == "initialize":
            value = {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "Council OS Brain", "version": "1.0.0"},
            }
        elif method == "tools/list":
            value = {
                "tools": [
                    {
                        "name": "search_brain",
                        "description": "Search verified knowledge with citations.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                        },
                    },
                    {
                        "name": "inspect_entities",
                        "description": "Inspect persisted brain entities and relationships.",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                    {
                        "name": "inspect_citations",
                        "description": "Inspect a knowledge document and ingestion status.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"document_id": {"type": "string"}},
                            "required": ["document_id"],
                        },
                    },
                    {
                        "name": "propose_council_run",
                        "description": "Queue a council proposal for normal human approval.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "council": {"enum": ["grant", "sales", "content"]},
                                "task_description": {"type": "string"},
                            },
                            "required": ["council", "task_description"],
                        },
                    },
                    {
                        "name": "read_task_status",
                        "description": "Read one task status.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"task_id": {"type": "string"}},
                            "required": ["task_id"],
                        },
                    },
                ]
            }
        elif method == "tools/call":
            tool_name = str(params.get("name") or "")
            arguments = (
                params.get("arguments")
                if isinstance(params.get("arguments"), dict)
                else {}
            )
            if (
                tool_name in {"search_brain", "inspect_entities", "inspect_citations"}
                and "brain:read" not in token.scopes
            ):
                raise _api_error(
                    403, "MCP_SCOPE_DENIED", "Token lacks brain:read scope"
                )
            if (
                tool_name == "propose_council_run"
                and "council:propose" not in token.scopes
            ):
                raise _api_error(
                    403, "MCP_SCOPE_DENIED", "Token lacks council:propose scope"
                )
            if tool_name == "read_task_status" and "task:read" not in token.scopes:
                raise _api_error(403, "MCP_SCOPE_DENIED", "Token lacks task:read scope")
            if tool_name == "search_brain":
                from src.core.rag_engine import search_knowledge

                tool_value = await search_knowledge(
                    str(arguments.get("query") or ""),
                    top_k=min(10, int(arguments.get("top_k") or 5)),
                )
            elif tool_name == "inspect_entities":
                from src.core.brain import graph_snapshot

                tool_value = await graph_snapshot("verified")
            elif tool_name == "inspect_citations":
                async with async_session() as session:
                    document = await session.get(
                        KnowledgeDocumentModel, str(arguments.get("document_id") or "")
                    )
                    if not document:
                        raise _api_error(
                            404,
                            "DOCUMENT_NOT_FOUND",
                            "Knowledge document does not exist",
                        )
                    count = int(
                        await session.scalar(
                            select(func.count(KnowledgeChunkModel.id)).where(
                                KnowledgeChunkModel.document_id == document.id
                            )
                        )
                        or 0
                    )
                    tool_value = _document_json(document, count)
            elif tool_name == "read_task_status":
                async with async_session() as session:
                    task = await session.get(
                        TaskModel, str(arguments.get("task_id") or "")
                    )
                    if not task:
                        raise _api_error(404, "TASK_NOT_FOUND", "Task does not exist")
                    tool_value = {
                        "task_id": task.task_id,
                        "council": task.council,
                        "status": task.status,
                        "version": task.version,
                        "updated_at": iso(task.updated_at),
                    }
            elif tool_name == "propose_council_run":
                council = str(arguments.get("council") or "")
                description = str(arguments.get("task_description") or "")
                if council not in PRODUCTION_COUNCILS or len(description) < 3:
                    raise _api_error(
                        422,
                        "INVALID_COUNCIL_PROPOSAL",
                        "Council and task description are required",
                    )
                proposal_digest = hashlib.sha256(
                    json.dumps(
                        {
                            "token_id": token.id,
                            "request_id": request_id,
                            "council": council,
                            "task_description": description,
                        },
                        sort_keys=True,
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest()
                task_id = f"task-mcp-{proposal_digest[:20]}"
                run_id = str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"council-os:mcp:{proposal_digest}")
                )
                async with async_session() as session:
                    bind = session.get_bind()
                    if bind is not None and bind.dialect.name == "postgresql":
                        await session.execute(
                            text(
                                "SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"
                            ),
                            {"key": f"mcp:council:{proposal_digest}"},
                        )
                    task = await session.get(TaskModel, task_id)
                    if task is None:
                        task = TaskModel(
                            task_id=task_id,
                            council=council,
                            status="queued",
                            task_description=description,
                            context={"source": "mcp", "mcp_token_id": token.id},
                        )
                        run = CouncilRunModel(
                            id=run_id,
                            task_id=task_id,
                            council=council,
                            status="queued",
                            priority="normal",
                            prompt=description,
                            context={"source": "mcp"},
                        )
                        approval = ApprovalModel(
                            resource_type="task",
                            resource_id=task_id,
                            status="awaiting_approval",
                            version=1,
                        )
                        job = _new_job(
                            workflow_id=f"council.{council}",
                            job_type="council.run",
                            payload={
                                "task_id": task_id,
                                "run_id": run_id,
                                "council": council,
                                "task_description": description,
                                "context": {"source": "mcp"},
                                "priority": "normal",
                            },
                            idempotency_key=f"mcp:council:{proposal_digest}",
                        )
                        session.add(task)
                        await session.flush()
                        session.add_all([run, approval, job])
                        await session.commit()
                    else:
                        job = (
                            await session.execute(
                                select(WorkflowRunModel).where(
                                    WorkflowRunModel.idempotency_key
                                    == f"mcp:council:{proposal_digest}"
                                )
                            )
                        ).scalar_one()
                tool_value = {
                    "task_id": task_id,
                    "run_id": run_id,
                    "job_id": job.id,
                    "status": "queued",
                }
            else:
                raise _api_error(
                    404, "MCP_TOOL_NOT_FOUND", "Requested MCP tool does not exist"
                )
            value = {
                "content": [
                    {"type": "text", "text": json.dumps(tool_value, ensure_ascii=False)}
                ],
                "structuredContent": tool_value,
            }
        else:
            raise _api_error(
                404, "MCP_METHOD_NOT_FOUND", "Requested MCP method does not exist"
            )
        return JSONResponse(
            _mcp_result(request_id, value), media_type="application/json"
        )
    except Exception as exc:
        success, detail = False, {"error": str(exc)[:1000]}
        raise
    finally:
        async with async_session() as session:
            session.add(
                MCPCallModel(
                    token_id=token.id, method=method, success=success, details=detail
                )
            )
            await record_audit(
                session,
                action="mcp.call",
                resource_type="mcp_token",
                resource_id=token.id,
                actor_type="mcp",
                actor_id=token.prefix,
                details={"method": method, "success": success, **detail},
            )
            await session.commit()


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
    return Response(
        content=build_task_docx(data),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{build_task_docx_filename(data)}"'
        },
    )


@app.get("/api/grants/{task_id}/export.pdf")
async def export_grant_pdf(task_id: str, _: RequestActor = Depends(require_admin)):
    from src.integrations.docx_export import build_task_pdf, build_task_pdf_filename

    data = (await _grant_task(task_id)).to_dict()
    return Response(
        content=build_task_pdf(data),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{build_task_pdf_filename(data)}"'
        },
    )


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
    if (
        mode != "subscribe"
        or not expected
        or not hmac.compare_digest(expected, verify_token)
    ):
        raise _api_error(
            403, "WEBHOOK_VERIFICATION_FAILED", "Meta webhook verification failed"
        )
    return Response(content=challenge, media_type="text/plain")


def _instagram_webhook_comments(payload: Any) -> list[dict[str, str]]:
    comments: list[dict[str, str]] = []
    if not isinstance(payload, dict) or payload.get("object") not in {
        "instagram",
        "page",
    }:
        return comments
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict) or change.get("field") not in {
                "comments",
                "live_comments",
            }:
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
                comments.append(
                    {
                        "comment_id": comment_id,
                        "comment_text": comment_text,
                        "username": str(
                            item.get("username")
                            or author.get("username")
                            or "instagram_user"
                        ),
                        "media_id": str(item.get("media_id") or media.get("id") or ""),
                        "caption": "",
                        "timestamp": str(item.get("timestamp") or ""),
                    }
                )
    return comments[:100]


@app.post("/api/webhooks/{provider}")
async def receive_webhook(
    provider: str,
    request: Request,
    telegram_secret: str | None = Header(
        default=None, alias="X-Telegram-Bot-Api-Secret-Token"
    ),
    signature: str | None = Header(default=None, alias="X-Hub-Signature-256"),
):
    provider, body = provider.lower(), await request.body()
    if len(body) > 2 * 1024 * 1024:
        raise _api_error(413, "WEBHOOK_TOO_LARGE", "Webhook payload is too large")
    if provider == "telegram":
        values = await _webhook_values("telegram")
        expected = values.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
        valid = bool(
            expected
            and telegram_secret
            and hmac.compare_digest(expected, telegram_secret)
        )
    elif provider == "meta":
        values = await _webhook_values("meta")
        secret = values.get("META_APP_SECRET", "").encode()
        expected = (
            "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
            if secret
            else ""
        )
        valid = bool(
            expected and signature and hmac.compare_digest(expected, signature)
        )
    elif provider == "youtube":
        expected, supplied = (
            os.getenv("YOUTUBE_WEBHOOK_SECRET", "").strip(),
            request.headers.get("X-Webhook-Secret", ""),
        )
        valid = bool(expected and supplied and hmac.compare_digest(expected, supplied))
    else:
        raise _api_error(404, "WEBHOOK_NOT_FOUND", "Webhook provider is unsupported")
    if not valid:
        raise _api_error(
            401, "INVALID_WEBHOOK_SIGNATURE", "Webhook signature is invalid"
        )
    event_id = (
        request.headers.get("X-Event-ID", "")[:128] or hashlib.sha256(body).hexdigest()
    )
    if provider == "meta":
        try:
            parsed = await request.json()
        except ValueError as exc:
            raise _api_error(
                422, "INVALID_WEBHOOK_PAYLOAD", "Meta webhook body is not valid JSON"
            ) from exc
        comments = _instagram_webhook_comments(parsed)
        if not comments:
            return {
                "accepted": True,
                "ignored": True,
                "reason": "no_supported_comment_events",
            }
        job = await job_service.enqueue(
            workflow_id="instagram_comments",
            job_type="workflow.instagram_comments",
            payload={"webhook_comments": comments},
            idempotency_key=f"webhook:{provider}:{event_id}",
            priority=8,
        )
    else:
        job = await job_service.enqueue(
            workflow_id=f"webhook-{provider}",
            job_type=f"webhook.{provider}",
            payload={"body_sha256": hashlib.sha256(body).hexdigest()},
            idempotency_key=f"webhook:{provider}:{event_id}",
        )
    return {"accepted": True, "job_id": job.id}
