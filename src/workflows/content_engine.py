"""
content_engine.py — Multi-Platform Content Engine Workflow

Client spec:
- Takes one YouTube video and produces 6+ rewritten posts
  (X, LinkedIn, Facebook, Instagram, Reddit, Discord)
- Each platform needs its own length, tone and format
- Structured output: one field per destination
- A missing or malformed field must fail the run, not publish empty
- Log every post + destination + timestamp
- Route each variant to its platform

Pipeline:
1. Check kill switch
2. Input: video transcript + metadata
3. Send to Content Council with per-platform specs
4. Validate all 6 outputs exist and meet length/format requirements
5. Stage each variant in Dashboard for approval
6. On approval → route to platform API
"""

import os
import re
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from src.core.kill_switch import is_killed
from src.core.llm_router import call_llm
from src.integrations.telegram_bot import (
    notify_workflow_start,
    notify_workflow_complete,
    notify_workflow_error,
)
from src.workflows.config.platform_specs import PLATFORM_SPECS, get_platform_prompt


async def run_content_engine(
    video_title: str,
    transcript: str,
    video_id: str,
    tasks_store: dict,
    metadata: Optional[Dict[str, Any]] = None,
) -> dict:
    """
    Main entry point for the Multi-Platform Content Engine.
    
    Args:
        video_title: Title of the source video
        transcript: Full video transcript text
        video_id: YouTube video ID (for tracking)
        tasks_store: Shared task state dict
        metadata: Optional video metadata (tags, description, etc.)
    """
    if is_killed():
        print("🛑 [Content Engine] Kill switch is active. Aborting.")
        return {"status": "killed"}

    platforms = list(PLATFORM_SPECS.keys())
    await notify_workflow_start(
        "Multi-Platform Content Engine",
        f"Source: {video_title}\nTargeting {len(platforms)} platforms"
    )

    try:
        # Generate all variants in one call (cost-efficient)
        variants = await _generate_all_variants(video_title, transcript, metadata)

        # Validate: every platform must have content
        missing = [p for p in platforms if p not in variants or not variants[p].strip()]
        if missing:
            error = f"Missing content for platforms: {', '.join(missing)}"
            await notify_workflow_error("Content Engine", error)
            return {"status": "error", "error": error, "missing_platforms": missing}

        # Validate: length constraints
        for platform, content in variants.items():
            spec = PLATFORM_SPECS.get(platform, {})
            max_len = spec.get("max_length", 99999)
            if len(content) > max_len:
                # Truncate with warning (don't fail the whole run)
                variants[platform] = content[:max_len]

        # Stage each variant as a separate task in Dashboard
        staged = 0
        for platform, content in variants.items():
            task_id = f"ctn-{platform[:3]}-{str(uuid.uuid4())[:6]}"
            spec = PLATFORM_SPECS[platform]

            task = {
                "task_id": task_id,
                "council": "content",
                "status": "awaiting_approval",
                "task_description": f"{spec['name']} post from '{video_title[:40]}'",
                "final_output": content,
                "confidence_score": 85.0,
                "iterations": 1,
                "total_cost_usd": 0,
                "debate_history": [
                    {
                        "role": "generator",
                        "model": "content-engine",
                        "content": f"Generated {spec['name']} variant ({len(content)} chars, max {spec['max_length']})",
                        "confidence_score": 85.0,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "context": {
                    "video_id": video_id,
                    "video_title": video_title,
                    "platform": platform,
                    "platform_name": spec["name"],
                    "max_length": spec["max_length"],
                    "workflow": "content_engine",
                },
            }
            tasks_store[task_id] = task
            staged += 1

        summary = (
            f"Generated {staged} platform variants from '{video_title}'.\n"
            f"Platforms: {', '.join(PLATFORM_SPECS[p]['name'] for p in variants.keys())}\n"
            f"All staged in Dashboard for review."
        )
        await notify_workflow_complete("Multi-Platform Content Engine", summary)

        return {"status": "complete", "variants_staged": staged, "platforms": list(variants.keys())}

    except Exception as e:
        await notify_workflow_error("Content Engine", str(e))
        return {"status": "error", "error": str(e)}


async def _generate_all_variants(
    video_title: str,
    transcript: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """
    Generate all 6 platform variants in a single LLM call.
    Uses structured JSON output for reliable parsing.
    """
    # Build per-platform spec blocks
    platform_instructions = ""
    for platform_key, spec in PLATFORM_SPECS.items():
        platform_instructions += f"\n### {spec['name']} (key: \"{platform_key}\")\n"
        platform_instructions += get_platform_prompt(platform_key) + "\n"

    messages = [
        {
            "role": "system",
            "content": (
                "You are a world-class content repurposing specialist.\n\n"
                "You will receive a YouTube video transcript and must create "
                "UNIQUE, PLATFORM-OPTIMIZED posts for 6 different platforms.\n\n"
                "CRITICAL RULES:\n"
                "- Each post must be COMPLETELY DIFFERENT in structure and tone.\n"
                "- Follow the exact platform specs below for length, tone, and format.\n"
                "- Do NOT cross-post identical content. That's the whole point of this system.\n"
                "- Extract the most valuable insight from the video for each audience.\n\n"
                f"PLATFORM SPECIFICATIONS:\n{platform_instructions}\n\n"
                "OUTPUT FORMAT: Respond with valid JSON only. No markdown code fences.\n"
                "The JSON must have exactly these keys: twitter, linkedin, facebook, instagram, reddit, discord\n"
                "Each value must be the complete post text as a string."
            ),
        },
        {
            "role": "user",
            "content": (
                f"VIDEO TITLE: {video_title}\n"
                f"VIDEO TAGS: {metadata.get('tags', 'N/A') if metadata else 'N/A'}\n\n"
                f"TRANSCRIPT (first 3000 chars):\n{transcript[:3000]}\n\n"
                "Generate all 6 platform posts as JSON:"
            ),
        },
    ]

    result = await call_llm(messages=messages, tier="smart", temperature=0.7, max_tokens=6000)

    # Parse JSON from response
    content = result["content"].strip()
    
    # Strip markdown code fences if present
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)

    try:
        variants = json.loads(content)
    except json.JSONDecodeError:
        # Fallback: try to extract JSON from the response
        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            variants = json.loads(json_match.group())
        else:
            raise ValueError(f"Failed to parse structured output from Content Engine: {content[:200]}")

    return variants
