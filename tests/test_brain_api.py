from __future__ import annotations

import hashlib

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import func, select

from src.api import server
from src.core import database as db, integration_vault
from src.core.models import (
    ApprovalModel,
    AuditEventModel,
    BrainFactModel,
    CouncilRunModel,
    IdempotencyRecordModel,
    KnowledgeCollectionModel,
    KnowledgeDocumentModel,
    MCPTokenModel,
    RetrievalCacheModel,
    TaskModel,
    WorkflowRunModel,
)


APP_ORIGIN = "http://localhost:3000"
ADMIN_PASSWORD = "native-brain-test-password"


@pytest_asyncio.fixture
async def brain_client(session_factory, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("APP_ORIGIN", APP_ORIGIN)
    monkeypatch.setenv("INTEGRATION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(db, "async_session", session_factory)
    monkeypatch.setattr(server, "async_session", session_factory)
    monkeypatch.setattr(server.auth_service, "_session_factory", session_factory)
    monkeypatch.setattr(server.approval_service, "_session_factory", session_factory)
    monkeypatch.setattr(server.job_service, "_session_factory", session_factory)
    monkeypatch.setattr(integration_vault, "async_session", session_factory)
    await server.auth_service.ensure_admin("brain-admin", ADMIN_PASSWORD)
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client, session_factory


async def login(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/api/auth/login",
        json={"username": "brain-admin", "password": ADMIN_PASSWORD},
        headers={"Origin": APP_ORIGIN},
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


@pytest.mark.asyncio
async def test_brain_routes_are_protected_and_bindings_are_persisted(brain_client):
    client, _ = brain_client
    assert (await client.get("/api/brain/graph")).status_code == 401
    csrf = await login(client)
    headers = {"Origin": APP_ORIGIN, "X-CSRF-Token": csrf}
    collection = await client.post(
        "/api/knowledge/collections",
        headers=headers,
        json={
            "name": "Product truth",
            "description": "Approved evidence",
            "document_ids": [],
            "idempotency_key": "collection-create-001",
        },
    )
    assert collection.status_code == 200, collection.text
    collection_id = collection.json()["resource"]["id"]
    binding = await client.put(
        "/api/councils/sales/knowledge-bindings",
        headers=headers,
        json={
            "collection_ids": [collection_id],
            "expected_version": 1,
            "idempotency_key": "bind-sales-001",
        },
    )
    assert binding.status_code == 200, binding.text
    listed = await client.get("/api/knowledge/collections")
    assert listed.json()["collections"][0]["bindings"] == [
        {"target_type": "council", "target_id": "sales"}
    ]

    per_run_override = await client.post(
        "/api/council-runs",
        headers={**headers, "Idempotency-Key": "sales-scope-override-001"},
        json={
            "council": "sales",
            "task_description": "Draft a collection-grounded outreach message",
            "selected_collection_ids": [collection_id],
        },
    )
    assert per_run_override.status_code == 422
    assert per_run_override.json()["error"]["code"] == "GRANT_ONLY_SETTING"


@pytest.mark.asyncio
async def test_knowledge_upload_and_delete_are_versioned_and_idempotent(brain_client):
    client, session_factory = brain_client
    csrf = await login(client)
    headers = {
        "Origin": APP_ORIGIN,
        "X-CSRF-Token": csrf,
        "Idempotency-Key": "knowledge-upload-001",
    }
    files = {
        "file": (
            "evidence.md",
            b"A cited and durable evidence passage.",
            "text/markdown",
        )
    }
    created = await client.post(
        "/api/knowledge/documents", headers=headers, files=files
    )
    assert created.status_code == 200, created.text
    replayed = await client.post(
        "/api/knowledge/documents", headers=headers, files=files
    )
    assert replayed.status_code == 200
    assert replayed.json()["replayed"] is True
    resource = created.json()["resource"]
    async with session_factory() as session:
        assert (
            int(
                await session.scalar(select(func.count(KnowledgeDocumentModel.id))) or 0
            )
            == 1
        )

    delete_body = {
        "expected_version": resource["version"],
        "idempotency_key": "knowledge-delete-001",
    }
    deleted = await client.request(
        "DELETE",
        f"/api/knowledge/documents/{resource['id']}",
        headers={"Origin": APP_ORIGIN, "X-CSRF-Token": csrf},
        json=delete_body,
    )
    assert deleted.status_code == 200, deleted.text
    replayed_delete = await client.request(
        "DELETE",
        f"/api/knowledge/documents/{resource['id']}",
        headers={"Origin": APP_ORIGIN, "X-CSRF-Token": csrf},
        json=delete_body,
    )
    assert replayed_delete.status_code == 200
    assert replayed_delete.json()["replayed"] is True


@pytest.mark.asyncio
async def test_fact_correction_creates_proposed_successor_without_overwriting(
    brain_client,
):
    client, session_factory = brain_client
    csrf = await login(client)
    async with session_factory() as session:
        original = BrainFactModel(
            predicate="budget",
            value_text="10",
            normalized_value="10",
            status="verified",
            confidence=1.0,
            version=1,
        )
        session.add(original)
        await session.flush()
        original_id = original.id
        session.add(
            RetrievalCacheModel(
                id="d" * 64,
                query_hash="e" * 64,
                scope_hash="f" * 64,
                model_version="BAAI/bge-small-en-v1.5",
                index_version=2,
                query_vector=[0.0] * 384,
                result={"results": [{"fact_id": original_id}]},
                expires_at=server.utcnow() + server.timedelta(minutes=20),
            )
        )
        await session.commit()

    response = await client.post(
        "/api/brain/review-actions",
        headers={"Origin": APP_ORIGIN, "X-CSRF-Token": csrf},
        json={
            "resource_type": "fact",
            "resource_id": original_id,
            "action": "supersede",
            "replacement_value": "20",
            "notes": "Administrator correction",
            "expected_version": 1,
            "idempotency_key": "fact-supersede-001",
        },
    )
    assert response.status_code == 200, response.text
    replacement_id = response.json()["resource"]["replacement_fact_id"]
    async with session_factory() as session:
        old = await session.get(BrainFactModel, original_id)
        replacement = await session.get(BrainFactModel, replacement_id)
        assert old.status == "superseded"
        assert old.value_text == "10"
        assert replacement.status == "proposed"
        assert replacement.value_text == "20"
        assert replacement.supersedes_fact_id == original_id
        assert (
            int(await session.scalar(select(func.count(RetrievalCacheModel.id))) or 0)
            == 0
        )


@pytest.mark.asyncio
async def test_mutation_replay_failure_rolls_back_resource_and_audit(
    brain_client, monkeypatch
):
    client, session_factory = brain_client
    csrf = await login(client)

    async def fail_replay_store(*_args, **_kwargs):
        raise RuntimeError("simulated crash before atomic commit")

    monkeypatch.setattr(server, "_store_mutation_replay", fail_replay_store)
    with pytest.raises(RuntimeError, match="simulated crash"):
        await client.post(
            "/api/knowledge/collections",
            headers={"Origin": APP_ORIGIN, "X-CSRF-Token": csrf},
            json={
                "name": "Must roll back",
                "description": "",
                "document_ids": [],
                "idempotency_key": "atomic-rollback-001",
            },
        )
    async with session_factory() as session:
        assert (
            int(
                await session.scalar(select(func.count(KnowledgeCollectionModel.id)))
                or 0
            )
            == 0
        )
        assert (
            int(await session.scalar(select(func.count(AuditEventModel.id))) or 0) == 0
        )
        assert (
            int(
                await session.scalar(select(func.count(IdempotencyRecordModel.id))) or 0
            )
            == 0
        )


@pytest.mark.asyncio
async def test_mcp_tokens_are_hashed_header_only_and_expose_no_privileged_tools(
    brain_client,
):
    client, session_factory = brain_client
    csrf = await login(client)
    created = await client.post(
        "/api/mcp/tokens",
        headers={"Origin": APP_ORIGIN, "X-CSRF-Token": csrf},
        json={
            "name": "Read-only audit",
            "expires_in_days": 1,
            "scopes": ["brain:read"],
            "idempotency_key": "mcp-token-create-001",
        },
    )
    assert created.status_code == 200, created.text
    created_resource = created.json()["resource"]
    raw_token = created_resource["token"]
    replayed = await client.post(
        "/api/mcp/tokens",
        headers={"Origin": APP_ORIGIN, "X-CSRF-Token": csrf},
        json={
            "name": "Read-only audit",
            "expires_in_days": 1,
            "scopes": ["brain:read"],
            "idempotency_key": "mcp-token-create-001",
        },
    )
    assert replayed.status_code == 200
    assert replayed.json()["resource"]["token"] == raw_token
    assert replayed.json()["replayed"] is True
    conflicting_replay = await client.post(
        "/api/mcp/tokens",
        headers={"Origin": APP_ORIGIN, "X-CSRF-Token": csrf},
        json={
            "name": "Different request",
            "expires_in_days": 1,
            "scopes": ["brain:read"],
            "idempotency_key": "mcp-token-create-001",
        },
    )
    assert conflicting_replay.status_code == 409
    assert conflicting_replay.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    async with session_factory() as session:
        stored = (await session.execute(select(MCPTokenModel))).scalar_one()
        assert stored.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
        assert raw_token not in stored.token_hash

    rejected = await client.post(
        f"/mcp?token={raw_token}",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert rejected.status_code == 401
    assert rejected.json()["error"]["code"] == "QUERY_TOKEN_REJECTED"

    listed = await client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {raw_token}"},
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    assert listed.status_code == 200, listed.text
    names = {item["name"] for item in listed.json()["result"]["tools"]}
    assert names == {
        "search_brain",
        "inspect_entities",
        "inspect_citations",
        "propose_council_run",
        "read_task_status",
    }
    assert not names & {"approve", "publish", "kill_switch", "runpod", "credentials"}

    denied = await client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {raw_token}"},
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "propose_council_run",
                "arguments": {
                    "council": "sales",
                    "task_description": "Create a proposal",
                },
            },
        },
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "MCP_SCOPE_DENIED"

    revoked = await client.request(
        "DELETE",
        f"/api/mcp/tokens/{created_resource['id']}",
        headers={"Origin": APP_ORIGIN, "X-CSRF-Token": csrf},
        json={
            "expected_version": created_resource["version"],
            "idempotency_key": "mcp-token-revoke-001",
        },
    )
    assert revoked.status_code == 200, revoked.text
    replayed_revoke = await client.request(
        "DELETE",
        f"/api/mcp/tokens/{created_resource['id']}",
        headers={"Origin": APP_ORIGIN, "X-CSRF-Token": csrf},
        json={
            "expected_version": created_resource["version"],
            "idempotency_key": "mcp-token-revoke-001",
        },
    )
    assert replayed_revoke.status_code == 200
    assert replayed_revoke.json()["replayed"] is True
    assert (
        await client.post(
            "/mcp",
            headers={"Authorization": f"Bearer {raw_token}"},
            json={"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
        )
    ).status_code == 401


@pytest.mark.asyncio
async def test_mcp_proposal_retry_reuses_the_same_task_run_and_job(brain_client):
    client, session_factory = brain_client
    csrf = await login(client)
    created = await client.post(
        "/api/mcp/tokens",
        headers={"Origin": APP_ORIGIN, "X-CSRF-Token": csrf},
        json={
            "name": "Proposal client",
            "expires_in_days": 1,
            "scopes": ["council:propose"],
            "idempotency_key": "mcp-proposal-token-001",
        },
    )
    token = created.json()["resource"]["token"]
    payload = {
        "jsonrpc": "2.0",
        "id": "proposal-42",
        "method": "tools/call",
        "params": {
            "name": "propose_council_run",
            "arguments": {
                "council": "sales",
                "task_description": "Draft an evidence-based outreach brief",
            },
        },
    }
    first = await client.post(
        "/mcp", headers={"Authorization": f"Bearer {token}"}, json=payload
    )
    second = await client.post(
        "/mcp", headers={"Authorization": f"Bearer {token}"}, json=payload
    )
    assert first.status_code == second.status_code == 200
    first_result = first.json()["result"]["structuredContent"]
    second_result = second.json()["result"]["structuredContent"]
    assert first_result == second_result
    async with session_factory() as session:
        assert (
            int(await session.scalar(select(func.count(TaskModel.task_id))) or 0) == 1
        )
        assert (
            int(await session.scalar(select(func.count(CouncilRunModel.id))) or 0) == 1
        )
        assert int(await session.scalar(select(func.count(ApprovalModel.id))) or 0) == 1
        assert (
            int(await session.scalar(select(func.count(WorkflowRunModel.id))) or 0) == 1
        )
