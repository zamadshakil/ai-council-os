"""YouTube comment reply producer; publication is a separate approved action."""

from __future__ import annotations

import asyncio
import os
from src.core.integration_context import integration_value
import uuid
from collections.abc import MutableMapping
from typing import Any

from src.core.dedup import is_seen, mark_seen
from src.core.workflow_contracts import (
    PublicationPolicy,
    TaskSink,
    WorkflowRunResult,
    WorkflowTask,
    WorkflowTaskStatus,
    has_external_item,
    stage_workflow_task,
    workflow_execution_blocked,
    workflow_kill_switch_active,
)
from src.councils import create_council
from src.integrations.youtube import fetch_channel_videos, fetch_recent_comments

MAX_REPLIES_PER_RUN = int(os.getenv("YT_MAX_REPLIES_PER_RUN", "50"))


async def _already_staged(sink: TaskSink, comment_id: str) -> bool:
    if await has_external_item(sink, "youtube_comment", comment_id):
        return True
    return isinstance(sink, MutableMapping) and is_seen(
        comment_id, source="youtube_comment"
    )


async def _generate_reply(
    video_title: str, comment_text: str, comment_author: str, custom_prompt: str = ""
) -> dict[str, Any]:
    """Generate and critique a reply with the Content Council profile."""
    result = await create_council("content").run(
        "Write a natural, specific reply to the supplied YouTube comment."
        + (f"\n\nAdministrator guidance:\n{custom_prompt}" if custom_prompt.strip() else ""),
        context={
            "platform": "youtube_comment",
            "video_title": video_title,
            "comment_text": comment_text,
            "comment_author": comment_author,
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


async def run_youtube_comment_workflow(
    tasks_store: TaskSink, custom_prompt: str = ""
) -> dict[str, Any]:
    from src.integrations.telegram_bot import (
        notify_workflow_complete,
        notify_workflow_error,
        notify_workflow_start,
    )

    workflow_name = "youtube_comments"
    if await workflow_kill_switch_active(tasks_store):
        return WorkflowRunResult(workflow=workflow_name, status="killed").model_dump(mode="json")

    channel_id = integration_value("YOUTUBE_CHANNEL_ID", "").strip()
    if not channel_id:
        error = "YOUTUBE_CHANNEL_ID is not configured."
        await notify_workflow_error("YouTube Comment Replies", error)
        return WorkflowRunResult(workflow=workflow_name, status="error", error=error).model_dump(
            mode="json"
        )

    await notify_workflow_start(
        "YouTube Comment Replies",
        f"At most {MAX_REPLIES_PER_RUN} replies will be staged for approval.",
    )
    task_ids: list[str] = []
    skipped = 0
    failed = 0
    scanned = 0
    item_errors: list[str] = []
    try:
        videos = await asyncio.to_thread(fetch_channel_videos, channel_id, 50)
        for video in videos:
            if await workflow_execution_blocked(tasks_store, workflow_name) or len(task_ids) >= MAX_REPLIES_PER_RUN:
                break
            comments = await asyncio.to_thread(fetch_recent_comments, video["video_id"], 30)
            for comment in comments:
                if await workflow_execution_blocked(tasks_store, workflow_name) or len(task_ids) >= MAX_REPLIES_PER_RUN:
                    break
                scanned += 1
                comment_id = comment["comment_id"]
                if await _already_staged(tasks_store, comment_id):
                    skipped += 1
                    continue
                try:
                    if await workflow_execution_blocked(tasks_store, workflow_name):
                        break
                    reply = await _generate_reply(
                        video["title"], comment["text"], comment["author"], custom_prompt
                    )
                    task_id = f"yt-{uuid.uuid4().hex[:8]}"
                    task = WorkflowTask(
                        task_id=task_id,
                        workflow=workflow_name,
                        source="youtube_comment",
                        external_id=comment_id,
                        council="content",
                        status=WorkflowTaskStatus(reply["status"]),
                        task_description=(
                            f"Reply to comment on '{video['title']}' by {comment['author']}"
                        ),
                        final_output=reply["reply"],
                        structured_output=reply["structured_output"],
                        confidence_score=reply["confidence"],
                        iterations=reply["iterations"],
                        total_cost_usd=reply["cost"],
                        cost_metrics_complete=reply["cost_metrics_complete"],
                        debate_history=reply["debate_history"],
                        publication_policy=PublicationPolicy.APPROVAL_REQUIRED,
                        context={
                            "comment_id": comment_id,
                            "video_id": video["video_id"],
                            "video_title": video["title"],
                            "original_comment": comment["text"],
                            "comment_author": comment["author"],
                            "publish_action": "youtube_comment_reply",
                            "warnings": reply["warnings"],
                        },
                    )
                    await stage_workflow_task(tasks_store, task)
                    if isinstance(tasks_store, MutableMapping):
                        mark_seen(comment_id, source="youtube_comment", metadata=video["title"])
                    task_ids.append(task_id)
                except Exception as exc:
                    failed += 1
                    item_errors.append(f"{type(exc).__name__}: {str(exc)[:300]}")

        if failed > 0 and not task_ids:
            error = (
                f"All {failed} eligible YouTube comment reply operations failed; "
                "no replies were staged for approval."
            )
            if item_errors:
                error += f" Last failure: {item_errors[-1]}"
            await notify_workflow_error("YouTube Comment Replies", error)
            return WorkflowRunResult(
                workflow=workflow_name,
                status="error",
                scanned=scanned,
                staged=0,
                skipped=skipped,
                failed=failed,
                task_ids=[],
                error=error,
            ).model_dump(mode="json")

        await notify_workflow_complete(
            "YouTube Comment Replies",
            f"Scanned {scanned} comments; staged {len(task_ids)} for approval.",
        )
        return WorkflowRunResult(
            workflow=workflow_name,
            status="complete",
            scanned=scanned,
            staged=len(task_ids),
            skipped=skipped,
            failed=failed,
            task_ids=task_ids,
        ).model_dump(mode="json")
    except Exception as exc:
        await notify_workflow_error("YouTube Comment Replies", str(exc))
        return WorkflowRunResult(
            workflow=workflow_name,
            status="error",
            scanned=scanned,
            staged=len(task_ids),
            skipped=skipped,
            failed=failed + 1,
            task_ids=task_ids,
            error=str(exc),
        ).model_dump(mode="json")
