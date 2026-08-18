"""Approval-gated Discord publishing through an administrator-owned webhook."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
from src.core.integration_context import integration_value


def _webhook_url() -> str:
    url = integration_value("DISCORD_WEBHOOK_URL", "").strip()
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"discord.com", "discordapp.com"}
        or "/api/webhooks/" not in parsed.path
    ):
        raise RuntimeError("DISCORD_WEBHOOK_URL is missing or invalid")
    return url


async def publish(content: str, media_url: str | None = None) -> dict:
    """Post one approved message and return Discord's persisted message ID."""
    if not content.strip():
        raise RuntimeError("Discord content cannot be empty")
    payload: dict[str, object] = {
        "content": content[:2000],
        "allowed_mentions": {"parse": []},
    }
    if media_url:
        payload["embeds"] = [{"url": media_url}]
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(_webhook_url(), params={"wait": "true"}, json=payload)
    if response.status_code not in {200, 201, 204}:
        raise RuntimeError(f"Discord API error: HTTP {response.status_code}")
    return response.json() if response.content else {"status": "published"}
