"""Two-phase YouTube description workflow: stage first, publish after approval."""

from __future__ import annotations

import asyncio
import os
from src.core.integration_context import integration_value
import uuid
from collections.abc import MutableMapping
from typing import Any
from urllib.parse import urlparse

import httpx

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
from src.integrations.youtube import fetch_channel_videos, update_video_description

BOILERPLATE_SOURCE_URL = os.getenv("BOILERPLATE_SOURCE_URL", "").strip()
BATCH_SIZE = int(os.getenv("YT_DESC_BATCH_SIZE", "20"))


async def _already_staged(sink: TaskSink, video_id: str) -> bool:
    if await has_external_item(sink, "youtube_description", video_id):
        return True
    return isinstance(sink, MutableMapping) and is_seen(
        video_id, source="youtube_description"
    )


async def _rewrite_description(
    video_title: str,
    current_description: str,
    boilerplate: str,
    custom_prompt: str = "",
) -> dict[str, Any]:
    result = await create_council("content").run(
        "Update this YouTube description while preserving its video-specific opening."
        + (f"\n\nAdministrator guidance:\n{custom_prompt}" if custom_prompt.strip() else ""),
        context={
            "platform": "youtube_description",
            "video_title": video_title,
            "current_description": current_description,
            "new_boilerplate": boilerplate,
        },
    )
    return {
        "description": result.final_output,
        "confidence": result.confidence_score,
        "cost": result.total_cost_usd,
        "cost_metrics_complete": result.cost_metrics_complete,
        "iterations": result.draft_count,
        "debate_history": result.debate_history,
        "structured_output": result.structured_output,
        "status": result.status.value,
        "warnings": result.warnings,
    }


async def _load_boilerplate(provided: str) -> str:
    if provided.strip():
        return provided.strip()
    if not BOILERPLATE_SOURCE_URL:
        raise ValueError("No boilerplate text or BOILERPLATE_SOURCE_URL was provided.")
    parsed = urlparse(BOILERPLATE_SOURCE_URL)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("BOILERPLATE_SOURCE_URL must be an absolute HTTPS URL.")
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        response = await client.get(BOILERPLATE_SOURCE_URL)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if content_type and not content_type.lower().startswith("text/"):
            raise ValueError("The boilerplate source must return text content.")
        if len(response.content) > 500_000:
            raise ValueError("The boilerplate source exceeds the 500 KB limit.")
        text = response.text.strip()
    if not text:
        raise ValueError("The configured boilerplate source returned empty content.")
    return text


