from __future__ import annotations
import asyncio
import httpx
from src.core.integration_context import integration_value

"""
instagram.py — Instagram Content Publisher

Posts AI-generated content to Instagram Business accounts.
Uses the 2-step container workflow required by Meta Graph API:
  1. Create media container (POST /ig_user_id/media)
  2. Poll until container is ready (GET /ig_container_id?fields=status_code)
  3. Publish container (POST /ig_user_id/media_publish)

Supports: Image posts, Reels, Carousels.
Requires: INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_BUSINESS_ID in .env
"""

def _base_url() -> str:
    version = integration_value("META_GRAPH_API_VERSION", "v23.0").strip() or "v23.0"
    return f"https://graph.facebook.com/{version}"

async def _poll_container(container_id: str, token: str, max_wait: int = 60) -> bool:
    """Polls the container status every 5s until FINISHED or timeout."""
    start_time = asyncio.get_event_loop().time()
    url = f"{_base_url()}/{container_id}"
    params = {"fields": "status_code", "access_token": token}
    
    async with httpx.AsyncClient() as client:
        while asyncio.get_event_loop().time() - start_time < max_wait:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("status_code")
                if status == "FINISHED":
                    return True
                elif status == "ERROR":
                    raise RuntimeError(f"Instagram container error: {data}")
            await asyncio.sleep(5)
    return False

async def publish_photo(caption: str, image_url: str) -> dict:
    """Posts an image with caption."""
    token = integration_value("INSTAGRAM_ACCESS_TOKEN") or integration_value("META_ACCESS_TOKEN")
    ig_user_id = integration_value("INSTAGRAM_BUSINESS_ID")
    if not token or not ig_user_id:
        raise RuntimeError("Missing Instagram credentials (INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_BUSINESS_ID).")

    async with httpx.AsyncClient() as client:
        # 1. Create media container
        create_url = f"{_base_url()}/{ig_user_id}/media"
        payload = {
            "image_url": image_url,
            "caption": caption,
            "access_token": token
        }
        create_resp = await client.post(create_url, data=payload)
        create_data = create_resp.json()
        
        if "error" in create_data:
            raise RuntimeError(f"Failed to create Instagram container: {create_data['error']}")
            
        container_id = create_data["id"]
        
        # 2. Poll container
        ready = await _poll_container(container_id, token)
        if not ready:
            raise RuntimeError("Instagram container timed out.")
            
        # 3. Publish container
        publish_url = f"{_base_url()}/{ig_user_id}/media_publish"
        publish_payload = {
            "creation_id": container_id,
            "access_token": token
        }
        publish_resp = await client.post(publish_url, data=publish_payload)
        publish_data = publish_resp.json()
        
        if "error" in publish_data:
            raise RuntimeError(f"Failed to publish Instagram container: {publish_data['error']}")
            
        return publish_data

async def publish_reel(caption: str, video_url: str) -> dict:
    """Posts a reel."""
    token = integration_value("INSTAGRAM_ACCESS_TOKEN") or integration_value("META_ACCESS_TOKEN")
    ig_user_id = integration_value("INSTAGRAM_BUSINESS_ID")
    if not token or not ig_user_id:
        raise RuntimeError("Missing Instagram credentials.")

    async with httpx.AsyncClient() as client:
        # 1. Create media container
        create_url = f"{_base_url()}/{ig_user_id}/media"
        payload = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": token
        }
        create_resp = await client.post(create_url, data=payload)
        create_data = create_resp.json()
        
        if "error" in create_data:
            raise RuntimeError(f"Failed to create Instagram container: {create_data['error']}")
            
        container_id = create_data["id"]
        
        # 2. Poll container
        ready = await _poll_container(container_id, token)
        if not ready:
            raise RuntimeError("Instagram container timed out.")
            
        # 3. Publish container
        publish_url = f"{_base_url()}/{ig_user_id}/media_publish"
        publish_payload = {
            "creation_id": container_id,
            "access_token": token
        }
        publish_resp = await client.post(publish_url, data=publish_payload)
        publish_data = publish_resp.json()
        
        if "error" in publish_data:
            raise RuntimeError(f"Failed to publish Instagram container: {publish_data['error']}")
            
        return publish_data

async def publish(content: str, media_url: str | None = None) -> dict:
    """Unified adapter interface."""
    if not media_url:
        raise RuntimeError("Instagram requires a media_url (image or video) to publish.")
    if media_url.lower().endswith(('.mp4', '.mov')):
        return await publish_reel(content, media_url)
    return await publish_photo(content, media_url)
