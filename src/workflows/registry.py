"""Stable workflow job registry for the durable worker."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from src.core.workflow_contracts import TaskSink
WorkflowJobHandler = Callable[[dict[str, Any], TaskSink], Awaitable[dict[str, Any]]]


class WorkflowJobFailed(RuntimeError):
    """Signals the durable worker to retry/dead-letter a failed handler."""


async def _telegram_control_handler(
    payload: dict[str, Any], task_sink: TaskSink
) -> dict[str, Any]:
    # Telegram is a continuously running authenticated control interface, not a
    # scheduled producer. Keeping it in the registry makes that distinction
    # explicit and prevents a scheduler from trying to enqueue a fake run.
    return {
        "workflow": "telegram_control",
        "status": "service_managed",
        "scanned": 0,
        "staged": 0,
        "skipped": 0,
        "failed": 0,
        "task_ids": [],
    }


async def _youtube_comments_handler(
    payload: dict[str, Any], task_sink: TaskSink
) -> dict[str, Any]:
    from src.workflows.youtube_comments import run_youtube_comment_workflow

    return await run_youtube_comment_workflow(
        task_sink, custom_prompt=str(payload.get("custom_prompt", ""))
    )


async def _reddit_handler(
    payload: dict[str, Any], task_sink: TaskSink
) -> dict[str, Any]:
    from src.workflows.reddit_prospector import run_reddit_prospector

    return await run_reddit_prospector(
        task_sink, custom_prompt=str(payload.get("custom_prompt", ""))
    )


async def _youtube_descriptions_handler(
    payload: dict[str, Any], task_sink: TaskSink
) -> dict[str, Any]:
    from src.workflows.youtube_descriptions import run_description_generator

    return await run_description_generator(
        task_sink,
        boilerplate=str(payload.get("boilerplate", "")),
        custom_prompt=str(payload.get("custom_prompt", "")),
    )


async def _content_engine_handler(
    payload: dict[str, Any], task_sink: TaskSink
) -> dict[str, Any]:
    from src.workflows.content_engine import run_content_engine

    return await run_content_engine(
        video_title=str(payload.get("video_title", "")),
        transcript=str(payload.get("transcript", "")),
        video_id=str(payload.get("video_id", "")),
        tasks_store=task_sink,
        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
        custom_prompt=str(payload.get("custom_prompt", "")),
    )


async def _instagram_comments_handler(
    payload: dict[str, Any], task_sink: TaskSink
) -> dict[str, Any]:
    from src.workflows.instagram_comments import run_instagram_comment_workflow

    raw_comments = payload.get("webhook_comments")
    return await run_instagram_comment_workflow(
        task_sink,
        custom_prompt=str(payload.get("custom_prompt", "")),
        webhook_comments=raw_comments if isinstance(raw_comments, list) else None,
    )


WORKFLOW_JOB_HANDLERS: dict[str, WorkflowJobHandler] = {
    "telegram_control": _telegram_control_handler,
    "youtube_comments": _youtube_comments_handler,
    "reddit_prospector": _reddit_handler,
    "youtube_descriptions": _youtube_descriptions_handler,
    "content_engine": _content_engine_handler,
    "instagram_comments": _instagram_comments_handler,
}

PRODUCTION_WORKFLOWS = tuple(WORKFLOW_JOB_HANDLERS)


def get_workflow_job_handler(name: str) -> WorkflowJobHandler:
    try:
        return WORKFLOW_JOB_HANDLERS[name.strip().lower()]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported workflow {name!r}; allowed workflows are {', '.join(PRODUCTION_WORKFLOWS)}."
        ) from exc


async def run_workflow_job(
    name: str,
    payload: dict[str, Any],
    task_sink: TaskSink,
) -> dict[str, Any]:
    result = await get_workflow_job_handler(name)(payload, task_sink)
    if result.get("status") == "error":
        raise WorkflowJobFailed(str(result.get("error") or f"{name} failed"))
    return result
