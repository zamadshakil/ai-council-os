from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from src.core.council_base import CritiqueOutput, TextDraftOutput
from src.core.llm_router import (
    APPROVED_MODELS,
    COUNCIL_MODEL_PROFILES,
    ModelPolicyError,
    assert_approved_model,
)
from src.core.workflow_contracts import (
    DuplicateExternalItem,
    PublicationPolicy,
    WorkflowTask,
    WorkflowTaskStatus,
    stage_workflow_task,
)
from src.councils import ALLOWED_COUNCILS, create_council
from src.councils.content.council import ContentVariantsOutput
from src.integrations.reddit import post_reddit_reply
from src.workflows.registry import (
    PRODUCTION_WORKFLOWS,
    WORKFLOW_JOB_HANDLERS,
    WorkflowJobFailed,
    run_workflow_job,
)
from src.workflows.content_engine import _run_content_council
from src.workflows.instagram_comments import _draft as _draft_instagram_comment
from src.workflows.instagram_comments import run_instagram_comment_workflow
from src.workflows.reddit_prospector import _draft_reply
from src.workflows.youtube_comments import _generate_reply
from src.workflows.youtube_descriptions import _rewrite_description


SALES_CATEGORIES = {
    "personalization": 20,
    "value_proposition": 20,
    "tone": 20,
    "call_to_action": 20,
    "length": 20,
}


def metrics(model: str, cost: float | None = 0.01) -> dict:
    return {
        "model": model,
        "input_tokens": 10,
        "output_tokens": 5,
        "cost_usd": cost,
        "cost_source": "provider_reported" if cost is not None else "unavailable",
        "provider_request_id": "generation-test",
    }


class CouncilPolicyTests(unittest.TestCase):
    def test_exact_councils_and_model_mapping(self):
        self.assertEqual(ALLOWED_COUNCILS, {"grant", "sales", "content"})
        self.assertEqual(
            COUNCIL_MODEL_PROFILES["grant"].generator,
            "anthropic/claude-sonnet-5",
        )
        self.assertEqual(
            COUNCIL_MODEL_PROFILES["sales"].generator,
            "openai/gpt-5.6-terra",
        )
        self.assertEqual(
            COUNCIL_MODEL_PROFILES["content"].critic,
            "openai/gpt-5.6-luna",
        )
        self.assertFalse(
            any(
                banned in model.lower()
                for model in APPROVED_MODELS
                for banned in ("deepseek", "qwen", "nvidia", ":free")
            )
        )

    def test_model_and_council_overrides_fail_closed(self):
        with self.assertRaises(ModelPolicyError):
            assert_approved_model("openrouter/free")
        with self.assertRaises(ValueError):
            create_council("strategy")
        with self.assertRaises(ValueError):
            create_council("support")

    def test_workflow_registry_has_current_approved_automations(self):
        self.assertEqual(
            set(PRODUCTION_WORKFLOWS),
            {
                "telegram_control",
                "youtube_comments",
                "reddit_prospector",
                "youtube_descriptions",
                "content_engine",
                "instagram_comments",
            },
        )

    def test_content_variants_are_exact_and_length_checked(self):
        valid = {
            "twitter": "x",
            "linkedin": "l",
            "facebook": "f",
            "instagram": "i",
            "reddit": "r",
            "discord": "d",
        }
        self.assertEqual(ContentVariantsOutput.model_validate(valid).twitter, "x")
        with self.assertRaises(ValidationError):
            ContentVariantsOutput.model_validate({key: value for key, value in valid.items() if key != "reddit"})
        with self.assertRaises(ValidationError):
            ContentVariantsOutput.model_validate({**valid, "twitter": "x" * 281})

    def test_reddit_publishing_is_disabled(self):
        with self.assertRaises(PermissionError):
            post_reddit_reply("post-1", "draft")


class CouncilExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_below_threshold_stops_after_exactly_three_drafts(self):
        generator_calls = 0
        critic_calls = 0

        async def fake_structured_call(**kwargs):
            nonlocal generator_calls, critic_calls
            output_model = kwargs["output_model"]
            if output_model is CritiqueOutput:
                critic_calls += 1
                return (
                    CritiqueOutput(
                        category_scores={key: 50 for key in SALES_CATEGORIES},
                        overall_score=99,
                        strengths=["specific"],
                        weaknesses=["not ready"],
                        required_edits=["revise"],
                    ),
                    metrics(kwargs["model_id"]),
                )
            generator_calls += 1
            return (
                TextDraftOutput(content=f"draft {generator_calls}", assumptions=[], warnings=[]),
                metrics(kwargs["model_id"]),
            )

        with patch("src.core.council_base.call_llm_structured", fake_structured_call):
            result = await create_council("sales").run("Draft outreach")

        self.assertEqual(generator_calls, 3)
        self.assertEqual(critic_calls, 3)
        self.assertEqual(result.draft_count, 3)
        self.assertEqual(result.status.value, "needs_manual_review")
        self.assertEqual(result.confidence_score, 50)
        self.assertEqual(result.final_output, "draft 3")
        self.assertAlmostEqual(result.total_cost_usd, 0.06)
        self.assertTrue(result.cost_metrics_complete)
        self.assertTrue(result.debate_history[0]["prompt_messages"])

    async def test_threshold_met_uses_one_draft_and_real_weighted_score(self):
        calls = {"generator": 0, "critic": 0}

        async def fake_structured_call(**kwargs):
            if kwargs["output_model"] is CritiqueOutput:
                calls["critic"] += 1
                scores = {key: 90 for key in SALES_CATEGORIES}
                scores["length"] = 70
                return (
                    CritiqueOutput(
                        category_scores=scores,
                        overall_score=1,
                        strengths=["good"],
                        weaknesses=[],
                        required_edits=[],
                    ),
                    metrics(kwargs["model_id"]),
                )
            calls["generator"] += 1
            return TextDraftOutput(content="approved draft", assumptions=[], warnings=[]), metrics(kwargs["model_id"])

        with patch("src.core.council_base.call_llm_structured", fake_structured_call):
            result = await create_council("sales").run("Draft outreach")

        self.assertEqual(calls, {"generator": 1, "critic": 1})
        self.assertEqual(result.status.value, "awaiting_approval")
        self.assertEqual(result.confidence_score, 86)

    async def test_missing_provider_cost_is_explicit_not_fabricated(self):
        async def fake_structured_call(**kwargs):
            if kwargs["output_model"] is CritiqueOutput:
                return (
                    CritiqueOutput(
                        category_scores={key: 100 for key in SALES_CATEGORIES},
                        overall_score=100,
                        strengths=["ready"],
                        weaknesses=[],
                        required_edits=[],
                    ),
                    metrics(kwargs["model_id"], None),
                )
            return TextDraftOutput(content="draft", assumptions=[], warnings=[]), metrics(kwargs["model_id"], None)

        with patch("src.core.council_base.call_llm_structured", fake_structured_call):
            result = await create_council("sales").run("Draft outreach")

        self.assertEqual(result.total_cost_usd, 0)
        self.assertFalse(result.cost_metrics_complete)
        self.assertIsNone(result.debate_history[0]["cost_usd"])


class WorkflowContractTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _fake_result():
        return SimpleNamespace(
            final_output="draft",
            confidence_score=90.0,
            total_cost_usd=0.01,
            cost_metrics_complete=True,
            draft_count=1,
            debate_history=[],
            structured_output={"content": "draft"},
            status=SimpleNamespace(value="awaiting_approval"),
            warnings=[],
        )

    async def test_each_workflow_uses_its_required_council_profile(self):
        class FakeCouncil:
            async def run(self, *args, **kwargs):
                return WorkflowContractTests._fake_result()

        with patch("src.workflows.youtube_comments.create_council", return_value=FakeCouncil()) as factory:
            await _generate_reply("Video", "Comment", "Viewer")
            factory.assert_called_once_with("content")

        with patch("src.workflows.youtube_descriptions.create_council", return_value=FakeCouncil()) as factory:
            await _rewrite_description("Video", "Old", "New")
            factory.assert_called_once_with("content")

        with patch("src.workflows.instagram_comments.create_council", return_value=FakeCouncil()) as factory:
            await _draft_instagram_comment(
                {
                    "comment_id": "comment-1",
                    "comment_text": "Can this automate approvals?",
                    "username": "viewer",
                    "media_id": "media-1",
                    "caption": "Automation demo",
                },
                "",
            )
            factory.assert_called_once_with("content")

        with patch("src.workflows.reddit_prospector.create_council", return_value=FakeCouncil()) as factory:
            await _draft_reply(
                {
                    "subreddit": "automation",
                    "title": "Need help",
                    "body": "How can I automate this repeated process?",
                    "author": "viewer",
                }
            )
            factory.assert_called_once_with("sales")

        content_result = self._fake_result()
        content_result.structured_output = {
            "twitter": "x",
            "linkedin": "l",
            "facebook": "f",
            "instagram": "i",
            "reddit": "r",
            "discord": "d",
        }

        class FakeContentCouncil:
            async def run(self, *args, **kwargs):
                return content_result

        with patch("src.workflows.content_engine.create_council", return_value=FakeContentCouncil()) as factory:
            await _run_content_council("Video", "Transcript", {})
            factory.assert_called_once_with("content")

    async def test_mapping_adapter_enforces_source_external_id_dedupe(self):
        store: dict[str, dict] = {}
        task = WorkflowTask(
            task_id="task-1",
            workflow="reddit_prospector",
            source="reddit",
            external_id="post-1",
            council="sales",
            status=WorkflowTaskStatus.AWAITING_APPROVAL,
            task_description="Lead",
            final_output="Manual draft",
            confidence_score=90,
            iterations=1,
            total_cost_usd=0.01,
            cost_metrics_complete=True,
            publication_policy=PublicationPolicy.MANUAL_ONLY,
        )
        await stage_workflow_task(store, task)
        self.assertEqual(store["task-1"]["publication_policy"], "manual_only")

        duplicate = task.model_copy(update={"task_id": "task-2"})
        with self.assertRaises(DuplicateExternalItem):
            await stage_workflow_task(store, duplicate)

    async def test_instagram_comment_is_staged_for_approval_and_never_auto_posted(self):
        class FakeCouncil:
            async def run(self, *args, **kwargs):
                return WorkflowContractTests._fake_result()

        store: dict[str, dict] = {}
        candidate = {
            "comment_id": "ig-comment-1",
            "comment_text": "Can you show how this works?",
            "username": "viewer",
            "media_id": "ig-media-1",
            "caption": "Product demo",
        }
        with (
            patch("src.workflows.instagram_comments.create_council", return_value=FakeCouncil()),
            patch("src.workflows.instagram_comments.workflow_kill_switch_active", return_value=False),
            patch("src.workflows.instagram_comments.workflow_execution_blocked", return_value=False),
        ):
            result = await run_instagram_comment_workflow(
                store, webhook_comments=[candidate]
            )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["staged"], 1)
        staged = next(iter(store.values()))
        self.assertEqual(staged["publication_policy"], "approval_required")
        self.assertEqual(staged["context"]["publish_action"], "instagram_comment_reply")

    async def test_durable_registry_raises_error_results_for_worker_retry(self):
        async def failed_handler(payload, sink):
            return {"workflow": "content_engine", "status": "error", "error": "temporary"}

        original = WORKFLOW_JOB_HANDLERS["content_engine"]
        WORKFLOW_JOB_HANDLERS["content_engine"] = failed_handler
        try:
            with self.assertRaises(WorkflowJobFailed):
                await run_workflow_job("content_engine", {}, {})
        finally:
            WORKFLOW_JOB_HANDLERS["content_engine"] = original


if __name__ == "__main__":
    unittest.main()
