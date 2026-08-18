"""Structured generator/critic execution engine shared by production councils."""

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from typing import Any

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.llm_router import (
    StructuredOutputError,
    call_llm_structured,
    get_council_model,
)
from src.core.state import AgentMessage, AgentRole, CouncilStatus


class TextDraftOutput(BaseModel):
    """Strict generator output for prose-oriented councils."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)
    assumptions: list[str]
    warnings: list[str]


class CritiqueOutput(BaseModel):
    """Strict critic output; the engine recomputes the authoritative score."""

    model_config = ConfigDict(extra="forbid")

    category_scores: dict[str, float]
    overall_score: float = Field(ge=0, le=100)
    strengths: list[str]
    weaknesses: list[str]
    required_edits: list[str]

    @field_validator("category_scores")
    @classmethod
    def scores_are_bounded(cls, value: dict[str, float]) -> dict[str, float]:
        if not value:
            raise ValueError("At least one category score is required.")
        if any(score < 0 or score > 100 for score in value.values()):
            raise ValueError("Every category score must be between 0 and 100.")
        return value


class CouncilRunResult(BaseModel):
    """Stable result contract consumed by API and durable worker layers."""

    task_id: str
    council: str
    status: CouncilStatus
    final_output: str
    structured_output: dict[str, Any] = Field(default_factory=dict)
    confidence_score: float
    draft_count: int
    debate_history: list[dict[str, Any]]
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    cost_metrics_complete: bool
    warnings: list[str] = Field(default_factory=list)
    error: str = ""

    def to_task_updates(self) -> dict[str, Any]:
        """Return database-friendly fields without hiding unavailable metrics."""
        return {
            "status": self.status.value,
            "final_output": self.final_output,
            "confidence_score": self.confidence_score,
            "iterations": self.draft_count,
            "total_cost_usd": self.total_cost_usd,
            "cost_metrics_complete": self.cost_metrics_complete,
            "debate_history": self.debate_history,
            "warnings": self.warnings,
            "error": self.error,
        }


class BaseCouncil(ABC):
    """A maximum-three-draft generator/critic loop with no model fallback."""

    council_name = "base"
    confidence_threshold = 85.0
    max_iterations = 3
    critic_categories: dict[str, float] = {}

    def __init__(self, *, checkpointer: Any = None):
        if self.council_name not in {"grant", "sales", "content"}:
            raise ValueError(f"{self.council_name!r} is not a production council.")
        if self.max_iterations != 3:
            raise ValueError("Production councils must allow exactly three drafts maximum.")
        builder = self._build_graph()
        self.graph = builder.compile(checkpointer=checkpointer) if checkpointer else builder.compile()

    @abstractmethod
    def get_generator_prompt(self, state: dict[str, Any]) -> list[dict[str, str]]:
        ...

    @abstractmethod
    def get_critic_prompt(self, state: dict[str, Any]) -> list[dict[str, str]]:
        ...

    def get_generator_output_model(self, state: dict[str, Any]) -> type[BaseModel]:
        return TextDraftOutput

    def draft_to_text(self, draft: BaseModel, state: dict[str, Any]) -> str:
        content = getattr(draft, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise StructuredOutputError("Generator output did not contain non-empty content.")
        return content.strip()

    async def _retrieve_context(self, state: dict[str, Any]) -> dict[str, Any]:
        """Retrieve only explicitly selected Grant documents and surface failures."""
        warnings = list(state.get("warnings", []))
        rag_context = ""
        selected_docs = (state.get("context") or {}).get("selected_docs")

        if self.council_name == "grant" and selected_docs:
            if not isinstance(selected_docs, list) or not all(
                isinstance(item, str) and item.strip() for item in selected_docs
            ):
                raise ValueError("context.selected_docs must be a list of document hashes.")
            try:
                from src.core.rag_engine import get_rag_context

                rag_context = await get_rag_context(
                    state.get("task_description", ""),
                    top_k=3,
                    doc_hashes=selected_docs,
                )
                if not rag_context:
                    warnings.append("No relevant text was found in the selected knowledge documents.")
            except Exception as exc:
                warnings.append(f"Selected knowledge retrieval failed: {type(exc).__name__}: {exc}")

        return {**state, "rag_context": rag_context, "warnings": warnings}

    @staticmethod
    def _inject_context(
        messages: list[dict[str, str]], state: dict[str, Any]
    ) -> list[dict[str, str]]:
        rag_context = state.get("rag_context", "")
        if not rag_context:
            return messages
        return [
            *messages,
            {
                "role": "system",
                "content": (
                    "Use only the following administrator-selected knowledge excerpts when relevant. "
                    "Do not claim that an excerpt says something it does not say.\n\n"
                    f"SELECTED KNOWLEDGE:\n{rag_context}"
                ),
            },
        ]

    @staticmethod
    def _append_metric_totals(state: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
        reported_cost = metrics.get("cost_usd")
        return {
            "total_input_tokens": state.get("total_input_tokens", 0) + metrics.get("input_tokens", 0),
            "total_output_tokens": state.get("total_output_tokens", 0) + metrics.get("output_tokens", 0),
            "total_cost_usd": state.get("total_cost_usd", 0.0) + (reported_cost or 0.0),
            "cost_metrics_complete": state.get("cost_metrics_complete", True)
            and reported_cost is not None,
        }

    async def _generate(self, state: dict[str, Any]) -> dict[str, Any]:
        draft_number = int(state.get("iteration", 0)) + 1
        if draft_number > self.max_iterations:
            raise RuntimeError("Generator draft cap exceeded.")

        messages = self._inject_context(self.get_generator_prompt(state), state)
        model_id = get_council_model(self.council_name, "generator")
        requested_model = state.get("model")
        if requested_model and requested_model != model_id:
            raise ValueError(
                f"Model override rejected: {self.council_name} generator is fixed to {model_id}."
            )
        draft, metrics = await call_llm_structured(
            messages=messages,
            model_id=model_id,
            output_model=self.get_generator_output_model(state),
            temperature=0.65,
            max_tokens=7000 if self.council_name == "grant" else 5000,
        )
        draft_text = self.draft_to_text(draft, state)
        structured = draft.model_dump(mode="json")
        history = list(state.get("debate_history", []))
        history.append(
            AgentMessage(
                role=AgentRole.GENERATOR,
                model_used=metrics["model"],
                content=draft_text,
                cost_usd=metrics.get("cost_usd"),
                cost_source=metrics.get("cost_source", "unavailable"),
                input_tokens=metrics.get("input_tokens", 0),
                output_tokens=metrics.get("output_tokens", 0),
                provider_request_id=metrics.get("provider_request_id"),
                prompt_messages=messages,
                structured_output=structured,
            ).model_dump(mode="json")
        )
        output = {
            **state,
            "iteration": draft_number,
            "current_draft": draft_text,
            "current_structured_output": structured,
            "status": CouncilStatus.GENERATING.value,
            "debate_history": history,
            "warnings": [
                *state.get("warnings", []),
                *(
                    structured.get("warnings", [])
                    if isinstance(structured.get("warnings", []), list)
                    else []
                ),
            ],
        }
        output.update(self._append_metric_totals(state, metrics))
        return output

    def _authoritative_score(self, critique: CritiqueOutput) -> float:
        expected = set(self.critic_categories)
        actual = set(critique.category_scores)
        if expected != actual:
            missing = sorted(expected - actual)
            unexpected = sorted(actual - expected)
            raise StructuredOutputError(
                f"Critic categories did not match contract; missing={missing}, unexpected={unexpected}."
            )
        total_weight = sum(self.critic_categories.values())
        if total_weight <= 0:
            raise RuntimeError("Critic category weights must sum to a positive number.")
        return round(
            sum(
                critique.category_scores[name] * weight
                for name, weight in self.critic_categories.items()
            )
            / total_weight,
            2,
        )

    async def _critique(self, state: dict[str, Any]) -> dict[str, Any]:
        messages = self._inject_context(self.get_critic_prompt(state), state)
        model_id = get_council_model(self.council_name, "critic")
        critique, metrics = await call_llm_structured(
            messages=messages,
            model_id=model_id,
            output_model=CritiqueOutput,
            temperature=0.2,
            max_tokens=3500,
        )
        confidence = self._authoritative_score(critique)
        structured = critique.model_dump(mode="json")
        structured["model_reported_overall_score"] = structured["overall_score"]
        structured["overall_score"] = confidence
        history = list(state.get("debate_history", []))
        history.append(
            AgentMessage(
                role=AgentRole.CRITIC,
                model_used=metrics["model"],
                content=json.dumps(structured, ensure_ascii=False),
                confidence_score=confidence,
                cost_usd=metrics.get("cost_usd"),
                cost_source=metrics.get("cost_source", "unavailable"),
                input_tokens=metrics.get("input_tokens", 0),
                output_tokens=metrics.get("output_tokens", 0),
                provider_request_id=metrics.get("provider_request_id"),
                prompt_messages=messages,
                structured_output=structured,
            ).model_dump(mode="json")
        )
        output = {
            **state,
            "confidence_score": confidence,
            "status": CouncilStatus.CRITIQUING.value,
            "debate_history": history,
            "last_critique": structured,
        }
        output.update(self._append_metric_totals(state, metrics))
        return output

    def _should_continue(self, state: dict[str, Any]) -> str:
        if float(state.get("confidence_score", 0)) >= self.confidence_threshold:
            return "approval"
        if int(state.get("iteration", 0)) >= self.max_iterations:
            return "manual_review"
        return "generate"

    def _prepare_approval(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            **state,
            "final_output": state.get("current_draft", ""),
            "final_structured_output": state.get("current_structured_output", {}),
            "status": CouncilStatus.AWAITING_APPROVAL.value,
            "error": "",
        }

    def _prepare_manual_review(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            **state,
            "final_output": state.get("current_draft", ""),
            "final_structured_output": state.get("current_structured_output", {}),
            "status": CouncilStatus.NEEDS_MANUAL_REVIEW.value,
            "error": (
                f"Quality threshold {self.confidence_threshold:.0f} was not reached after "
                f"{self.max_iterations} drafts."
            ),
        }

    def _build_graph(self) -> StateGraph:
        builder = StateGraph(dict)
        builder.add_node("retrieve_context", self._retrieve_context)
        builder.add_node("generate", self._generate)
        builder.add_node("critique", self._critique)
        builder.add_node("approval", self._prepare_approval)
        builder.add_node("manual_review", self._prepare_manual_review)
        builder.add_edge(START, "retrieve_context")
        builder.add_edge("retrieve_context", "generate")
        builder.add_edge("generate", "critique")
        builder.add_conditional_edges(
            "critique",
            self._should_continue,
            {
                "generate": "generate",
                "approval": "approval",
                "manual_review": "manual_review",
            },
        )
        builder.add_edge("approval", END)
        builder.add_edge("manual_review", END)
        return builder

    async def run(
        self,
        task_description: str,
        *,
        context: dict[str, Any] | None = None,
        priority: str = "medium",
        task_id: str | None = None,
    ) -> CouncilRunResult:
        """Execute the stable council contract for the API or durable worker."""
        if not task_description.strip():
            raise ValueError("task_description must not be empty.")
        final = await self.graph.ainvoke(
            {
                "task_id": task_id or str(uuid.uuid4()),
                "council_name": self.council_name,
                "task_description": task_description.strip(),
                "context": context or {},
                "priority": priority,
                "iteration": 0,
                "max_iterations": self.max_iterations,
                "confidence_threshold": self.confidence_threshold,
                "debate_history": [],
                "total_cost_usd": 0.0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "cost_metrics_complete": True,
                "warnings": [],
            }
        )
        return CouncilRunResult(
            task_id=final["task_id"],
            council=self.council_name,
            status=CouncilStatus(final["status"]),
            final_output=final.get("final_output", ""),
            structured_output=final.get("final_structured_output", {}),
            confidence_score=float(final.get("confidence_score", 0)),
            draft_count=int(final.get("iteration", 0)),
            debate_history=final.get("debate_history", []),
            total_input_tokens=int(final.get("total_input_tokens", 0)),
            total_output_tokens=int(final.get("total_output_tokens", 0)),
            total_cost_usd=float(final.get("total_cost_usd", 0.0)),
            cost_metrics_complete=bool(final.get("cost_metrics_complete", False)),
            warnings=final.get("warnings", []),
            error=final.get("error", ""),
        )
