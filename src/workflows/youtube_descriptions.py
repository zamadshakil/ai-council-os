"""
youtube_descriptions.py — Bulk Description Updater Workflow

Client spec:
- Rewrites descriptions across the whole video catalogue
- Pull current boilerplate from external source of truth (not hard-coded)
- AI rewrites: keep video-specific opening, replace ONLY defined boilerplate blocks
- Stage to Dashboard FIRST. Publish as a separate, manually-triggered step.
- Batch across runs for YouTube API write quota

Two-phase pipeline:
Phase 1 (auto-scheduled): Generate → Stage in Dashboard
Phase 2 (manual trigger): Read approved updates → Publish to YouTube → Log
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
    update_video_description,
)
from src.integrations.telegram_bot import (
    notify_workflow_start,
    notify_workflow_complete,
    notify_workflow_error,
)

# Config
BOILERPLATE_SOURCE_URL = os.getenv("BOILERPLATE_SOURCE_URL", "")
BATCH_SIZE = int(os.getenv("YT_DESC_BATCH_SIZE", "20"))


async def run_description_generator(tasks_store: dict, boilerplate: str = "") -> dict:
    """
    Phase 1: Generate updated descriptions and stage them in the Dashboard.
    Does NOT publish to YouTube. Human must approve each one first.
    
    Args:
        tasks_store: The shared task state dict
        boilerplate: The current boilerplate/links to inject. If empty, 
                     will try to fetch from BOILERPLATE_SOURCE_URL.
    """
    if is_killed():
        print("🛑 [Description Updater] Kill switch is active. Aborting.")
        return {"status": "killed"}

    await notify_workflow_start(
        "Bulk Description Updater (Phase 1: Generate)",
        f"Batch size: {BATCH_SIZE} videos"
    )

    try:
        # Fetch boilerplate from external source if not provided
        if not boilerplate and BOILERPLATE_SOURCE_URL:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(BOILERPLATE_SOURCE_URL)
                boilerplate = resp.text

        if not boilerplate:
            boilerplate = "No boilerplate configured. Keeping existing descriptions."

        channel_id = os.getenv("YOUTUBE_CHANNEL_ID", "")
        videos = fetch_channel_videos(channel_id, max_results=BATCH_SIZE)
        
        generated = 0

        for video in videos:
            if is_killed():
                break

            video_id = video["video_id"]

            # Skip if already processed this run cycle
            if is_seen(video_id, source="youtube_description"):
                continue

            # Generate updated description
            updated = await _rewrite_description(
                video_title=video["title"],
                current_description=video.get("description", ""),
                boilerplate=boilerplate,
            )

            mark_seen(video_id, source="youtube_description", metadata=video["title"])

            # Stage for human approval in Dashboard
            task_id = f"desc-{str(uuid.uuid4())[:8]}"
            task = {
                "task_id": task_id,
                "council": "content",
                "status": "awaiting_approval",
                "task_description": f"Description update for: {video['title'][:60]}",
                "final_output": updated["description"],
                "confidence_score": updated["confidence"],
                "iterations": 1,
                "total_cost_usd": updated.get("cost", 0),
                "debate_history": [
                    {
                        "role": "generator",
                        "model": updated.get("model", "unknown"),
                        "content": "Generated updated description with new boilerplate blocks.",
                        "confidence_score": updated["confidence"],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "context": {
                    "video_id": video_id,
                    "video_title": video["title"],
                    "old_description": video.get("description", "")[:300],
                    "workflow": "youtube_descriptions",
                },
            }
            tasks_store[task_id] = task
            generated += 1

        summary = f"Generated {generated} updated descriptions out of {len(videos)} videos. All staged in Dashboard."
        await notify_workflow_complete("Bulk Description Updater (Phase 1)", summary)

        return {"status": "complete", "generated": generated, "total_videos": len(videos)}

    except Exception as e:
        await notify_workflow_error("Bulk Description Updater", str(e))
        return {"status": "error", "error": str(e)}


async def publish_approved_descriptions(tasks_store: dict) -> dict:
    """
    Phase 2 (manual trigger): Find all approved description tasks and publish to YouTube.
    Client requirement: "Publish as a second, separately-triggered step."
    """
    if is_killed():
        return {"status": "killed"}

    await notify_workflow_start("Bulk Description Updater (Phase 2: Publish)")

    published = 0
    errors = 0

    for task_id, task in tasks_store.items():
        if task.get("context", {}).get("workflow") != "youtube_descriptions":
            continue
        if task["status"] != "approved":
            continue

        video_id = task["context"]["video_id"]
        new_desc = task["final_output"]

        result = update_video_description(video_id, new_desc)
        if result:
            task["status"] = "published"
            published += 1
        else:
            errors += 1

    summary = f"Published {published} descriptions. Errors: {errors}."
    await notify_workflow_complete("Bulk Description Updater (Phase 2)", summary)

    return {"status": "complete", "published": published, "errors": errors}


async def _rewrite_description(
    video_title: str,
    current_description: str,
    boilerplate: str,
) -> dict:
    """
    AI rewrites the description, replacing ONLY boilerplate blocks
    while preserving the video-specific opening.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are a YouTube SEO specialist updating video descriptions.\n\n"
                "CRITICAL RULES:\n"
                "- PRESERVE the video-specific opening paragraph (first 2-3 sentences).\n"
                "- REPLACE only the boilerplate/links section with the new boilerplate provided.\n"
                "- Do NOT rewrite the video-specific content from scratch.\n"
                "- Keep the tone consistent with the original.\n"
                "- Add relevant timestamps if they exist in the original.\n"
                "- Ensure all links from the new boilerplate are included.\n\n"
                "At the end, on a new line:\nCONFIDENCE: X/100"
            ),
        },
        {
            "role": "user",
            "content": (
                f"VIDEO TITLE: {video_title}\n\n"
                f"CURRENT DESCRIPTION:\n{current_description}\n\n"
                f"NEW BOILERPLATE TO INSERT:\n{boilerplate}\n\n"
                "Produce the updated description:"
            ),
        },
    ]

    result = await call_llm(messages=messages, tier="fast", temperature=0.4)

    import re
    confidence = 80.0
    match = re.search(r"CONFIDENCE:\s*(\d+(?:\.\d+)?)", result["content"], re.IGNORECASE)
    if match:
        confidence = float(match.group(1))

    desc = re.sub(r"\nCONFIDENCE:\s*\d+(?:\.\d+)?/?\d*\s*$", "", result["content"]).strip()

    return {
        "description": desc,
        "confidence": min(max(confidence, 0), 100),
        "model": result["model"],
        "cost": result["cost_usd"],
    }
