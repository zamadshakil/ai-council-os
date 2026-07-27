from __future__ import annotations
import os
import httpx

"""
facebook.py — Facebook Page Publisher

Posts AI-generated content to Facebook Pages.
Uses Meta Graph API v21.0.

Requires:
  META_ACCESS_TOKEN (or INSTAGRAM_ACCESS_TOKEN — same app token works)
  FACEBOOK_PAGE_ID — the numeric Facebook Page ID
"""

API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"

async def publish_text(content: str) -> dict:
    """Text-only post."""
    page_id = os.environ.get("FACEBOOK_PAGE_ID")
    token = os.environ.get("META_ACCESS_TOKEN") or os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    if not page_id or not token:
        raise RuntimeError("Missing Facebook credentials (FACEBOOK_PAGE_ID, META_ACCESS_TOKEN).")
        
    url = f"{BASE_URL}/{page_id}/feed"
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
    page_id = os.environ.get("FACEBOOK_PAGE_ID")
    token = os.environ.get("META_ACCESS_TOKEN") or os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    if not page_id or not token:
        raise RuntimeError("Missing Facebook credentials (FACEBOOK_PAGE_ID, META_ACCESS_TOKEN).")
        
    url = f"{BASE_URL}/{page_id}/photos"
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
