"""Instagram comment discovery with Content Council drafts and approval gating."""

from __future__ import annotations

import uuid
from typing import Any

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
from src.integrations.instagram_comments import fetch_comment_candidates


MAX_REPLIES_PER_RUN = 20


async def _draft(candidate: dict[str, str], custom_prompt: str) -> dict[str, Any]:
    result = await create_council("content").run(
        "Write a helpful, specific public reply to this Instagram comment. "
        "Do not invent facts, do not ask for private information, and keep it concise."
        + (f"\n\nAdministrator guidance:\n{custom_prompt}" if custom_prompt.strip() else ""),
        context={
            "platform": "instagram_comment",
            "post_caption": candidate.get("caption", "")[:1200],
            "comment_text": candidate["comment_text"],
            "comment_author": candidate["username"],
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


async def run_instagram_comment_workflow(
    tasks_store: TaskSink,
    *,
    custom_prompt: str = "",
    webhook_comments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from src.integrations.telegram_bot import (
        notify_workflow_complete,
        notify_workflow_error,
        notify_workflow_start,
    )

    workflow = "instagram_comments"
    if await workflow_kill_switch_active(tasks_store):
        return WorkflowRunResult(workflow=workflow, status="killed").model_dump(mode="json")
    await notify_workflow_start(
        "Instagram Comment Replies",
        "New comments will be drafted and held for approval; nothing is posted automatically.",
    )
    try:
        candidates = [
            {
                "comment_id": str(item.get("comment_id", "")),
                "comment_text": str(item.get("comment_text", "")),
                "username": str(item.get("username", "instagram_user")),
                "media_id": str(item.get("media_id", "")),
                "caption": str(item.get("caption", "")),
                "timestamp": str(item.get("timestamp", "")),
            }
            for item in (webhook_comments or [])
            if isinstance(item, dict)
        ] or await fetch_comment_candidates()
    except Exception as exc:
        await notify_workflow_error("Instagram Comment Replies", str(exc))
        return WorkflowRunResult(workflow=workflow, status="error", failed=1, error=str(exc)).model_dump(mode="json")

    task_ids: list[str] = []
    skipped = 0
    failed = 0
    errors: list[str] = []
    for candidate in candidates[:MAX_REPLIES_PER_RUN]:
        if await workflow_execution_blocked(tasks_store, workflow):
            break
        comment_id = candidate["comment_id"].strip()
        if not comment_id or not candidate["comment_text"].strip():
            skipped += 1
            continue
        if await has_external_item(tasks_store, "instagram_comment", comment_id):
            skipped += 1
            continue
        try:
            draft = await _draft(candidate, custom_prompt)
            task_id = f"ig-{uuid.uuid4().hex[:10]}"
            await stage_workflow_task(tasks_store, WorkflowTask(
                task_id=task_id,
                workflow=workflow,
                source="instagram_comment",
                external_id=comment_id,
                council="content",
                status=WorkflowTaskStatus(draft["status"]),
                task_description=f"Reply to @{candidate['username']}: {candidate['comment_text'][:240]}",
                final_output=draft["reply"],
                structured_output=draft["structured_output"],
                confidence_score=draft["confidence"],
                iterations=draft["iterations"],
                total_cost_usd=draft["cost"],
                cost_metrics_complete=draft["cost_metrics_complete"],
                debate_history=draft["debate_history"],
                publication_policy=PublicationPolicy.APPROVAL_REQUIRED,
                context={
                    "comment_id": comment_id,
                    "media_id": candidate["media_id"],
                    "original_comment": candidate["comment_text"],
                    "comment_author": candidate["username"],
                    "post_caption": candidate["caption"],
                    "publish_action": "instagram_comment_reply",
                    "warnings": draft["warnings"],
                },
            ))
            task_ids.append(task_id)
        except Exception as exc:
            failed += 1
            errors.append(f"{type(exc).__name__}: {str(exc)[:300]}")

    if failed and not task_ids:
        error = f"No Instagram replies were staged. Last error: {errors[-1]}"
        await notify_workflow_error("Instagram Comment Replies", error)
        return WorkflowRunResult(
            workflow=workflow, status="error", scanned=len(candidates), skipped=skipped,
            failed=failed, error=error,
        ).model_dump(mode="json")
    await notify_workflow_complete(
        "Instagram Comment Replies",
        f"Scanned {len(candidates)} comments; staged {len(task_ids)} for approval.",
    )
    return WorkflowRunResult(
        workflow=workflow, status="complete", scanned=len(candidates), staged=len(task_ids),
        skipped=skipped, failed=failed, task_ids=task_ids,
    ).model_dump(mode="json")
