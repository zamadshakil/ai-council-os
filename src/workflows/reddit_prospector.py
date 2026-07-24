"""
reddit_prospector.py — Reddit Lead Prospector Workflow

Client spec:
- Monitors 45 subreddits
- Finds posts where someone describes a problem we solve
- AI scores intent (is this a real request for a solution?)
- Drafts contextual reply (answers question FIRST, then subtle mention)
- Logs to Dashboard for human review
- NO auto-posting. Human reviews and approves.
- Per-subreddit volume cap
- Target: 10-20 warm leads/day

Pipeline:
1. Check kill switch
2. Load subreddit config (45 subs, keywords, exclusions)
3. Loop over subreddits → fetch posts via official Reddit API
4. Filter by exclusion terms, deduplicate against persistent DB
5. AI intent scoring (cheap tier) → discard below threshold
6. For qualifying posts → draft reply via Sales Council
7. Stage in Dashboard for human review
8. Telegram run summary
"""

import os
import re
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any

from src.core.kill_switch import is_killed
from src.core.dedup import is_seen, mark_seen
from src.core.llm_router import call_llm
from src.integrations.reddit import fetch_prospect_leads
from src.integrations.telegram_bot import (
    notify_workflow_start,
    notify_workflow_complete,
    notify_workflow_error,
)
from src.workflows.config.reddit_config import (
    SUBREDDITS,
    INTENT_KEYWORDS,
    EXCLUSION_TERMS,
    MAX_POSTS_PER_SUBREDDIT,
    MAX_LEADS_PER_RUN,
    INTENT_SCORE_THRESHOLD,
)


