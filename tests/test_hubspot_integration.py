from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.core.integration_context import use_integration_configuration
from src.integrations import hubspot


@pytest.mark.asyncio
async def test_verify_connection_requires_contact_read_and_write(monkeypatch):
    monkeypatch.delenv("HUBSPOT_ACCESS_TOKEN", raising=False)
    request = AsyncMock(return_value={
        "hubId": 42,
        "appId": 7,
        "scopes": [
            "crm.objects.contacts.read",
            "crm.objects.contacts.write",
        ],
    })
    monkeypatch.setattr(hubspot, "_request", request)

    with use_integration_configuration({"HUBSPOT_ACCESS_TOKEN": "private-token"}):
        result = await hubspot.verify_connection()

    assert result["hub_id"] == "42"
    assert result["scopes"] == sorted(hubspot.REQUIRED_SCOPES)
    request.assert_awaited_once_with(
        "POST",
        "/oauth/v2/private-apps/get/access-token-info",
        json={"tokenKey": "private-token"},
        include_auth=False,
    )


@pytest.mark.asyncio
async def test_verify_connection_rejects_missing_write_scope(monkeypatch):
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "private-token")
    monkeypatch.setattr(
        hubspot,
        "_request",
        AsyncMock(return_value={"scopes": ["crm.objects.contacts.read"]}),
    )

    with pytest.raises(hubspot.HubSpotIntegrationError, match="contacts.write"):
        await hubspot.verify_connection()


@pytest.mark.asyncio
async def test_sales_sync_uses_explicit_contact_and_deduplicated_note(monkeypatch):
    upsert = AsyncMock(return_value={"id": "contact-123"})
    note = AsyncMock(return_value=({"id": "note-456"}, True))
    monkeypatch.setattr(hubspot, "upsert_contact", upsert)
    monkeypatch.setattr(hubspot, "ensure_outreach_note", note)
    task = {
        "task_id": "task-1",
        "final_output": "Approved outreach",
        "context": {
            "contact_email": "  PERSON@EXAMPLE.COM ",
            "contact_first_name": "Ada",
            "contact_last_name": "Lovelace",
            "company": "Analytical Engines",
        },
    }

    result = await hubspot.sync_approved_sales_task(task)

    assert result == {
        "status": "synced",
        "hubspot_contact_id": "contact-123",
        "hubspot_note_id": "note-456",
        "note_replayed": True,
    }
    upsert.assert_awaited_once_with(
        email="person@example.com",
        firstname="Ada",
        lastname="Lovelace",
        company="Analytical Engines",
    )
    note.assert_awaited_once_with(
        contact_id="contact-123",
        task_id="task-1",
        note_body="Approved outreach",
    )


@pytest.mark.asyncio
async def test_sales_sync_skips_without_valid_explicit_email(monkeypatch):
    upsert = AsyncMock()
    monkeypatch.setattr(hubspot, "upsert_contact", upsert)

    result = await hubspot.sync_approved_sales_task({
        "task_id": "task-2",
        "context": {"contact_email": "not-an-email"},
    })

    assert result == {"status": "skipped", "reason": "missing_contact_email"}
    upsert.assert_not_awaited()
