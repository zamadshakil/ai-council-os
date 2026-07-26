"""
instagram_commenter.py — Instagram Comment Auto-Reply

CLIENT PRIORITY #1 — Reads comments on Instagram Business posts/reels
and uses the AI Support Council to generate and post contextual replies.

Requirements:
- Meta Business App with instagram_basic, instagram_manage_comments permissions
- Instagram Business or Creator account linked to a Facebook Page
- Long-lived User Access Token or Page Access Token

Flow:
    1. Fetch recent media (posts/reels) from Instagram Business account
    2. For each media, fetch recent comments
    3. Filter out already-replied and already-processed comments (dedup)
    4. Run each comment through the Support Council AI debate loop
    5. Post the AI-generated reply via Graph API
    6. Store processed comment IDs to prevent double-replies
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Optional

import httpx

# ── Config ─────────────────────────────────────────────────────────────
GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
DATA_DIR = Path("./data")
REPLIED_DB_PATH = DATA_DIR / "instagram_replied.db"

# Max comments to process per run (rate limit protection)
MAX_COMMENTS_PER_RUN = 10


# ── Deduplication DB ───────────────────────────────────────────────────

def _get_replied_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(REPLIED_DB_PATH), check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS replied_comments (
            comment_id  TEXT PRIMARY KEY,
            media_id    TEXT,
            replied_at  TEXT DEFAULT (datetime('now')),
            reply_text  TEXT
        )
    """)
    conn.commit()
    return conn


def _is_already_replied(comment_id: str) -> bool:
    conn = _get_replied_conn()
    row = conn.execute(
        "SELECT comment_id FROM replied_comments WHERE comment_id = ?", (comment_id,)
    ).fetchone()
    return row is not None


def _mark_replied(comment_id: str, media_id: str, reply_text: str):
    conn = _get_replied_conn()
    conn.execute(
        "INSERT OR IGNORE INTO replied_comments (comment_id, media_id, reply_text) VALUES (?, ?, ?)",
        (comment_id, media_id, reply_text),
    )
    conn.commit()


# ── Graph API Helpers ──────────────────────────────────────────────────

def _get_token() -> str:
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN") or os.getenv("META_ACCESS_TOKEN")
    if not token:
        raise ValueError(
            "INSTAGRAM_ACCESS_TOKEN not set. Add it to your .env file.\n"
            "Get a long-lived token from: https://developers.facebook.com/tools/explorer/"
        )
    return token


def _get_ig_user_id() -> str:
    user_id = os.getenv("INSTAGRAM_BUSINESS_ID")
    if not user_id:
        raise ValueError(
            "INSTAGRAM_BUSINESS_ID not set. Add your Instagram Business Account ID to .env.\n"
            "Find it in: Meta Business Suite → Settings → Accounts → Instagram Account → ID"
        )
    return user_id


async def fetch_recent_media(limit: int = 10) -> list[dict]:
    """Fetch recent posts and reels from the Instagram Business account."""
    token = _get_token()
    ig_id = _get_ig_user_id()

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{GRAPH_API_BASE}/{ig_id}/media",
            params={
                "fields": "id,caption,media_type,timestamp,comments_count",
                "limit": limit,
                "access_token": token,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])


async def fetch_comments_for_media(media_id: str, limit: int = 25) -> list[dict]:
    """Fetch comments on a specific post/reel."""
    token = _get_token()

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{GRAPH_API_BASE}/{media_id}/comments",
            params={
                "fields": "id,text,username,timestamp,like_count,replies{id,text,username}",
                "limit": limit,
                "access_token": token,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])


async def post_reply(comment_id: str, reply_text: str) -> dict:
    """Post a reply to a specific comment."""
    token = _get_token()

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{GRAPH_API_BASE}/{comment_id}/replies",
            params={"access_token": token},
            data={"message": reply_text},
        )
        resp.raise_for_status()
        return resp.json()


# ── AI Reply Generation ────────────────────────────────────────────────

