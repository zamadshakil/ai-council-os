"""Content Council workflow producing six separately approved destinations."""

from __future__ import annotations

import asyncio
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
from src.workflows.config.platform_specs import PLATFORM_SPECS


async def _run_content_council(
    video_title: str,
    transcript: str,
    metadata: dict[str, Any] | None,
    custom_prompt: str = "",
):
    if not transcript.strip():
        raise ValueError("A pasted transcript or available YouTube caption text is required.")
    if len(transcript) > 100_000:
        raise ValueError(
            "Transcript exceeds 100,000 characters; split it into reviewed source segments."
        )
    return await create_council("content").run(
        "Repurpose the supplied transcript into six genuinely platform-native variants."
        + (f"\n\nAdministrator guidance:\n{custom_prompt}" if custom_prompt.strip() else ""),
        context={
            "platform": "all",
            "video_title": video_title,
            "transcript": transcript,
            "metadata": metadata or {},
        },
    )


async def _generate_all_variants(
    video_title: str,
    transcript: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Compatibility helper returning the strictly validated six variants."""
    result = await _run_content_council(video_title, transcript, metadata)
    return {key: str(value) for key, value in result.structured_output.items()}


async def _run_platform_content_council(
    platform: str,
    video_title: str,
    transcript: str,
    metadata: dict[str, Any] | None,
    custom_prompt: str,
):
    """Generate and critique one destination with its own quality loop."""
    spec = PLATFORM_SPECS[platform]
    task = (
        f"Create the {spec['name']} variant for the source titled {video_title!r}. "
        "Use only claims supported by the supplied transcript and follow the platform contract."
    )
    if custom_prompt.strip():
        task += f"\n\nAdministrator guidance:\n{custom_prompt.strip()}"
    return await create_council("content").run(
        task,
        context={
            "platform": platform,
            "video_title": video_title,
            "transcript": transcript,
            "metadata": metadata or {},
        },
    )


async def run_content_engine(
    video_title: str,
    transcript: str,
    video_id: str,
    tasks_store: TaskSink,
    metadata: dict[str, Any] | None = None,
    custom_prompt: str = "",
) -> dict[str, Any]:
    from src.integrations.telegram_bot import (
        notify_workflow_complete,
        notify_workflow_error,
        notify_workflow_start,
    )

    workflow_name = "content_engine"
    if await workflow_kill_switch_active(tasks_store):
        return WorkflowRunResult(workflow=workflow_name, status="killed").model_dump(mode="json")
    if not video_id.strip():
        return WorkflowRunResult(
            workflow=workflow_name,
            status="error",
            error="video_id is required for durable deduplication.",
        ).model_dump(mode="json")

    notification_warnings: list[str] = []
    try:
        await notify_workflow_start(
            "Multi-Platform Content Engine",
            f"Source: {video_title}; six destinations will require approval.",
        )
    except Exception as exc:
        notification_warnings.append(
            f"Telegram start notification unavailable: {type(exc).__name__}"
        )
    task_ids: list[str] = []
    skipped = 0
    try:
        new_platforms = [
            platform
            for platform in PLATFORM_SPECS
            if not await has_external_item(
                tasks_store, "content_variant", f"{video_id}:{platform}"
            )
        ]
        skipped = len(PLATFORM_SPECS) - len(new_platforms)
        if not new_platforms:
            await notify_workflow_complete(
                "Multi-Platform Content Engine",
                "All six destination variants were already staged; no model call was made.",
            )
            return WorkflowRunResult(
                workflow=workflow_name,
                status="complete",
                scanned=len(PLATFORM_SPECS),
                staged=0,
                skipped=skipped,
            ).model_dump(mode="json")

        if await workflow_execution_blocked(tasks_store, workflow_name):
            return WorkflowRunResult(
                workflow=workflow_name,
                status="killed",
                scanned=len(PLATFORM_SPECS),
                skipped=skipped,
            ).model_dump(mode="json")
        semaphore = asyncio.Semaphore(2)

        async def generate(platform: str):
            async with semaphore:
                if await workflow_execution_blocked(tasks_store, workflow_name):
                    raise RuntimeError("Workflow was paused or killed during generation")
                return await _run_platform_content_council(
                    platform, video_title, transcript, metadata, custom_prompt
                )

        generated = await asyncio.gather(
            *(generate(platform) for platform in new_platforms),
            return_exceptions=True,
        )
        platform_results = dict(zip(new_platforms, generated))
        errors: dict[str, str] = {}
        for platform in new_platforms:
            if await workflow_execution_blocked(tasks_store, workflow_name):
                break
            result = platform_results[platform]
            if isinstance(result, BaseException):
                errors[platform] = f"{type(result).__name__}: {str(result)[:500]}"
                continue
            content = result.final_output.strip()
            spec = PLATFORM_SPECS[platform]
            # The Pydantic output model enforces these limits. Keep this explicit
            # guard to protect against future model/schema changes; never truncate.
            if not content or len(content) > spec["max_length"]:
                raise ValueError(
                    f"{platform} content violates its {spec['max_length']}-character contract."
                )
            task_id = f"ctn-{platform[:3]}-{uuid.uuid4().hex[:6]}"
            policy = (
                PublicationPolicy.MANUAL_ONLY
                if platform == "reddit"
                else PublicationPolicy.APPROVAL_REQUIRED
            )
            task = WorkflowTask(
                task_id=task_id,
                workflow=workflow_name,
                source="content_variant",
                external_id=f"{video_id}:{platform}",
                council="content",
                status=WorkflowTaskStatus(result.status.value),
                task_description=f"{spec['name']} post from '{video_title[:80]}'",
                final_output=content,
                structured_output={
                    "platform": platform,
                    "content": content,
                    "generator_output": result.structured_output,
                },
                confidence_score=result.confidence_score,
                iterations=result.draft_count,
                total_cost_usd=result.total_cost_usd,
                cost_metrics_complete=result.cost_metrics_complete,
                debate_history=result.debate_history,
                publication_policy=policy,
                context={
                    "video_id": video_id,
                    "video_title": video_title,
                    "platform": platform,
                    "platform_name": spec["name"],
                    "max_length": spec["max_length"],
                    "publish_action": (
                        "manual_copy" if policy == PublicationPolicy.MANUAL_ONLY else "platform_api"
                    ),
                    "manual_posting_required": policy == PublicationPolicy.MANUAL_ONLY,
                    "council_run_total_cost_usd": result.total_cost_usd,
                    "cost_allocation_fraction": 1,
                    "warnings": [*notification_warnings, *result.warnings],
                    "media_url": str((metadata or {}).get("media_url", "")).strip(),
                },
            )
            await stage_workflow_task(tasks_store, task)
            task_ids.append(task_id)

        try:
            await notify_workflow_complete(
                "Multi-Platform Content Engine",
                f"Staged {len(task_ids)} variants; every destination requires human approval.",
            )
        except Exception as exc:
            notification_warnings.append(
                f"Telegram completion notification unavailable: {type(exc).__name__}"
            )
        return WorkflowRunResult(
            workflow=workflow_name,
            status="error" if errors else "complete",
            scanned=len(PLATFORM_SPECS),
            staged=len(task_ids),
            skipped=skipped,
            failed=len(errors),
            task_ids=task_ids,
            error=(
                "; ".join(f"{platform}: {message}" for platform, message in errors.items())
                if errors else ""
            ),
        ).model_dump(mode="json")
    except Exception as exc:
        try:
            await notify_workflow_error("Multi-Platform Content Engine", str(exc))
        except Exception:
            pass
        return WorkflowRunResult(
            workflow=workflow_name,
            status="error",
            scanned=len(PLATFORM_SPECS),
            staged=len(task_ids),
            skipped=skipped,
            failed=1,
            task_ids=task_ids,
            error=str(exc),
        ).model_dump(mode="json")
