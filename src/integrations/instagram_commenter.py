"""Backward-compatible entry points for the approval-gated Instagram workflow.

The former implementation generated and posted replies immediately while
tracking deduplication in a separate SQLite database. It is intentionally
retired: all callers now stage durable PostgreSQL tasks for human approval.
"""

from __future__ import annotations

from typing import Any

from src.workflows.instagram_comments import run_instagram_comment_workflow


async def run_instagram_commenter(tasks_store) -> dict[str, Any]:
    return await run_instagram_comment_workflow(tasks_store)


async def handle_instant_webhook_comment(
    comment_id: str,
    comment_text: str,
    username: str,
    media_id: str = "",
    *,
    tasks_store=None,
) -> dict[str, Any]:
    if tasks_store is None:
        from src.core.repositories import DurableTaskRepository

        tasks_store = DurableTaskRepository()
    return await run_instagram_comment_workflow(
        tasks_store,
        webhook_comments=[{
            "comment_id": comment_id,
            "comment_text": comment_text,
            "username": username,
            "media_id": media_id,
            "caption": "",
        }],
    )


def get_instagram_workflow_details() -> dict[str, Any]:
    return {
        "id": "instagram_comments",
        "name": "Instagram Comment Replies",
        "status": "database_managed",
        "publication_policy": "approval_required",
        "activity_source": "workflow_runs",
    }
