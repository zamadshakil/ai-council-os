from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet

from src.api import server
from src.core import database as db, integration_vault
from src.core.models import ApprovalModel, TaskModel, WorkflowDefinitionModel


ADMIN_PASSWORD = "correct-horse-battery-staple"
APP_ORIGIN = "http://localhost:3000"
SERVICE_TOKEN = "test-service-token-that-is-longer-than-thirty-two-characters"


@pytest_asyncio.fixture
async def api_client(session_factory, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("APP_ORIGIN", APP_ORIGIN)
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", SERVICE_TOKEN)
    monkeypatch.setenv(
        "INTEGRATION_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii")
    )

    # server.py imports the factory directly while services resolve it from
    # database.py, so both references must point at the isolated schema.
    monkeypatch.setattr(db, "async_session", session_factory)
    monkeypatch.setattr(server, "async_session", session_factory)
    monkeypatch.setattr(server.auth_service, "_session_factory", session_factory)
    monkeypatch.setattr(server.approval_service, "_session_factory", session_factory)
    monkeypatch.setattr(server.job_service, "_session_factory", session_factory)
    monkeypatch.setattr(integration_vault, "async_session", session_factory)

    await server.auth_service.ensure_admin("admin", ADMIN_PASSWORD)
    async with session_factory() as session:
        session.add_all(
            [
                WorkflowDefinitionModel(
                    id="reddit-prospector",
                    display_name="Reddit Lead Prospector",
                    is_enabled=True,
                    credential_status="verified",
                ),
                WorkflowDefinitionModel(
                    id="instagram_comments",
                    display_name="Instagram Comment Replies",
                    is_enabled=False,
                    credential_status="untested",
                    schedule={"type": "interval", "seconds": 300},
                ),
                TaskModel(
                    task_id="service-approval-task",
                    council="sales",
                    status="awaiting_approval",
                    task_description="Review this staged reply",
                ),
                ApprovalModel(
                    id="service-approval",
                    resource_type="task",
                    resource_id="service-approval-task",
                    status="awaiting_approval",
                    version=1,
                ),
            ]
        )
        await session.commit()

    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def _login(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
        headers={"Origin": APP_ORIGIN},
    )
    assert response.status_code == 200, response.text
    assert server.SESSION_COOKIE_NAME in response.cookies
    assert server.CSRF_COOKIE_NAME in response.cookies
    return response.json()["csrf_token"]


def _telegram_headers() -> dict[str, str]:
    return {"X-Service-Token": SERVICE_TOKEN, "X-Service-Actor": "telegram"}


@pytest.mark.asyncio
async def test_cookie_login_session_and_logout(api_client):
    csrf_token = await _login(api_client)

    session = await api_client.get("/api/auth/session")
    assert session.status_code == 200
    assert session.json()["authenticated"] is True
    assert session.json()["user"]["username"] == "admin"

    logout = await api_client.post(
        "/api/auth/logout",
        headers={"Origin": APP_ORIGIN, "X-CSRF-Token": csrf_token},
    )
    assert logout.status_code == 200
    assert logout.json()["status"] == "logged_out"

    after_logout = await api_client.get("/api/auth/session")
    assert after_logout.status_code == 401
    assert after_logout.json()["error"]["code"] == "INVALID_SESSION"


@pytest.mark.asyncio
async def test_local_loopback_alias_is_allowed_but_foreign_origin_is_rejected(api_client):
    login = await api_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
        headers={"Origin": "http://127.0.0.1:3000"},
    )
    assert login.status_code == 200, login.text
    csrf = login.json()["csrf_token"]

    rejected = await api_client.put(
        "/api/kill-switch",
        json={"active": False, "reason": "foreign origin"},
        headers={"Origin": "https://attacker.example", "X-CSRF-Token": csrf},
    )
    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "ORIGIN_REJECTED"

    logout = await api_client.post(
        "/api/auth/logout",
        headers={"Origin": "http://127.0.0.1:3000", "X-CSRF-Token": csrf},
    )
    assert logout.status_code == 200, logout.text


@pytest.mark.asyncio
async def test_anonymous_protected_route_is_rejected(api_client):
    response = await api_client.get("/api/tasks")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_SESSION"