async def run_reddit_prospector(tasks_store: dict) -> dict:
    """
    Main entry point for the Reddit Lead Prospector workflow.
    """
    # 1. Kill switch check
    if is_killed():
        print("🛑 [Reddit Prospector] Kill switch is active. Aborting.")
        return {"status": "killed", "processed": 0}

    await notify_workflow_start(
        "Reddit Lead Prospector",
        f"Scanning {len(SUBREDDITS)} subreddits. Max leads: {MAX_LEADS_PER_RUN}"
    )

    try:
        total_scanned = 0
        total_filtered = 0
        leads_found = 0

        # 2-3. Fetch posts from all subreddits
        all_posts = fetch_prospect_leads(SUBREDDITS, limit=MAX_POSTS_PER_SUBREDDIT)
        total_scanned = len(all_posts)

        # 4a. Filter by exclusion terms
        filtered_posts = []
        for post in all_posts:
            text = (post["title"] + " " + post["body"]).lower()
            if any(term.lower() in text for term in EXCLUSION_TERMS):
                continue
            if is_seen(post["id"], source="reddit"):
                continue
            filtered_posts.append(post)

        total_filtered = len(filtered_posts)

        # 5. AI intent scoring (cheap tier to save costs)
        for post in filtered_posts:
            if is_killed():
                break
            if leads_found >= MAX_LEADS_PER_RUN:
                break

            # Score intent
            intent = await _score_intent(post)
            mark_seen(post["id"], source="reddit", metadata=post["subreddit"])

            if intent["score"] < INTENT_SCORE_THRESHOLD:
                continue

            # 6. Draft a contextual reply
            reply_data = await _draft_reply(post)

            # 7. Stage in Dashboard for human review
            task_id = f"rd-{str(uuid.uuid4())[:8]}"
            task = {
                "task_id": task_id,
                "council": "sales",
                "status": "awaiting_approval",
                "task_description": f"Reddit lead from r/{post['subreddit']}: {post['title'][:80]}",
                "final_output": reply_data["reply"],
                "confidence_score": intent["score"] * 100,
                "iterations": 1,
                "total_cost_usd": intent.get("cost", 0) + reply_data.get("cost", 0),
                "debate_history": [
                    {
                        "role": "generator",
                        "model": "intent-scorer",
                        "content": f"Intent score: {intent['score']:.2f}. Reasoning: {intent['reasoning']}",
                        "confidence_score": intent["score"] * 100,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                    {
                        "role": "generator",
                        "model": reply_data.get("model", "unknown"),
                        "content": f"Drafted contextual reply for r/{post['subreddit']}",
                        "confidence_score": reply_data.get("confidence", 0),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                ],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "context": {
                    "id": post["id"],
                    "subreddit": post["subreddit"],
                    "title": post["title"],
                    "body": post["body"][:500],
                    "author": post["author"],
                    "url": post["url"],
                    "intent_score": intent["score"],
                    "intent_reasoning": intent["reasoning"],
                    "workflow": "reddit_prospector",
                },
            }
            tasks_store[task_id] = task
            leads_found += 1

        # 8. Summary
        summary = (
            f"Scanned {total_scanned} posts across {len(SUBREDDITS)} subreddits.\n"
            f"After filters: {total_filtered} candidates.\n"
            f"Qualifying leads: {leads_found}.\n"
            f"All drafts staged in Dashboard for review."
        )
        await notify_workflow_complete("Reddit Lead Prospector", summary)

        return {
            "status": "complete",
            "total_scanned": total_scanned,
            "total_filtered": total_filtered,
            "leads_found": leads_found,
        }

    except Exception as e:
        await notify_workflow_error("Reddit Lead Prospector", str(e))
        return {"status": "error", "error": str(e)}


async def _score_intent(post: Dict[str, Any]) -> dict:
    """
    Use a cheap LLM to score whether this post is a genuine lead.
    Most posts should be rejected here to save costs on the expensive reply drafting.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are an intent classifier for a lead prospecting system.\n\n"
                "Your job: determine if the Reddit post is from someone who has a REAL problem "
                "that could be solved by AI automation, content creation, or marketing tools.\n\n"
                "Score 0.0 to 1.0:\n"
                "- 0.0-0.3: Not a lead (meme, rant, hiring post, unrelated)\n"
                "- 0.4-0.6: Maybe a lead (vaguely related but not asking for help)\n"
                "- 0.7-1.0: Strong lead (actively asking for a solution we provide)\n\n"
                "Respond in this exact format:\n"
                "SCORE: X.X\n"
                "REASONING: one sentence explaining why"
            ),
        },
        {
            "role": "user",
            "content": f"SUBREDDIT: r/{post['subreddit']}\nTITLE: {post['title']}\nBODY: {post['body'][:500]}",
        },
    ]

    result = await call_llm(messages=messages, tier="cheap", temperature=0.2, max_tokens=200)

    # Parse score
    score = 0.0
    reasoning = "Could not parse"
    
    score_match = re.search(r"SCORE:\s*([\d.]+)", result["content"])
    if score_match:
        score = float(score_match.group(1))
    
    reason_match = re.search(r"REASONING:\s*(.+)", result["content"])
    if reason_match:
        reasoning = reason_match.group(1).strip()

    return {"score": min(max(score, 0), 1), "reasoning": reasoning, "cost": result["cost_usd"]}


async def _draft_reply(post: Dict[str, Any]) -> dict:
    """
    Draft a contextual reply that answers the question FIRST,
    then subtly positions our solution. Never salesy.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are drafting a Reddit reply for a lead prospecting system.\n\n"
                "CRITICAL RULES:\n"
                "- Answer the person's question or problem FIRST with genuine help.\n"
                "- Only AFTER helping, you can subtly mention your experience or tool.\n"
                "- Sound like a real Redditor, not a marketer.\n"
                "- Never use corporate language, buzzwords, or hard sells.\n"
                "- Keep it under 200 words.\n"
                "- Match the subreddit's culture and tone.\n"
                "- If you can't genuinely help, say so — don't force a pitch.\n\n"
                "At the end, on a new line:\nCONFIDENCE: X/100"
            ),
        },
        {
            "role": "user",
            "content": (
                f"SUBREDDIT: r/{post['subreddit']}\n"
                f"POST TITLE: {post['title']}\n"
                f"POST BODY: {post['body'][:800]}\n\n"
                "Draft a helpful reply:"
            ),
        },
    ]

    result = await call_llm(messages=messages, tier="fast", temperature=0.7)

    confidence = 70.0
    match = re.search(r"CONFIDENCE:\s*(\d+(?:\.\d+)?)", result["content"], re.IGNORECASE)
    if match:
        confidence = float(match.group(1))

    reply = re.sub(r"\nCONFIDENCE:\s*\d+(?:\.\d+)?/?\d*\s*$", "", result["content"]).strip()

    return {
        "reply": reply,
        "confidence": min(max(confidence, 0), 100),
        "model": result["model"],
        "cost": result["cost_usd"],
    }
