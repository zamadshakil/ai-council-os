"""Official Instagram comment discovery and public reply adapter."""

from __future__ import annotations

from typing import Any

import httpx

from src.core.integration_context import integration_value


class InstagramCommentsError(RuntimeError):
    pass


def _configuration() -> tuple[str, str, str]:
    token = (
        integration_value("META_ACCESS_TOKEN", "")
        or integration_value("INSTAGRAM_ACCESS_TOKEN", "")
    ).strip()
    business_id = integration_value("INSTAGRAM_BUSINESS_ID", "").strip()
    version = integration_value("META_GRAPH_API_VERSION", "v23.0").strip() or "v23.0"
    if not token or not business_id:
        raise InstagramCommentsError("Instagram comment access is not configured")
    return token, business_id, version


async def _get(path: str, *, fields: str, limit: int | None = None) -> dict[str, Any]:
    token, _, version = _configuration()
    params: dict[str, Any] = {"fields": fields, "access_token": token}
    if limit is not None:
        params["limit"] = limit
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.get(
            f"https://graph.facebook.com/{version}/{path}", params=params
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise InstagramCommentsError("Meta returned an unreadable response") from exc
    if response.is_error or payload.get("error"):
        raise InstagramCommentsError("Meta rejected the Instagram comment request")
    return payload


async def verify_comment_access() -> dict[str, str]:
    _, business_id, _ = _configuration()
    payload = await _get(business_id, fields="id,username")
    if not payload.get("id"):
        raise InstagramCommentsError("Meta did not return the Instagram professional account")
    return {"id": str(payload["id"]), "username": str(payload.get("username", ""))}


async def fetch_comment_candidates(
    *, media_limit: int = 10, comments_per_media: int = 25
) -> list[dict[str, str]]:
    _, business_id, _ = _configuration()
    account = await verify_comment_access()
    media_payload = await _get(
        f"{business_id}/media",
        fields="id,caption,media_type,timestamp",
        limit=media_limit,
    )
    candidates: list[dict[str, str]] = []
    for media in media_payload.get("data") or []:
        if not isinstance(media, dict) or not media.get("id"):
            continue
        comments_payload = await _get(
            f"{media['id']}/comments",
            fields="id,text,username,timestamp,replies{id,text,username}",
            limit=comments_per_media,
        )
        for comment in comments_payload.get("data") or []:
            if not isinstance(comment, dict):
                continue
            comment_id = str(comment.get("id", "")).strip()
            text = str(comment.get("text", "")).strip()
            username = str(comment.get("username", "")).strip()
            if not comment_id or not text or username == account.get("username"):
                continue
            replies = (comment.get("replies") or {}).get("data") or []
            already_replied = any(
                isinstance(reply, dict)
                and account.get("username")
                and reply.get("username") == account.get("username")
                for reply in replies
            )
            if already_replied:
                continue
            candidates.append({
                "comment_id": comment_id,
                "comment_text": text,
                "username": username or "instagram_user",
                "media_id": str(media["id"]),
                "caption": str(media.get("caption", "")),
                "timestamp": str(comment.get("timestamp", "")),
            })
    return candidates


async def post_public_reply(comment_id: str, message: str) -> dict[str, Any]:
    token, _, version = _configuration()
    if not comment_id.strip() or not message.strip():
        raise ValueError("Comment ID and reply text are required")
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(
            f"https://graph.facebook.com/{version}/{comment_id.strip()}/replies",
            data={"message": message.strip(), "access_token": token},
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise InstagramCommentsError("Meta returned an unreadable reply response") from exc
    if response.is_error or payload.get("error") or not payload.get("id"):
        raise InstagramCommentsError("Meta did not confirm the Instagram comment reply")
    return payload
