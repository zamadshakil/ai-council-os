from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.workflows import reddit_prospector, youtube_comments, youtube_descriptions
from src.workflows.registry import WorkflowJobFailed, run_workflow_job


class MemoryTaskSink:
    """Small repository-shaped sink that keeps workflow tests independent of local state."""

    def __init__(self) -> None:
        self.tasks: dict[str, object] = {}
        self.external_items: set[tuple[str, str]] = set()

    async def is_kill_switch_active(self) -> bool:
        return False

    async def is_workflow_blocked(self, workflow_id: str) -> bool:
        return False

    async def has_external_item(self, source: str, external_id: str) -> bool:
        return (source, external_id) in self.external_items

    async def record_external_item(
        self, source: str, external_id: str, metadata: dict
    ) -> bool:
        self.external_items.add((source, external_id))
        return True

    async def stage_workflow_task(self, task) -> None:
        self.tasks[task.task_id] = task
        self.external_items.add((task.source, task.external_id))


def _silence_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.integrations import telegram_bot

    monkeypatch.setattr(telegram_bot, "notify_workflow_start", AsyncMock())
    monkeypatch.setattr(telegram_bot, "notify_workflow_complete", AsyncMock())
    monkeypatch.setattr(telegram_bot, "notify_workflow_error", AsyncMock())


def _content_result(text: str) -> dict:
    return {
        "reply": text,
        "description": text,
        "confidence": 91.0,
        "cost": 0.01,
        "cost_metrics_complete": True,
        "iterations": 1,
        "debate_history": [],
        "structured_output": {"content": text},
        "status": "awaiting_approval",
        "warnings": [],
    }


@pytest.mark.asyncio
async def test_youtube_comments_all_item_failures_are_retry_visible(
    monkeypatch: pytest.MonkeyPatch,
):
    _silence_telegram(monkeypatch)
    monkeypatch.setenv("YOUTUBE_CHANNEL_ID", "channel-1")
    monkeypatch.setattr(
        youtube_comments,
        "fetch_channel_videos",
        lambda channel_id, max_results: [{"video_id": "video-1", "title": "Video"}],
    )
    monkeypatch.setattr(
        youtube_comments,
        "fetch_recent_comments",
        lambda video_id, max_results: [
            {"comment_id": "comment-1", "text": "First", "author": "A"},
            {"comment_id": "comment-2", "text": "Second", "author": "B"},
        ],
    )
    monkeypatch.setattr(
        youtube_comments,
        "_generate_reply",
        AsyncMock(side_effect=RuntimeError("temporary model failure")),
    )

    result = await youtube_comments.run_youtube_comment_workflow(MemoryTaskSink())

    assert result["status"] == "error"
    assert result["scanned"] == 2
    assert result["staged"] == 0
    assert result["failed"] == 2
    assert "no replies were staged" in result["error"]

    with pytest.raises(WorkflowJobFailed, match="no replies were staged"):
        await run_workflow_job("youtube_comments", {}, MemoryTaskSink())


@pytest.mark.asyncio
async def test_reddit_all_item_failures_are_retry_visible(
    monkeypatch: pytest.MonkeyPatch,
):
    _silence_telegram(monkeypatch)
    monkeypatch.setattr(
        reddit_prospector,
        "fetch_prospect_leads",
        lambda subreddits, max_posts: [
            {
                "id": "post-1",
                "subreddit": "automation",
                "title": "Need workflow help",
                "body": "I need a better process for recurring reports.",
                "author": "A",
                "url": "https://reddit.example/post-1",
            },
            {
                "id": "post-2",
                "subreddit": "smallbusiness",
                "title": "Manual reporting takes too long",
                "body": "How can I improve this repeated task?",
                "author": "B",
                "url": "https://reddit.example/post-2",
            },
        ],
    )
    monkeypatch.setattr(
        reddit_prospector,
        "_score_intent",
        AsyncMock(side_effect=RuntimeError("temporary classifier failure")),
    )

    result = await reddit_prospector.run_reddit_prospector(MemoryTaskSink())

    assert result["status"] == "error"
    assert result["scanned"] == 2
    assert result["staged"] == 0
    assert result["failed"] == 2
    assert "no manual-only drafts were staged" in result["error"]


@pytest.mark.asyncio
async def test_youtube_descriptions_all_item_failures_are_retry_visible(
    monkeypatch: pytest.MonkeyPatch,
):
    _silence_telegram(monkeypatch)
    monkeypatch.setenv("YOUTUBE_CHANNEL_ID", "channel-1")
    monkeypatch.setattr(
        youtube_descriptions,
        "fetch_channel_videos",
        lambda channel_id, max_results: [
            {"video_id": "video-1", "title": "One", "description": "Old one"},
            {"video_id": "video-2", "title": "Two", "description": "Old two"},
        ],
    )
    monkeypatch.setattr(
        youtube_descriptions,
        "_rewrite_description",
        AsyncMock(side_effect=RuntimeError("temporary content failure")),
    )

    result = await youtube_descriptions.run_description_generator(
        MemoryTaskSink(), boilerplate="New standard footer"
    )

    assert result["status"] == "error"
    assert result["scanned"] == 2
    assert result["staged"] == 0
    assert result["failed"] == 2
    assert "no descriptions were staged" in result["error"]


@pytest.mark.asyncio
async def test_partial_item_failure_preserves_success_summary(
    monkeypatch: pytest.MonkeyPatch,
):
    _silence_telegram(monkeypatch)
    monkeypatch.setenv("YOUTUBE_CHANNEL_ID", "channel-1")
    monkeypatch.setattr(
        youtube_comments,
        "fetch_channel_videos",
        lambda channel_id, max_results: [{"video_id": "video-1", "title": "Video"}],
    )
    monkeypatch.setattr(
        youtube_comments,
        "fetch_recent_comments",
        lambda video_id, max_results: [
            {"comment_id": "comment-1", "text": "First", "author": "A"},
            {"comment_id": "comment-2", "text": "Second", "author": "B"},
        ],
    )
    monkeypatch.setattr(
        youtube_comments,
        "_generate_reply",
        AsyncMock(
            side_effect=[
                _content_result("A useful reply"),
                RuntimeError("temporary model failure"),
            ]
        ),
    )
    sink = MemoryTaskSink()

    result = await youtube_comments.run_youtube_comment_workflow(sink)

    assert result["status"] == "complete"
    assert result["scanned"] == 2
    assert result["staged"] == 1
    assert result["failed"] == 1
    assert len(result["task_ids"]) == 1
    assert len(sink.tasks) == 1
