from __future__ import annotations
import httpx
from src.core.integration_context import integration_value

"""
facebook.py — Facebook Page Publisher

Posts AI-generated content to Facebook Pages.
Uses the configured Meta Graph API version.

Requires:
  META_ACCESS_TOKEN (or INSTAGRAM_ACCESS_TOKEN — same app token works)
  FACEBOOK_PAGE_ID — the numeric Facebook Page ID
"""

def _base_url() -> str:
    version = integration_value("META_GRAPH_API_VERSION", "v23.0").strip() or "v23.0"
    return f"https://graph.facebook.com/{version}"

async def publish_text(content: str) -> dict:
    """Text-only post."""
    page_id = integration_value("FACEBOOK_PAGE_ID")
    token = integration_value("META_ACCESS_TOKEN") or integration_value("INSTAGRAM_ACCESS_TOKEN")
    if not page_id or not token:
        raise RuntimeError("Missing Facebook credentials (FACEBOOK_PAGE_ID, META_ACCESS_TOKEN).")
        
    url = f"{_base_url()}/{page_id}/feed"
    payload = {
        "message": content,
        "access_token": token
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, data=payload)
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Facebook API error: {data['error']}")
        return data

async def publish_with_image(content: str, image_url: str) -> dict:
    """Posts with photo."""
    page_id = integration_value("FACEBOOK_PAGE_ID")
    token = integration_value("META_ACCESS_TOKEN") or integration_value("INSTAGRAM_ACCESS_TOKEN")
    if not page_id or not token:
        raise RuntimeError("Missing Facebook credentials (FACEBOOK_PAGE_ID, META_ACCESS_TOKEN).")
        
    url = f"{_base_url()}/{page_id}/photos"
    payload = {
        "url": image_url,
        "message": content,
        "access_token": token
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, data=payload)
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Facebook API error: {data['error']}")
        return data

async def publish(content: str, media_url: str | None = None) -> dict:
    """Posts to page feed."""
    if media_url:
        return await publish_with_image(content, media_url)
    return await publish_text(content)
