"""Reddit lead prospecting that always ends in manual posting."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import MutableMapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.core.dedup import is_seen, mark_seen
from src.core.llm_router import call_llm_structured, get_council_model
from src.core.workflow_contracts import (
    PublicationPolicy,
    TaskSink,
    WorkflowRunResult,
    WorkflowTask,
    WorkflowTaskStatus,
    has_external_item,
    record_external_item,
    stage_workflow_task,
    workflow_execution_blocked,
    workflow_kill_switch_active,
)
from src.councils import create_council
from src.integrations.reddit import fetch_prospect_leads
from src.workflows.config.reddit_config import (
    EXCLUSION_TERMS,
    INTENT_SCORE_THRESHOLD,
    MAX_LEADS_PER_RUN,
    MAX_POSTS_PER_SUBREDDIT,
    SUBREDDITS,
)


class RedditIntentAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float = Field(ge=0, le=1)
    reasoning: str = Field(min_length=1)
    buying_signals: list[str]


async def _already_staged(sink: TaskSink, post_id: str) -> bool:
    if await has_external_item(sink, "reddit", post_id):
        return True
    # Legacy mapping deployments retain restart dedupe. Durable repositories
    # enforce the same key atomically and do not touch this SQLite adapter.
    return isinstance(sink, MutableMapping) and is_seen(post_id, source="reddit")


async def _score_intent(post: dict[str, Any]) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": (
                "Act as the Sales Council's lead-intent classifier. Determine whether the author "
                "has a real, current problem addressable by AI automation, content operations, or "
                "marketing workflow services. Hiring posts, memes, promotions, and general discussion "
                "are not leads. Return the required structured assessment and do not invent signals."
            ),
        },
        {
            "role": "user",
            "content": (
                f"SUBREDDIT: r/{post['subreddit']}\n"
                f"TITLE: {post['title']}\nBODY: {post['body'][:1200]}"
            ),
        },
    ]
    assessment, metrics = await call_llm_structured(
        messages=messages,
        model_id=get_council_model("sales", "generator"),
        output_model=RedditIntentAssessment,
        temperature=0.1,
        max_tokens=500,
    )
    return {**assessment.model_dump(mode="json"), **metrics, "prompt_messages": messages}


async def _draft_reply(post: dict[str, Any], custom_prompt: str = "") -> dict[str, Any]:
    result = await create_council("sales").run(
        (
            "Draft a helpful Reddit reply to this post. Answer the person's problem first. "
            "Do not auto-post, hard-sell, or pretend to have facts not supplied."
            + (f"\n\nAdministrator guidance:\n{custom_prompt}" if custom_prompt.strip() else "")
        ),
        context={
            "channel": "reddit",
            "subreddit": post["subreddit"],
            "post_title": post["title"],
            "post_body": post["body"][:1600],
            "post_author": post.get("author", ""),
        },
    )
    return {
        "reply": result.final_output,
        "confidence": result.confidence_score,
        "cost": result.total_cost_usd,
        "cost_metrics_complete": result.cost_metrics_complete,
        "iterations": result.draft_count,
        "debate_history": result.debate_history,
        "structured_output": result.structured_output,
        "status": result.status.value,
        "warnings": result.warnings,
    }


async def run_reddit_prospector(
    tasks_store: TaskSink, custom_prompt: str = ""
) -> dict[str, Any]:
    """Scan, assess, debate, and stage; never publish a Reddit reply."""
    from src.integrations.telegram_bot import (
        notify_workflow_complete,
        notify_workflow_error,
        notify_workflow_start,
    )

    workflow_name = "reddit_prospector"
    if await workflow_kill_switch_active(tasks_store):
        return WorkflowRunResult(workflow=workflow_name, status="killed").model_dump(mode="json")

    await notify_workflow_start(
        "Reddit Lead Prospector",
        f"Scanning {len(SUBREDDITS)} subreddits; manual posting is enforced.",
    )
    task_ids: list[str] = []
    skipped = 0
    failed = 0
    item_errors: list[str] = []
    try:
        posts = await asyncio.to_thread(
            fetch_prospect_leads, SUBREDDITS, MAX_POSTS_PER_SUBREDDIT
        )
        for post in posts:
            if await workflow_execution_blocked(tasks_store, workflow_name) or len(task_ids) >= MAX_LEADS_PER_RUN:
                break
            text = f"{post['title']} {post['body']}".lower()
            if any(term.lower() in text for term in EXCLUSION_TERMS):
                skipped += 1
                await record_external_item(
                    tasks_store,
                    "reddit",
                    post["id"],
                    {"outcome": "excluded", "subreddit": post["subreddit"]},
                )
                if isinstance(tasks_store, MutableMapping):
                    mark_seen(post["id"], source="reddit", metadata="excluded")
                continue
            if await _already_staged(tasks_store, post["id"]):
                skipped += 1
                continue

            try:
                if await workflow_execution_blocked(tasks_store, workflow_name):
                    break
                intent = await _score_intent(post)
                if intent["score"] < INTENT_SCORE_THRESHOLD:
                    skipped += 1
                    # A durable repository may record discarded source items in
                    # its own ingestion table. The legacy adapter records them here.
                    if isinstance(tasks_store, MutableMapping):
                        mark_seen(post["id"], source="reddit", metadata=post["subreddit"])
                    else:
                        await record_external_item(
                            tasks_store,
                            "reddit",
                            post["id"],
                            {
                                "outcome": "below_intent_threshold",
                                "subreddit": post["subreddit"],
                                "intent_score": intent["score"],
                            },
                        )
                    continue

                if await workflow_execution_blocked(tasks_store, workflow_name):
                    break
                reply = await _draft_reply(post, custom_prompt)
                task_id = f"rd-{uuid.uuid4().hex[:8]}"
                intent_cost = intent.get("cost_usd")
                cost_complete = intent_cost is not None and reply["cost_metrics_complete"]
                history = [
                    {
                        "role": "generator",
                        "model_used": intent["model"],
                        "content": intent["reasoning"],
                        "confidence_score": intent["score"] * 100,
                        "cost_usd": intent_cost,
                        "cost_source": intent.get("cost_source", "unavailable"),
                        "input_tokens": intent.get("input_tokens", 0),
                        "output_tokens": intent.get("output_tokens", 0),
                        "provider_request_id": intent.get("provider_request_id"),
                        "prompt_messages": intent["prompt_messages"],
                        "structured_output": {
                            "score": intent["score"],
                            "reasoning": intent["reasoning"],
                            "buying_signals": intent["buying_signals"],
                        },
                    },
                    *reply["debate_history"],
                ]
                status = WorkflowTaskStatus(reply["status"])
                task = WorkflowTask(
                    task_id=task_id,
                    workflow=workflow_name,
                    source="reddit",
                    external_id=post["id"],
                    council="sales",
                    status=status,
                    task_description=f"Reddit lead from r/{post['subreddit']}: {post['title'][:120]}",
                    final_output=reply["reply"],
                    structured_output=reply["structured_output"],
                    confidence_score=reply["confidence"],
                    iterations=reply["iterations"],
                    total_cost_usd=(intent_cost or 0.0) + reply["cost"],
                    cost_metrics_complete=cost_complete,
                    debate_history=history,
                    publication_policy=PublicationPolicy.MANUAL_ONLY,
                    context={
                        "subreddit": post["subreddit"],
                        "title": post["title"],
                        "body": post["body"][:1000],
                        "author": post.get("author", ""),
                        "url": post["url"],
                        "intent_score": intent["score"],
                        "intent_reasoning": intent["reasoning"],
                        "manual_posting_required": True,
                        "warnings": reply["warnings"],
                    },
                )
                await stage_workflow_task(tasks_store, task)
                if isinstance(tasks_store, MutableMapping):
                    mark_seen(post["id"], source="reddit", metadata=post["subreddit"])
                task_ids.append(task_id)
            except Exception as exc:
                failed += 1
                item_errors.append(f"{type(exc).__name__}: {str(exc)[:300]}")

        if failed > 0 and not task_ids:
            error = (
                f"All {failed} eligible Reddit prospect operations failed; "
                "no manual-only drafts were staged."
            )
            if item_errors:
                error += f" Last failure: {item_errors[-1]}"
            await notify_workflow_error("Reddit Lead Prospector", error)
            return WorkflowRunResult(
                workflow=workflow_name,
                status="error",
                scanned=len(posts),
                staged=0,
                skipped=skipped,
                failed=failed,
                task_ids=[],
                error=error,
            ).model_dump(mode="json")

        await notify_workflow_complete(
            "Reddit Lead Prospector",
            f"Scanned {len(posts)} posts; staged {len(task_ids)} manual-only drafts.",
        )
        return WorkflowRunResult(
            workflow=workflow_name,
            status="complete",
            scanned=len(posts),
            staged=len(task_ids),
            skipped=skipped,
            failed=failed,
            task_ids=task_ids,
        ).model_dump(mode="json")
    except Exception as exc:
        await notify_workflow_error("Reddit Lead Prospector", str(exc))
        return WorkflowRunResult(
            workflow=workflow_name,
            status="error",
            staged=len(task_ids),
            skipped=skipped,
            failed=failed + 1,
            task_ids=task_ids,
            error=str(exc),
        ).model_dump(mode="json")
