from __future__ import annotations
import os
import importlib

"""
publisher.py — Unified Multi-Platform Publisher

Adapter pattern: all platforms implement publish(content, media_url=None) -> dict.
This service routes approved council output to one or more platforms.

Usage:
    result = await publish_to_platforms(
        content="Your AI-generated post",
        platforms=["instagram", "linkedin", "facebook", "twitter"],
        media_url="https://...",  # optional
    )
"""

PLATFORM_MAP = {
    "instagram": "integrations.instagram",
    "linkedin": "integrations.linkedin",
    "facebook": "integrations.facebook",
    "twitter": "integrations.twitter",
}

async def get_platform_status() -> dict:
    """Checks which platforms have credentials configured."""
    return {
        "instagram": bool(os.environ.get("INSTAGRAM_ACCESS_TOKEN") and os.environ.get("INSTAGRAM_BUSINESS_ID")),
        "linkedin": bool(os.environ.get("LINKEDIN_ACCESS_TOKEN") and (os.environ.get("LINKEDIN_PERSON_ID") or os.environ.get("LINKEDIN_ORGANIZATION_ID"))),
        "facebook": bool((os.environ.get("META_ACCESS_TOKEN") or os.environ.get("INSTAGRAM_ACCESS_TOKEN")) and os.environ.get("FACEBOOK_PAGE_ID")),
        "twitter": bool(os.environ.get("TWITTER_API_KEY") and os.environ.get("TWITTER_ACCESS_TOKEN"))
    }

async def publish_to_platforms(content: str, platforms: list[str], media_url: str | None = None) -> dict:
    """Routes to all selected platforms, collects results."""
    results = {}
    success_count = 0
    fail_count = 0
    
    for platform in platforms:
        if platform not in PLATFORM_MAP:
            results[platform] = {"status": "error", "message": f"Unsupported platform: {platform}"}
            fail_count += 1
            continue
            
        try:
            # Lazy import
            module = importlib.import_module(PLATFORM_MAP[platform])
            
            # Call publish
            result = await module.publish(content, media_url=media_url)
            results[platform] = {"status": "success", "data": result}
            success_count += 1
        except Exception as e:
            results[platform] = {"status": "error", "message": str(e)}
            fail_count += 1
            
    return {
        "results": results,
        "success_count": success_count,
        "fail_count": fail_count
    }
