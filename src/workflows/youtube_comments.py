"""
youtube_comments.py — YouTube Comment Auto-Reply Workflow

Client spec:
- Pulls new comments across the channel
- Drafts context-aware reply with AI (Support Council)
- Posts via YouTube API after human approval
- ~200 comments/day target
- Rate cap per run
- Deduplication against persistent store

Pipeline:
1. Check kill switch → exit if ON
2. Fetch all channel videos
3. Loop over each video → fetch comments
4. Deduplicate each comment ID against persistent DB
5. For each new comment: build prompt with video title + topic + comment text
6. Send to Support Council (LangGraph debate loop)
7. Stage draft for human approval in Dashboard
8. On approval → post reply via YouTube API
"""

import os
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any

from src.core.kill_switch import is_killed
from src.core.dedup import is_seen, mark_seen
from src.core.llm_router import call_llm
from src.integrations.youtube import (
    fetch_channel_videos,
    fetch_recent_comments,
    post_comment_reply,
)
from src.integrations.telegram_bot import (
    notify_workflow_start,
    notify_workflow_complete,
    notify_workflow_error,
    send_draft_for_approval,
)

# Config
MAX_REPLIES_PER_RUN = int(os.getenv("YT_MAX_REPLIES_PER_RUN", "50"))
CONFIDENCE_THRESHOLD = 75.0


async def run_youtube_comment_workflow(tasks_store: dict) -> dict:
    """
    Main entry point for the YouTube Comment Auto-Reply workflow.
    
    Returns a summary dict with stats from this run.
    """
    # 1. Kill switch check
    if is_killed():
        print("🛑 [YouTube Comments] Kill switch is active. Aborting.")
        return {"status": "killed", "processed": 0}

    await notify_workflow_start(
        "YouTube Comment Auto-Reply",
        f"Max replies this run: {MAX_REPLIES_PER_RUN}"
    )

    channel_id = os.getenv("YOUTUBE_CHANNEL_ID", "")
    if not channel_id:
        await notify_workflow_error("YouTube Comment Auto-Reply", "No YOUTUBE_CHANNEL_ID configured")
        return {"status": "error", "error": "No channel ID"}

    try:
        # 2. Fetch all channel videos
        videos = fetch_channel_videos(channel_id, max_results=50)
        
        new_comments = []
        replies_staged = 0

        # 3. Loop over each video → fetch comments
        for video in videos:
            if is_killed():
                break
            if replies_staged >= MAX_REPLIES_PER_RUN:
                break

            video_id = video["video_id"]
            video_title = video["title"]
            
            comments = fetch_recent_comments(video_id, limit=30)

            # 4. Deduplicate
            for comment in comments:
                if replies_staged >= MAX_REPLIES_PER_RUN:
                    break

                comment_id = comment["comment_id"]
                
                if is_seen(comment_id, source="youtube_comment"):
                    continue

                # 5. Build context-aware prompt and get AI reply
                reply_data = await _generate_reply(
                    video_title=video_title,
                    comment_text=comment["text"],
                    comment_author=comment["author"],
                )

                # Mark as seen immediately (even before approval)
                mark_seen(comment_id, source="youtube_comment", metadata=video_title)

                # 6. Stage for human approval in Dashboard
                task_id = f"yt-{str(uuid.uuid4())[:8]}"
                task = {
                    "task_id": task_id,
                    "council": "support",
                    "status": "awaiting_approval",
                    "task_description": f"Reply to comment on '{video_title}' by {comment['author']}",
                    "final_output": reply_data["reply"],
                    "confidence_score": reply_data["confidence"],
                    "iterations": 1,
                    "total_cost_usd": reply_data.get("cost", 0),
                    "debate_history": [
                        {
                            "role": "generator",
                            "model": reply_data.get("model", "unknown"),
                            "content": f"Generated reply to: \"{comment['text'][:100]}...\"",
                            "confidence_score": reply_data["confidence"],
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    ],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "context": {
                        "comment_id": comment_id,
                        "video_id": video_id,
                        "video_title": video_title,
                        "original_comment": comment["text"],
                        "comment_author": comment["author"],
                        "workflow": "youtube_comments",
                    },
                }
                tasks_store[task_id] = task
                replies_staged += 1

                # 7. Notify via Telegram
                await send_draft_for_approval(
                    task_id=task_id,
                    workflow_name="YouTube Comment Reply",
                    draft_text=reply_data["reply"],
                    context_summary=f"Video: {video_title}\nComment by {comment['author']}: {comment['text'][:100]}",
                    confidence=reply_data["confidence"],
                )

        summary = f"Scanned {len(videos)} videos. Staged {replies_staged} new replies for approval."
        await notify_workflow_complete("YouTube Comment Auto-Reply", summary)
        
        return {"status": "complete", "videos_scanned": len(videos), "replies_staged": replies_staged}

    except Exception as e:
        await notify_workflow_error("YouTube Comment Auto-Reply", str(e))
        return {"status": "error", "error": str(e)}


async def _generate_reply(video_title: str, comment_text: str, comment_author: str) -> dict:
    """
    Generate a context-aware reply using the LLM.
    Uses the cheap/fast tier for individual comment replies to save costs.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful, friendly YouTube channel manager.\n\n"
                "RULES:\n"
                "- Reply to the comment naturally and helpfully.\n"
                "- Reference the VIDEO TOPIC to show you actually watched/made the video.\n"
                "- Keep replies under 100 words.\n"
                "- Sound human, not like a bot. Vary your sentence structure.\n"
                "- If the comment is positive, be grateful. If it's a question, answer it.\n"
                "- Never be generic. Never say 'Thanks for watching!' without context.\n\n"
                "At the end of your response, on a new line, write:\n"
                "CONFIDENCE: X/100\n"
                "Score 80+ means the reply is natural and contextual."
            ),
        },
        {
            "role": "user",
            "content": (
                f"VIDEO TITLE: {video_title}\n"
                f"COMMENTER: {comment_author}\n"
                f"COMMENT: {comment_text}\n\n"
                "Write a reply:"
            ),
        },
    ]

    result = await call_llm(messages=messages, tier="fast", temperature=0.8)

    # Extract confidence
    import re
    confidence = 75.0
    match = re.search(r"CONFIDENCE:\s*(\d+(?:\.\d+)?)", result["content"], re.IGNORECASE)
    if match:
        confidence = float(match.group(1))

    # Strip confidence line from reply
    reply = re.sub(r"\nCONFIDENCE:\s*\d+(?:\.\d+)?/?\d*\s*$", "", result["content"]).strip()

    return {
        "reply": reply,
        "confidence": min(max(confidence, 0), 100),
        "model": result["model"],
        "cost": result["cost_usd"],
    }
