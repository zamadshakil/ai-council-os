from __future__ import annotations
import httpx
from src.core.integration_context import integration_value

"""
linkedin.py — LinkedIn Content Publisher

Posts AI-generated content to LinkedIn personal profiles or company pages.
Uses LinkedIn API v2 (Posts API).

Requires:
  LINKEDIN_ACCESS_TOKEN — OAuth 2.0 Bearer token
  LINKEDIN_PERSON_ID — urn:li:person:{id} (for personal) OR
  LINKEDIN_ORGANIZATION_ID — urn:li:organization:{id} (for company pages)
"""

async def _get_author_urn() -> str:
    """Returns person or org URN from env."""
    org_id = integration_value("LINKEDIN_ORGANIZATION_ID")
    if org_id:
        return f"urn:li:organization:{org_id}" if not org_id.startswith("urn:li:organization:") else org_id
    
    person_id = integration_value("LINKEDIN_PERSON_ID")
    if person_id:
        return f"urn:li:person:{person_id}" if not person_id.startswith("urn:li:person:") else person_id
        
    raise RuntimeError("Missing LinkedIn author ID (LINKEDIN_PERSON_ID or LINKEDIN_ORGANIZATION_ID).")

async def _upload_image(image_url: str) -> str:
    """Uploads image and returns asset URN."""
    raise NotImplementedError("Image upload for LinkedIn is not fully implemented yet.")

async def publish(content: str, media_url: str | None = None) -> dict:
    """Posts text (with optional image)."""
    token = integration_value("LINKEDIN_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("Missing LINKEDIN_ACCESS_TOKEN.")
        
    author_urn = await _get_author_urn()
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "LinkedIn-Version": "202401"
    }
    
    payload = {
        "author": author_urn,
        "commentary": content,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": []
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False
    }

    if media_url:
        pass # simplified for now

    async with httpx.AsyncClient() as client:
        resp = await client.post("https://api.linkedin.com/rest/posts", headers=headers, json=payload)
        
        if resp.status_code != 201:
            raise RuntimeError(f"LinkedIn API error: {resp.status_code} - {resp.text}")
            
        return resp.json() if resp.text else {"status": "success"}