@pytest.mark.asyncio
async def test_mutation_requires_matching_csrf_cookie_and_header(api_client):
    csrf_token = await _login(api_client)

    missing = await api_client.put(
        "/api/kill-switch",
        json={"active": True, "reason": "test"},
        headers={"Origin": APP_ORIGIN},
    )
    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "INVALID_CSRF_TOKEN"

    invalid = await api_client.put(
        "/api/kill-switch",
        json={"active": True, "reason": "test"},
        headers={"Origin": APP_ORIGIN, "X-CSRF-Token": "incorrect"},
    )
    assert invalid.status_code == 403
    assert invalid.json()["error"]["code"] == "INVALID_CSRF_TOKEN"

    accepted = await api_client.put(
        "/api/kill-switch",
        json={"active": True, "reason": "test"},
        headers={"Origin": APP_ORIGIN, "X-CSRF-Token": csrf_token},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["resource"]["is_active"] is True


@pytest.mark.asyncio
async def test_workflow_rejects_grant_only_document_selection(api_client):
    csrf_token = await _login(api_client)

    response = await api_client.patch(
        "/api/workflows/reddit_prospector",
        json={"selected_document_hashes": ["a" * 64]},
        headers={"Origin": APP_ORIGIN, "X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "GRANT_ONLY_SETTING"

    trigger = await api_client.post(
        "/api/workflows/reddit_prospector/trigger",
        json={
            "payload": {"selected_document_hashes": ["a" * 64]},
            "idempotency_key": "grant-docs-not-valid-here",
        },
        headers={"Origin": APP_ORIGIN, "X-CSRF-Token": csrf_token},
    )

    assert trigger.status_code == 422
    assert trigger.json()["error"]["code"] == "GRANT_ONLY_SETTING"


@pytest.mark.asyncio
async def test_workflow_schedule_uses_simple_presets_and_hides_legacy_cron(api_client):
    csrf_token = await _login(api_client)
    headers = {"Origin": APP_ORIGIN, "X-CSRF-Token": csrf_token}

    saved = await api_client.patch(
        "/api/workflows/instagram_comments",
        json={"schedule_preset": "every_15_minutes"},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["resource"]["schedule"] == {
        "type": "interval",
        "seconds": 900,
        "preset": "every_15_minutes",
    }
    assert "cron" not in saved.text.lower()

    unavailable = await api_client.patch(
        "/api/workflows/instagram_comments",
        json={"schedule_preset": "daily"},
        headers=headers,
    )
    assert unavailable.status_code == 422
    assert unavailable.json()["error"]["code"] == "INVALID_SCHEDULE_PRESET"

    technical_format = await api_client.patch(
        "/api/workflows/instagram_comments",
        json={"schedule": "*/5 * * * *"},
        headers=headers,
    )
    assert technical_format.status_code == 422


@pytest.mark.asyncio
async def test_portal_integration_credentials_are_write_only(api_client):
    csrf_token = await _login(api_client)
    secret = "https://discord.com/api/webhooks/123456/secret-token"
    saved = await api_client.put(
        "/api/integrations/discord/credentials",
        json={"credentials": {"webhook_url": secret}},
        headers={"Origin": APP_ORIGIN, "X-CSRF-Token": csrf_token},
    )
    assert saved.status_code == 200, saved.text
    assert secret not in saved.text
    assert saved.json()["resource"]["configured_fields"] == ["webhook_url"]

    catalog = await api_client.get("/api/integrations/catalog")
    assert catalog.status_code == 200
    assert secret not in catalog.text
    discord = next(
        item for item in catalog.json()["integrations"] if item["id"] == "discord"
    )
    assert discord["configured"] is True
    assert discord["status"] == "configured"


@pytest.mark.asyncio
async def test_blender_manager_requires_verified_runpod_connection(api_client):
    await _login(api_client)
    response = await api_client.get("/api/blender/pods")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRATION_NOT_VERIFIED"

    catalog = await api_client.get("/api/integrations/catalog")
    runpod = next(item for item in catalog.json()["integrations"] if item["id"] == "runpod")
    assert runpod["configured"] is False
    assert [field["key"] for field in runpod["fields"]] == [
        "api_key", "agent_token", "agent_port", "workspace_root",
    ]


@pytest.mark.asyncio
async def test_blender_template_job_is_durable_and_never_serializes_agent_token(
    api_client, monkeypatch
):
    csrf_token = await _login(api_client)
    agent_token = "agent-token-that-is-longer-than-thirty-two-characters"
    saved = await api_client.put(
        "/api/integrations/runpod/credentials",
        json={"credentials": {"api_key": "rotated-runpod-test-key", "agent_token": agent_token}},
        headers={"Origin": APP_ORIGIN, "X-CSRF-Token": csrf_token},
    )
    assert saved.status_code == 200, saved.text
    await integration_vault.mark_verification("runpod", True)

    async def fake_pods():
        return [{"id": "pod-test-1", "desired_status": "RUNNING"}]

    monkeypatch.setattr("src.integrations.runpod.list_pods", fake_pods)
    queued = await api_client.post(
        "/api/blender/jobs",
        json={
            "pod_id": "pod-test-1",
            "source_path": "/workspace/scene.blend",
            "output_name": "scene_gpu_fixed.blend",
            "frame": 1,
            "samples": 64,
            "resolution_percent": 25,
            "auto_stop": True,
            "idempotency_key": "blender-security-test",
        },
        headers={"Origin": APP_ORIGIN, "X-CSRF-Token": csrf_token},
    )
    assert queued.status_code == 200, queued.text
    assert queued.json()["resource"]["status"] == "queued"
    assert agent_token not in queued.text

    history = await api_client.get("/api/blender/jobs")
    assert history.status_code == 200
    assert len(history.json()["jobs"]) == 1
    assert agent_token not in history.text


def test_meta_webhook_parser_extracts_only_supported_comment_fields():
    payload = {
        "object": "instagram",
        "entry": [{"changes": [{
            "field": "comments",
            "value": {
                "id": "comment-1",
                "text": "Interested in this",
                "from": {"username": "prospect", "private": "discarded"},
                "media": {"id": "media-1", "extra": "discarded"},
                "untrusted": {"nested": "discarded"},
            },
        }]}],
    }
    assert server._instagram_webhook_comments(payload) == [{
        "comment_id": "comment-1",
        "comment_text": "Interested in this",
        "username": "prospect",
        "media_id": "media-1",
        "caption": "",
        "timestamp": "",
    }]


@pytest.mark.asyncio
async def test_telegram_service_token_allows_only_control_surface(api_client):
    headers = _telegram_headers()

    invalid_service = await api_client.get(
        "/api/tasks/service-approval-task",
        headers={"X-Service-Token": "x" * 40, "X-Service-Actor": "telegram"},
    )
    assert invalid_service.status_code == 401
    assert invalid_service.json()["error"]["code"] == "INVALID_SERVICE_TOKEN"

    task = await api_client.get("/api/tasks/service-approval-task", headers=headers)
    assert task.status_code == 200, task.text
    assert task.json()["task_id"] == "service-approval-task"

    task_list = await api_client.get("/api/tasks", headers=headers)
    assert task_list.status_code == 403
    assert task_list.json()["error"]["code"] == "SERVICE_SCOPE_DENIED"

    council = await api_client.post(
        "/api/council-runs",
        json={
            "council": "content",
            "task_description": "Draft a concise approved test message",
            "priority": "normal",
        },
        headers=headers,
    )
    assert council.status_code == 200, council.text

    approval = await api_client.post(
        "/api/approvals/service-approval-task/actions",
        json={
            "action": "reject",
            "expected_version": 1,
            "idempotency_key": "telegram:test:update:1",
            "notes": "Rejected in API security test",
        },
        headers=headers,
    )
    assert approval.status_code == 200, approval.text

    kill_switch = await api_client.put(
        "/api/kill-switch",
        json={"active": False, "reason": "Telegram control test"},
        headers=headers,
    )
    assert kill_switch.status_code == 200, kill_switch.text

    workflow_patch = await api_client.patch(
        "/api/workflows/reddit-prospector",
        json={"paused": True},
        headers=headers,
    )
    assert workflow_patch.status_code == 403
    assert workflow_patch.json()["error"]["code"] == "SERVICE_SCOPE_DENIED"

    workflow_trigger = await api_client.post(
        "/api/workflows/reddit-prospector/trigger",
        json={"payload": {}, "idempotency_key": "telegram-trigger-denied"},
        headers=headers,
    )
    assert workflow_trigger.status_code == 403
    assert workflow_trigger.json()["error"]["code"] == "SERVICE_SCOPE_DENIED"