async def run_description_generator(
    tasks_store: TaskSink, boilerplate: str = "", custom_prompt: str = ""
) -> dict[str, Any]:
    from src.integrations.telegram_bot import (
        notify_workflow_complete,
        notify_workflow_error,
        notify_workflow_start,
    )

    workflow_name = "youtube_descriptions"
    if await workflow_kill_switch_active(tasks_store):
        return WorkflowRunResult(workflow=workflow_name, status="killed").model_dump(mode="json")

    channel_id = integration_value("YOUTUBE_CHANNEL_ID", "").strip()
    if not channel_id:
        error = "YOUTUBE_CHANNEL_ID is not configured."
        await notify_workflow_error("YouTube Description Updater", error)
        return WorkflowRunResult(workflow=workflow_name, status="error", error=error).model_dump(
            mode="json"
        )

    task_ids: list[str] = []
    skipped = 0
    failed = 0
    item_errors: list[str] = []
    try:
        source_boilerplate = await _load_boilerplate(boilerplate)
        await notify_workflow_start(
            "YouTube Description Updater (stage)", f"Batch size: {BATCH_SIZE}"
        )
        videos = await asyncio.to_thread(fetch_channel_videos, channel_id, BATCH_SIZE)
        for video in videos:
            if await workflow_execution_blocked(tasks_store, workflow_name):
                break
            if await _already_staged(tasks_store, video["video_id"]):
                skipped += 1
                continue
            try:
                if await workflow_execution_blocked(tasks_store, workflow_name):
                    break
                updated = await _rewrite_description(
                    video["title"], video.get("description", ""), source_boilerplate,
                    custom_prompt,
                )
                task_id = f"desc-{uuid.uuid4().hex[:8]}"
                task = WorkflowTask(
                    task_id=task_id,
                    workflow=workflow_name,
                    source="youtube_description",
                    external_id=video["video_id"],
                    council="content",
                    status=WorkflowTaskStatus(updated["status"]),
                    task_description=f"Description update for: {video['title'][:100]}",
                    final_output=updated["description"],
                    structured_output=updated["structured_output"],
                    confidence_score=updated["confidence"],
                    iterations=updated["iterations"],
                    total_cost_usd=updated["cost"],
                    cost_metrics_complete=updated["cost_metrics_complete"],
                    debate_history=updated["debate_history"],
                    publication_policy=PublicationPolicy.APPROVAL_REQUIRED,
                    context={
                        "video_id": video["video_id"],
                        "video_title": video["title"],
                        "old_description": video.get("description", ""),
                        "publish_action": "youtube_description_update",
                        "publication_key": f"youtube-description:{video['video_id']}",
                        "warnings": updated["warnings"],
                    },
                )
                await stage_workflow_task(tasks_store, task)
                if isinstance(tasks_store, MutableMapping):
                    mark_seen(
                        video["video_id"],
                        source="youtube_description",
                        metadata=video["title"],
                    )
                task_ids.append(task_id)
            except Exception as exc:
                failed += 1
                item_errors.append(f"{type(exc).__name__}: {str(exc)[:300]}")

        if failed > 0 and not task_ids:
            error = (
                f"All {failed} eligible YouTube description operations failed; "
                "no descriptions were staged for approval."
            )
            if item_errors:
                error += f" Last failure: {item_errors[-1]}"
            await notify_workflow_error("YouTube Description Updater", error)
            return WorkflowRunResult(
                workflow=workflow_name,
                status="error",
                scanned=len(videos),
                staged=0,
                skipped=skipped,
                failed=failed,
                task_ids=[],
                error=error,
            ).model_dump(mode="json")

        await notify_workflow_complete(
            "YouTube Description Updater (stage)",
            f"Staged {len(task_ids)} of {len(videos)} descriptions for approval.",
        )
        return WorkflowRunResult(
            workflow=workflow_name,
            status="complete",
            scanned=len(videos),
            staged=len(task_ids),
            skipped=skipped,
            failed=failed,
            task_ids=task_ids,
        ).model_dump(mode="json")
    except Exception as exc:
        await notify_workflow_error("YouTube Description Updater", str(exc))
        return WorkflowRunResult(
            workflow=workflow_name,
            status="error",
            staged=len(task_ids),
            skipped=skipped,
            failed=failed + 1,
            task_ids=task_ids,
            error=str(exc),
        ).model_dump(mode="json")


async def publish_approved_descriptions(tasks_store: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Legacy adapter for the explicit, manually-triggered publication phase.

    Production workers should claim approved publication attempts from the
    database using ``context.publication_key`` as their idempotency key.
    """
    from src.integrations.telegram_bot import notify_workflow_complete

    if await workflow_kill_switch_active(tasks_store):
        return {"status": "killed", "published": 0, "failed": 0}

    published = 0
    failed = 0
    for task in tasks_store.values():
        if await workflow_kill_switch_active(tasks_store):
            break
        context = task.get("context") or {}
        if context.get("workflow") != "youtube_descriptions":
            continue
        if task.get("status") != WorkflowTaskStatus.APPROVED.value:
            continue
        if task.get("publication_policy") != PublicationPolicy.APPROVAL_REQUIRED.value:
            continue
        if context.get("published_result_id"):
            continue

        task["status"] = WorkflowTaskStatus.PUBLISHING.value
        result = update_video_description(context["video_id"], task["final_output"])
        if result:
            context["published_result_id"] = result.get("id", context["video_id"])
            task["context"] = context
            task["status"] = WorkflowTaskStatus.PUBLISHED.value
            task["version"] = int(task.get("version", 1)) + 1
            published += 1
        else:
            task["status"] = WorkflowTaskStatus.FAILED.value
            failed += 1

    await notify_workflow_complete(
        "YouTube Description Updater (publish)",
        f"Published {published}; failed {failed}.",
    )
    return {"status": "complete", "published": published, "failed": failed}
