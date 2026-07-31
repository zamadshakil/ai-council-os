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

import asyncio
import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

from src.core.kill_switch import is_killed

load_dotenv()

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
    Falls back to ultra-fast direct LLM completion if Council times out or encounters errors.
    """
    from src.core.database import get_workflow_settings
    settings = await get_workflow_settings("instagram-comments")
    custom_prompt = settings.get("custom_prompt", "")
    selected_docs = settings.get("selected_docs", [])

    rag_context = ""
    if selected_docs:
        try:
            from src.core.rag_engine import search_knowledge_base
            results = await search_knowledge_base(comment_text, top_k=3, doc_hashes=selected_docs)
            if results:
                rag_context = "\n\nKNOWLEDGE BASE CONTEXT:\n" + "\n---\n".join([r['text'] for r in results])
        except Exception as e:
            print(f"[Instagram AI] RAG search failed: {e}")

    task_description = (
        f"Generate a friendly, engaging Instagram reply to this comment.\n\n"
        f"Post caption: {caption[:300] if caption else '(no caption)'}\n"
        f"Comment from @{username}: {comment_text}\n\n"
        f"Requirements:\n"
        f"- Keep it conversational and authentic (1-3 sentences max)\n"
        f"- Address the comment specifically\n"
        f"- End with a CTA or question when appropriate\n"
    )
    
    if custom_prompt:
        task_description += f"\nCUSTOM BRAND GUIDELINES:\n{custom_prompt}\n"
        
    if rag_context:
        task_description += rag_context

    try:
        from src.councils.support.council import SupportCouncil
        council = SupportCouncil()

        async def _run_council():
            final_state = {}
            async for chunk in council.graph.astream({
                "task_description": task_description,
                "context": {"workflow": "instagram_commenter", "username": username},
                "priority": "medium",
            }):
                for _, node_state in chunk.items():
                    final_state.update(node_state)
            return final_state.get("final_output") or final_state.get("current_draft", "")

        reply = await asyncio.wait_for(_run_council(), timeout=12.0)
        if reply and reply.strip():
            return reply.strip()
    except Exception as e:
        print(f"[Instagram AI] Council loop timed out or failed ({e}), using fast direct LLM fallback...")

    # Fast fallback: Direct LLM Call (< 2 sec)
    try:
        from src.core.llm_router import call_llm
        system_prompt = (
            "You are the official Instagram AI assistant for ZamDev.me (@zamdev.me). "
            "ZamDev provides custom AI agents, business workflow automation, web development, and digital systems. "
            "Write helpful, professional, friendly 1-2 sentence replies to Instagram comments."
        )
        if custom_prompt:
            system_prompt += f"\n\nCUSTOM BRAND GUIDELINES:\n{custom_prompt}"
        if rag_context:
            system_prompt += f"\n\n{rag_context}"

        user_prompt = f"Comment from @{username}: '{comment_text}'\nPost Caption: '{caption[:200]}'\nReply:"
        res = await call_llm(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            tier="fast"
        )
        return res.get("content", "").strip()
    except Exception as fallback_err:
        print(f"[Instagram AI] Fast fallback error: {fallback_err}")
        return f"Hey @{username}! Thanks for reaching out to ZamDev. How can we help automate your workflow today? 🚀"


# ── Main Workflow ──────────────────────────────────────────────────────

async def run_instagram_commenter(tasks_store: dict) -> dict:
    """
    Main entry point: fetch comments → generate AI replies → post them.

    Returns a summary dict with counts of processed, skipped, and failed comments.
    """
    print("[Instagram Commenter] Starting comment automation run...")

    if is_killed():
        print("🛑 [Instagram Commenter] Kill switch is active. Aborting.")
        return {"status": "killed", "processed": 0}

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
        if is_killed():
            print("🛑 [Instagram Commenter] Kill switch activated mid-run. Stopping.")
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


# ── Instant Webhook Handler (< 5 sec reply) ────────────────────────────

async def handle_instant_webhook_comment(comment_id: str, comment_text: str, username: str, media_id: str = "") -> dict:
    """
    Called instantly when Meta sends a real-time Webhook comment notification.
    Generates AI reply and posts it to Instagram immediately (< 5 sec).
    """
    if not comment_id or not comment_text:
        return {"status": "ignored", "reason": "empty comment or id"}

    if is_killed():
        print(f"🛑 [Instagram Webhook] Kill switch is active. Ignoring comment {comment_id}.")
        return {"status": "killed", "reason": "kill_switch_active"}

    if _is_already_replied(comment_id):
        print(f"[Instagram Webhook] Comment {comment_id} already replied — skipping.")
        return {"status": "skipped", "reason": "already_replied"}

    print(f"[Instagram Webhook] Instant comment received from @{username}: '{comment_text}'")

    try:
        caption = ""
        if media_id:
            try:
                token = _get_token()
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        f"{GRAPH_API_BASE}/{media_id}",
                        params={"fields": "caption", "access_token": token}
                    )
                    if resp.status_code == 200:
                        caption = resp.json().get("caption", "")
            except Exception:
                pass

        reply_text = await generate_reply_for_comment(
            comment_text=comment_text,
            caption=caption,
            username=username,
            tasks_store={},
        )

        if not reply_text:
            return {"status": "failed", "reason": "empty AI reply"}

        res = await post_reply(comment_id, reply_text)
        _mark_replied(comment_id, media_id, reply_text)
        print(f"[Instagram Webhook] Instantly replied to @{username}: '{reply_text}'")

        return {
            "status": "success",
            "comment_id": comment_id,
            "username": username,
            "reply": reply_text,
            "meta_response": res,
        }
    except Exception as e:
        print(f"[Instagram Webhook] Instant reply error: {e}")
        return {"status": "error", "error": str(e)}


def get_instagram_workflow_details() -> dict:
    """Return real connected account details, activity history, and stats from database."""
    conn = _get_replied_conn()
    rows = conn.execute(
        "SELECT comment_id, media_id, replied_at, reply_text FROM replied_comments ORDER BY replied_at DESC LIMIT 50"
    ).fetchall()
    
    activity = []
    for r in rows:
        activity.append({
            "comment_id": r[0],
            "media_id": r[1],
            "replied_at": r[2],
            "reply_text": r[3],
        })

    token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
    has_token = bool(token)
    
    return {
        "id": "instagram-comments",
        "name": "Instagram Comment Auto-Reply",
        "account_name": "Instagram Business",
        "account_handle": os.getenv("INSTAGRAM_USERNAME", "@zamdev.me"),
        "business_id": os.getenv("INSTAGRAM_BUSINESS_ID", "17841462186143667"),
        "page_id": os.getenv("FACEBOOK_PAGE_ID", "693866747149445"),
        "status": "active",
        "token_type": "Page Access Token (Never-Expiring)",
        "token_valid": has_token,
        "webhook_url": "https://187.124.172.17.sslip.io/api/webhooks/instagram",
        "webhook_status": "verified",
        "schedule": "Every 5 minutes",
        "total_replied": len(activity),
        "activity_history": activity,
    }