async def generate_reply_for_comment(
    comment_text: str,
    caption: str,
    username: str,
    tasks_store: dict,
) -> str:
    """
    Use the Support Council AI debate loop to generate a contextual reply.
    Returns the final approved reply text.
    """
    from src.councils.support.council import SupportCouncil

    council = SupportCouncil()
    task_description = (
        f"Generate a friendly, engaging Instagram reply to this comment.\n\n"
        f"Post caption: {caption[:300] if caption else '(no caption)'}\n"
        f"Comment from @{username}: {comment_text}\n\n"
        f"Requirements:\n"
        f"- Keep it conversational and authentic (1-3 sentences max)\n"
        f"- Match the brand voice\n"
        f"- Do NOT use generic responses like 'Thanks!'\n"
        f"- Address the comment specifically\n"
        f"- End with a CTA or question when appropriate"
    )

    final_state = {}
    async for chunk in council.graph.astream({
        "task_description": task_description,
        "context": {"workflow": "instagram_commenter", "username": username},
        "priority": "medium",
    }):
        for _, node_state in chunk.items():
            final_state.update(node_state)

    reply = final_state.get("final_output") or final_state.get("current_draft", "")
    return reply.strip()


# ── Main Workflow ──────────────────────────────────────────────────────

async def run_instagram_commenter(tasks_store: dict) -> dict:
    """
    Main entry point: fetch comments → generate AI replies → post them.

    Returns a summary dict with counts of processed, skipped, and failed comments.
    """
    print("[Instagram Commenter] Starting comment automation run...")

    try:
        media_list = await fetch_recent_media(limit=10)
    except Exception as e:
        return {"status": "error", "error": str(e), "processed": 0}

    total_processed = 0
    total_skipped = 0
    total_failed = 0
    results = []

    for media in media_list:
        if total_processed >= MAX_COMMENTS_PER_RUN:
            break

        media_id = media["id"]
        caption = media.get("caption", "")

        try:
            comments = await fetch_comments_for_media(media_id)
        except Exception as e:
            print(f"[Instagram Commenter] Failed to fetch comments for {media_id}: {e}")
            continue

        for comment in comments:
            if total_processed >= MAX_COMMENTS_PER_RUN:
                break

            comment_id = comment["id"]
            comment_text = comment.get("text", "").strip()
            username = comment.get("username", "unknown")

            # Skip empty comments
            if not comment_text:
                continue

            # Skip if already replied (deduplication)
            if _is_already_replied(comment_id):
                total_skipped += 1
                continue

            # Check if already has a reply from us (check replies field)
            existing_replies = comment.get("replies", {}).get("data", [])
            ig_id = _get_ig_user_id()
            our_reply = next(
                (r for r in existing_replies if r.get("username") == os.getenv("INSTAGRAM_USERNAME", "")),
                None
            )
            if our_reply:
                _mark_replied(comment_id, media_id, our_reply.get("text", ""))
                total_skipped += 1
                continue

            # Generate AI reply
            try:
                print(f"[Instagram Commenter] Generating reply for @{username}: {comment_text[:80]}...")
                reply_text = await generate_reply_for_comment(
                    comment_text=comment_text,
                    caption=caption,
                    username=username,
                    tasks_store=tasks_store,
                )

                if not reply_text:
                    total_failed += 1
                    continue

                # Post the reply
                await post_reply(comment_id, reply_text)
                _mark_replied(comment_id, media_id, reply_text)

                total_processed += 1
                results.append({
                    "comment_id": comment_id,
                    "username": username,
                    "comment": comment_text[:100],
                    "reply": reply_text[:100],
                    "status": "replied",
                })
                print(f"[Instagram Commenter] Replied to @{username}: {reply_text[:60]}...")

            except Exception as e:
                print(f"[Instagram Commenter] Failed to reply to {comment_id}: {e}")
                total_failed += 1

    summary = {
        "status": "ok",
        "processed": total_processed,
        "skipped": total_skipped,
        "failed": total_failed,
        "results": results,
    }
    print(f"[Instagram Commenter] Run complete: {total_processed} replied, {total_skipped} skipped, {total_failed} failed.")
    return summary
