"""
hubspot.py — HubSpot CRM Integration

Uses a HubSpot Private App access token (HubSpot's current recommended
auth method — the old API Key auth was deprecated by HubSpot).

Setup once the client provides credentials:
1. HubSpot → Settings → Integrations → Private Apps → Create a private app
2. Grant scopes: crm.objects.contacts.write/read, crm.objects.deals.write/read,
   crm.objects.companies.write/read, timeline (for engagement notes)
3. Copy the generated access token into HUBSPOT_ACCESS_TOKEN in .env

Nothing in this module runs unless HUBSPOT_ACCESS_TOKEN is set — every
function checks configuration first and no-ops safely if absent, so the
Sales Council pipeline keeps working even without HubSpot connected yet.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.hubapi.com"


def _get_token() -> str:
    return os.getenv("HUBSPOT_ACCESS_TOKEN", "").strip()


def is_configured() -> bool:
    return bool(_get_token())


def get_hubspot_status() -> dict:
    """Report whether HubSpot is wired up, for dashboard/API display."""
    return {
        "configured": is_configured(),
        "provider": "hubspot",
        "note": "Set HUBSPOT_ACCESS_TOKEN to enable Sales Council -> HubSpot sync."
        if not is_configured() else "HubSpot sync active.",
    }


def _headers() -> dict:
    token = _get_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def find_contact_by_email(email: str) -> Optional[dict]:
    """Look up an existing contact by email. Returns None if not found or not configured."""
    if not is_configured() or not email:
        return None

    payload = {
        "filterGroups": [
            {"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}
        ],
        "properties": ["email", "firstname", "lastname", "company"],
        "limit": 1,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{BASE_URL}/crm/v3/objects/contacts/search",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return results[0] if results else None


async def upsert_contact(
    email: str,
    firstname: str = "",
    lastname: str = "",
    company: str = "",
    extra_properties: Optional[dict[str, Any]] = None,
) -> Optional[dict]:
    """
    Create a HubSpot contact, or update it if a contact with this email
    already exists. Returns the HubSpot contact record, or None if HubSpot
    isn't configured (safe no-op).
    """
    if not is_configured():
        return None
    if not email:
        raise ValueError("A contact email is required to sync to HubSpot.")

    properties = {"email": email}
    if firstname:
        properties["firstname"] = firstname
    if lastname:
        properties["lastname"] = lastname
    if company:
        properties["company"] = company
    if extra_properties:
        properties.update(extra_properties)

    existing = await find_contact_by_email(email)
    async with httpx.AsyncClient(timeout=20) as client:
        if existing:
            contact_id = existing["id"]
            resp = await client.patch(
                f"{BASE_URL}/crm/v3/objects/contacts/{contact_id}",
                headers=_headers(),
                json={"properties": properties},
            )
        else:
            resp = await client.post(
                f"{BASE_URL}/crm/v3/objects/contacts",
                headers=_headers(),
                json={"properties": properties},
            )
        resp.raise_for_status()
        return resp.json()


async def create_deal(
    dealname: str,
    contact_id: Optional[str] = None,
    amount: Optional[float] = None,
    pipeline_stage: str = "appointmentscheduled",
) -> Optional[dict]:
    """Create a deal, optionally associated with a contact. No-op if not configured."""
    if not is_configured():
        return None

    properties: dict[str, Any] = {"dealname": dealname, "dealstage": pipeline_stage}
    if amount is not None:
        properties["amount"] = amount

    payload: dict[str, Any] = {"properties": properties}
    if contact_id:
        payload["associations"] = [
            {
                "to": {"id": contact_id},
                "types": [
                    {
                        "associationCategory": "HUBSPOT_DEFINED",
                        "associationTypeId": 3,  # deal_to_contact
                    }
                ],
            }
        ]

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{BASE_URL}/crm/v3/objects/deals", headers=_headers(), json=payload
        )
        resp.raise_for_status()
        return resp.json()


async def log_note_engagement(contact_id: str, note_body: str) -> Optional[dict]:
    """Attach a note (e.g. the AI-drafted outreach) to a contact's timeline. No-op if not configured."""
    if not is_configured() or not contact_id:
        return None

    payload = {
        "properties": {"hs_note_body": note_body, "hs_timestamp": _now_ms()},
        "associations": [
            {
                "to": {"id": contact_id},
                "types": [
                    {
                        "associationCategory": "HUBSPOT_DEFINED",
                        "associationTypeId": 202,  # note_to_contact
                    }
                ],
            }
        ],
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{BASE_URL}/crm/v3/objects/notes", headers=_headers(), json=payload
        )
        resp.raise_for_status()
        return resp.json()


def _now_ms() -> int:
    from datetime import datetime, timezone
    return int(datetime.now(timezone.utc).timestamp() * 1000)


async def sync_approved_sales_task(task: dict) -> dict:
    """
    Best-effort sync of an approved Sales Council task into HubSpot: upsert the
    contact (if an email is available in the task context) and log the
    AI-drafted outreach as a note. Safe no-op if HubSpot isn't configured or
    the task doesn't carry a real contact email yet (e.g. Reddit-sourced leads
    before enrichment).
    """
    if not is_configured():
        return {"status": "skipped", "reason": "HubSpot not configured"}

    context = task.get("context", {}) or {}
    email = context.get("contact_email") or context.get("email")
    if not email:
        return {
            "status": "skipped",
            "reason": "No contact email in task context yet (needs Apollo/enrichment first)",
        }

    contact = await upsert_contact(
        email=email,
        firstname=context.get("contact_first_name", ""),
        lastname=context.get("contact_last_name", ""),
        company=context.get("company") or context.get("subreddit", ""),
    )
    if not contact:
        return {"status": "error", "reason": "Contact upsert failed"}

    await log_note_engagement(
        contact_id=contact["id"],
        note_body=f"AI Council OS Sales outreach (approved):\n\n{task.get('final_output', '')[:1900]}",
    )
    return {"status": "synced", "hubspot_contact_id": contact["id"]}
