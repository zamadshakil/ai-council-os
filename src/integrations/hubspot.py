"""HubSpot CRM adapter for approval-driven Sales Council synchronization.

The adapter receives a verified private-app access token through the scoped
integration runtime. It never logs or returns the token. Contact upserts are
keyed by email, and outreach notes contain a stable task marker so a worker
retry can recover without creating duplicate timeline entries.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import httpx

from src.core.integration_context import integration_value


BASE_URL = "https://api.hubapi.com"
REQUIRED_SCOPES = frozenset({
    "crm.objects.contacts.read",
    "crm.objects.contacts.write",
})
NOTE_TO_CONTACT_ASSOCIATION_ID = 202
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class HubSpotIntegrationError(RuntimeError):
    """Sanitized HubSpot failure safe for durable job state and UI display."""

    def __init__(self, message: str, *, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


def _get_token() -> str:
    return integration_value("HUBSPOT_ACCESS_TOKEN", "").strip()


def is_configured() -> bool:
    return bool(_get_token())


def get_hubspot_status() -> dict[str, Any]:
    return {
        "configured": is_configured(),
        "provider": "hubspot",
        "note": (
            "HubSpot is available to linked approved-sales destinations."
            if is_configured()
            else "Configure and verify HubSpot in Settings & Integrations."
        ),
    }


async def _request(
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    include_auth: bool = True,
) -> dict[str, Any]:
    token = _get_token()
    if not token:
        raise HubSpotIntegrationError("HubSpot credentials are not available")
    headers = {"Content-Type": "application/json"}
    if include_auth:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=10.0)) as client:
            response = await client.request(
                method,
                f"{BASE_URL}{path}",
                headers=headers,
                json=json,
                params=params,
            )
    except httpx.TimeoutException as exc:
        raise HubSpotIntegrationError("HubSpot request timed out") from exc
    except httpx.HTTPError as exc:
        raise HubSpotIntegrationError("HubSpot could not be reached") from exc
    if response.status_code >= 400:
        if response.status_code == 401:
            message = "HubSpot rejected the private-app access token"
        elif response.status_code == 403:
            message = "HubSpot token does not have the required CRM permissions"
        elif response.status_code == 429:
            message = "HubSpot rate limit was reached"
        else:
            message = f"HubSpot API request failed with status {response.status_code}"
        raise HubSpotIntegrationError(message, status_code=response.status_code)
    try:
        payload = response.json()
    except ValueError as exc:
        raise HubSpotIntegrationError("HubSpot returned an invalid response") from exc
    if not isinstance(payload, dict):
        raise HubSpotIntegrationError("HubSpot returned an invalid response")
    return payload


async def verify_connection() -> dict[str, Any]:
    """Validate the token and ensure both read and write contact scopes exist."""

    token = _get_token()
    if not token:
        raise HubSpotIntegrationError("HubSpot credentials are not available")
    payload = await _request(
        "POST",
        "/oauth/v2/private-apps/get/access-token-info",
        json={"tokenKey": token},
        include_auth=False,
    )
    scopes = {str(scope) for scope in payload.get("scopes", [])}
    missing = sorted(REQUIRED_SCOPES - scopes)
    if missing:
        raise HubSpotIntegrationError(
            "HubSpot private app is missing required scopes: " + ", ".join(missing)
        )
    return {
        "hub_id": str(payload.get("hubId") or ""),
        "app_id": str(payload.get("appId") or ""),
        "scopes": sorted(scopes),
    }


def extract_contact(task: dict[str, Any]) -> dict[str, str]:
    """Extract explicit CRM fields without trying to infer personal data."""

    context = task.get("context") if isinstance(task.get("context"), dict) else {}
    structured = context.get("structured_output")
    if not isinstance(structured, dict):
        structured = (
            task.get("structured_output")
            if isinstance(task.get("structured_output"), dict)
            else {}
        )

    def first(*keys: str) -> str:
        for source in (context, structured):
            for key in keys:
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    email = first("contact_email", "prospect_email", "email").lower()
    return {
        "email": email if EMAIL_PATTERN.fullmatch(email) else "",
        "firstname": first("contact_first_name", "prospect_first_name", "firstname"),
        "lastname": first("contact_last_name", "prospect_last_name", "lastname"),
        "company": first("company", "company_name", "prospect_company"),
    }


async def find_contact_by_email(email: str) -> dict[str, Any] | None:
    payload = await _request(
        "POST",
        "/crm/v3/objects/contacts/search",
        json={
            "filterGroups": [{
                "filters": [{"propertyName": "email", "operator": "EQ", "value": email}]
            }],
            "properties": ["email", "firstname", "lastname", "company"],
            "limit": 1,
        },
    )
    results = payload.get("results") or []
    return results[0] if results and isinstance(results[0], dict) else None


async def upsert_contact(
    *,
    email: str,
    firstname: str = "",
    lastname: str = "",
    company: str = "",
) -> dict[str, Any]:
    if not EMAIL_PATTERN.fullmatch(email):
        raise ValueError("A valid contact email is required for HubSpot synchronization")
    properties = {"email": email}
    properties.update({
        key: value
        for key, value in {
            "firstname": firstname,
            "lastname": lastname,
            "company": company,
        }.items()
        if value
    })
    existing = await find_contact_by_email(email)
    if existing:
        return await _request(
            "PATCH",
            f"/crm/v3/objects/contacts/{existing['id']}",
            json={"properties": properties},
        )
    try:
        return await _request(
            "POST", "/crm/v3/objects/contacts", json={"properties": properties}
        )
    except HubSpotIntegrationError as exc:
        # Concurrent upserts can race on HubSpot's unique email constraint.
        if exc.status_code != 409:
            raise
        existing = await find_contact_by_email(email)
        if not existing:
            raise
        return await _request(
            "PATCH",
            f"/crm/v3/objects/contacts/{existing['id']}",
            json={"properties": properties},
        )


async def _find_existing_note(contact_id: str, marker: str) -> dict[str, Any] | None:
    contact = await _request(
        "GET",
        f"/crm/v3/objects/contacts/{contact_id}",
        params={"associations": "notes", "archived": "false"},
    )
    note_ids = [
        str(item.get("id"))
        for item in (
            ((contact.get("associations") or {}).get("notes") or {}).get("results")
            or []
        )
        if isinstance(item, dict) and item.get("id")
    ][-100:]
    if not note_ids:
        return None
    notes = await _request(
        "POST",
        "/crm/v3/objects/notes/batch/read",
        json={
            "properties": ["hs_note_body"],
            "inputs": [{"id": note_id} for note_id in note_ids],
        },
    )
    for note in notes.get("results") or []:
        if not isinstance(note, dict):
            continue
        body = str((note.get("properties") or {}).get("hs_note_body") or "")
        if marker in body:
            return note
    return None


async def ensure_outreach_note(
    *,
    contact_id: str,
    task_id: str,
    note_body: str,
) -> tuple[dict[str, Any], bool]:
    marker = f"[AI Council OS task:{task_id}]"
    existing = await _find_existing_note(contact_id, marker)
    if existing:
        return existing, True
    body = f"{note_body.strip()[:60000]}\n\n{marker}"
    note = await _request(
        "POST",
        "/crm/v3/objects/notes",
        json={
            "properties": {
                "hs_timestamp": datetime.now(timezone.utc).isoformat(),
                "hs_note_body": body,
            },
            "associations": [{
                "to": {"id": contact_id},
                "types": [{
                    "associationCategory": "HUBSPOT_DEFINED",
                    "associationTypeId": NOTE_TO_CONTACT_ASSOCIATION_ID,
                }],
            }],
        },
    )
    return note, False


async def sync_approved_sales_task(task: dict[str, Any]) -> dict[str, Any]:
    """Upsert an explicit contact and attach the approved outreach exactly once."""

    contact_fields = extract_contact(task)
    if not contact_fields["email"]:
        return {"status": "skipped", "reason": "missing_contact_email"}
    task_id = str(task.get("task_id") or "").strip()
    if not task_id:
        raise ValueError("A durable task ID is required for HubSpot synchronization")
    contact = await upsert_contact(**contact_fields)
    note, replayed = await ensure_outreach_note(
        contact_id=str(contact["id"]),
        task_id=task_id,
        note_body=str(task.get("final_output") or "Approved Sales Council outreach"),
    )
    return {
        "status": "synced",
        "hubspot_contact_id": str(contact["id"]),
        "hubspot_note_id": str(note.get("id") or ""),
        "note_replayed": replayed,
    }
