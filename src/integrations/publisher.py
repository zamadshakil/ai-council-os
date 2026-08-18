from __future__ import annotations
import importlib
from src.core.integration_context import integration_value

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
    "instagram": "src.integrations.instagram",
    "linkedin": "src.integrations.linkedin",
    "facebook": "src.integrations.facebook",
    "twitter": "src.integrations.twitter",
    "discord": "src.integrations.discord",
}

async def get_platform_status() -> dict:
    """Checks which platforms have credentials configured."""
    return {
        "instagram": bool(integration_value("INSTAGRAM_ACCESS_TOKEN") and integration_value("INSTAGRAM_BUSINESS_ID")),
        "linkedin": bool(integration_value("LINKEDIN_ACCESS_TOKEN") and (integration_value("LINKEDIN_PERSON_ID") or integration_value("LINKEDIN_ORGANIZATION_ID"))),
        "facebook": bool((integration_value("META_ACCESS_TOKEN") or integration_value("INSTAGRAM_ACCESS_TOKEN")) and integration_value("FACEBOOK_PAGE_ID")),
        "twitter": all(
            bool(integration_value(name))
            for name in (
                "TWITTER_API_KEY",
                "TWITTER_API_SECRET",
                "TWITTER_ACCESS_TOKEN",
                "TWITTER_ACCESS_SECRET",
            )
        ),
        "discord": bool(integration_value("DISCORD_WEBHOOK_URL")),
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
