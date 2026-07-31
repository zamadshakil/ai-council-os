"""
council_base.py — The Core Debate Engine

This is the heart of the AI Council OS. It defines the reusable
debate loop that every council (Sales, Content, Grant, Strategy) inherits.

The flow:
    1. GENERATE  → Generator agent drafts V1
    2. CRITIQUE  → Critic agent reviews and scores (0-100)
    3. DECIDE    → Supervisor checks: score >= threshold?
                    YES → move to human approval
                    NO  → loop back to GENERATE with critique feedback
                    MAX RETRIES → force consensus with best version
    4. APPROVE   → Human reviews (graph pauses here via interrupt)
    5. LEARN     → If rejected, feedback is stored for future improvement
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.core.state import (
    CouncilState,
    CouncilStatus,
    AgentRole,
    AgentMessage,
    HumanFeedback,
)
from src.core.llm_router import call_llm, get_model_for_role


class BaseCouncil(ABC):
    """
    Abstract base class for all councils.

    Subclasses must implement:
        - council_name: str
        - get_generator_prompt(state) -> list[dict]
        - get_critic_prompt(state) -> list[dict]
        - get_synthesizer_prompt(state) -> list[dict]

    The debate loop, consensus mechanism, and human approval
    workflow are handled automatically by this base class.
    """

    council_name: str = "base"
    min_iterations: int = 2
    confidence_threshold: float = 92.0
    max_iterations: int = 4

    def __init__(self):
        self.graph = self._build_graph().compile()

    # ── Abstract Methods (subclasses MUST implement) ─────────────────

    @abstractmethod
    def get_generator_prompt(self, state: dict) -> list[dict]:
        """Return the messages list for the Generator agent."""
        ...

    @abstractmethod
    def get_critic_prompt(self, state: dict) -> list[dict]:
        """Return the messages list for the Critic agent."""
        ...

    def get_synthesizer_prompt(self, state: dict) -> list[dict]:
        """
        Return the messages list for the Synthesizer agent.
        Default implementation asks the model to merge generator + critic feedback.
        Override in subclasses for custom synthesis logic.
        """
        return [
            {
                "role": "system",
                "content": (
                    "You are the Synthesizer. You receive a draft and critique feedback. "
                    "Produce the best possible final version that addresses all valid concerns "
                    "from the Critic while preserving the Generator's intent. "
                    "Output ONLY the improved version, no commentary."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"ORIGINAL DRAFT:\n{state.get('current_draft', '')}\n\n"
                    f"CRITIC FEEDBACK:\n{state['debate_history'][-1]['content'] if state.get('debate_history') else 'No feedback yet'}\n\n"
                    f"TASK: {state.get('task_description', '')}\n\n"
                    "Produce the improved final version:"
                ),
            },
        ]

    # ── Graph Nodes ──────────────────────────────────────────────────

    async def _retrieve_context(self, state: dict) -> dict:
        """
        Context retrieval node (fires before Generator on first iteration only).
        Fetches:
          1. RAG knowledge chunks (relevant documents from knowledge base)
          2. Memory context (brand guidelines, preferences, past approved examples)
        Gracefully no-ops if either source is empty or unavailable.
        """
        if state.get("iteration", 0) > 0:
            return {}

        rag_ctx = ""
        memory_ctx = ""
        task = state.get("task_description", "")

        try:
            from src.core.rag_engine import get_rag_context
            rag_ctx = await get_rag_context(task, top_k=3)
            if rag_ctx:
                print(f"[RAG] Injecting {len(rag_ctx)} chars into {self.council_name} council.")
        except Exception as e:
            print(f"[RAG] Skipped (non-fatal): {e}")

        try:
            from src.core.memory_manager import get_memory_context
            memory_ctx = await get_memory_context(task, self.council_name)
            if memory_ctx:
                print(f"[Memory] Injecting {len(memory_ctx)} chars into {self.council_name} council.")
        except Exception as e:
            print(f"[Memory] Skipped (non-fatal): {e}")

        return {
            "rag_context": rag_ctx,
            "memory_context": memory_ctx,
        }

    async def _generate(self, state: dict) -> dict:
        """Generator agent: creates or refines the draft."""
        priority = state.get("priority", "medium")
        messages = self.get_generator_prompt(state)

        result = await call_llm(
            messages=messages,
            tier=get_model_for_role("generator", priority).name,
        )

        agent_msg = AgentMessage(
            role=AgentRole.GENERATOR,
            model_used=result["model"],
            content=result["content"],
            cost_usd=result["cost_usd"],
        )

        history = state.get("debate_history", [])
        history.append(agent_msg.model_dump(mode="json"))

        return {
            "current_draft": result["content"],
            "status": CouncilStatus.GENERATING.value,
            "debate_history": history,
            "total_cost_usd": state.get("total_cost_usd", 0) + result["cost_usd"],
            "total_input_tokens": state.get("total_input_tokens", 0) + result["input_tokens"],
            "total_output_tokens": state.get("total_output_tokens", 0) + result["output_tokens"],
        }

    async def _critique(self, state: dict) -> dict:
        """Critic agent: reviews the draft and assigns a confidence score."""
        messages = self.get_critic_prompt(state)

        result = await call_llm(
            messages=messages,
            tier="smart",  # Critics always use smart models
            temperature=0.3,  # Lower temperature for more consistent scoring
        )

        # Parse confidence score from the response
        confidence = self._extract_confidence(result["content"])

        agent_msg = AgentMessage(
            role=AgentRole.CRITIC,
            model_used=result["model"],
            content=result["content"],
            confidence_score=confidence,
            cost_usd=result["cost_usd"],
        )

        history = state.get("debate_history", [])
        history.append(agent_msg.model_dump(mode="json"))

        return {
            "confidence_score": confidence,
            "status": CouncilStatus.CRITIQUING.value,
            "debate_history": history,
            "total_cost_usd": state.get("total_cost_usd", 0) + result["cost_usd"],
            "total_input_tokens": state.get("total_input_tokens", 0) + result["input_tokens"],
            "total_output_tokens": state.get("total_output_tokens", 0) + result["output_tokens"],
        }

    async def _synthesize(self, state: dict) -> dict:
        """Synthesizer agent: merges generator draft + critic feedback into final version."""
        priority = state.get("priority", "medium")
        messages = self.get_synthesizer_prompt(state)

        result = await call_llm(
            messages=messages,
            tier=get_model_for_role("synthesizer", priority).name,
        )

        agent_msg = AgentMessage(
            role=AgentRole.SYNTHESIZER,
            model_used=result["model"],
            content=result["content"],
            cost_usd=result["cost_usd"],
        )

        history = state.get("debate_history", [])
        history.append(agent_msg.model_dump(mode="json"))

        return {
            "current_draft": result["content"],
            "final_output": result["content"],
            "debate_history": history,
            "total_cost_usd": state.get("total_cost_usd", 0) + result["cost_usd"],
            "total_input_tokens": state.get("total_input_tokens", 0) + result["input_tokens"],
            "total_output_tokens": state.get("total_output_tokens", 0) + result["output_tokens"],
        }

    def _should_continue(self, state: dict) -> str:
        """
        The Supervisor's decision logic.

        Returns the next node name:
            - "synthesize" → confidence met, produce final output
            - "generate"   → needs another round of revision
            - "force_end"  → max iterations hit, use best draft
        """
        confidence = state.get("confidence_score", 0)
        iteration = state.get("iteration", 1)
        max_iter = state.get("max_iterations", self.max_iterations)
        min_iter = state.get("min_iterations", self.min_iterations)
        threshold = state.get("confidence_threshold", self.confidence_threshold)

        # Enforce minimum debate rounds so Generator & Critic iterate at least twice
        if iteration < min_iter:
            return "generate"

        if confidence >= threshold:
            return "synthesize"
        elif iteration >= max_iter:
            return "force_end"
        else:
            return "generate"

    def _increment_iteration(self, state: dict) -> dict:
        """Bump the iteration counter before looping back."""
        return {
            "iteration": state.get("iteration", 0) + 1,
            "status": CouncilStatus.REFINING.value,
        }

    def _prepare_approval(self, state: dict) -> dict:
        """Mark the state as ready for human review."""
        return {
            "final_output": state.get("final_output") or state.get("current_draft", ""),
            "status": CouncilStatus.AWAITING_APPROVAL.value,
        }

    def _force_end(self, state: dict) -> dict:
        """Max retries exceeded — use the best available draft."""
        return {
            "final_output": state.get("current_draft", ""),
            "status": CouncilStatus.CONSENSUS.value,
            "error": f"Max iterations ({self.max_iterations}) reached. Using best available draft.",
        }

    # ── Graph Construction ───────────────────────────────────────────

    def _build_graph(self) -> StateGraph:
        """
        Builds the LangGraph state machine for this council.

        Flow:
            START → generate → critique → [decide]
                                             ├── synthesize → approve → END
                                             ├── generate (loop back)
                                             └── force_end → approve → END
        """
        builder = StateGraph(dict)

        # Add nodes
        builder.add_node("retrieve_context", self._retrieve_context)
        builder.add_node("generate", self._generate)
        builder.add_node("critique", self._critique)
        builder.add_node("increment", self._increment_iteration)
        builder.add_node("synthesize", self._synthesize)
        builder.add_node("approve", self._prepare_approval)
        builder.add_node("force_end", self._force_end)

        # Define edges
        builder.add_edge(START, "retrieve_context")
        builder.add_edge("retrieve_context", "generate")
        builder.add_edge("generate", "critique")

        # Conditional branching after critique
        builder.add_conditional_edges(
            "critique",
            self._should_continue,
            {
                "synthesize": "synthesize",
                "generate": "increment",
                "force_end": "force_end",
            },
        )

        # Loop back after incrementing
        builder.add_edge("increment", "generate")

        # Synthesize → Approve → END
        builder.add_edge("synthesize", "approve")
        builder.add_edge("force_end", "approve")
        builder.add_edge("approve", END)

        return builder

    def compile(self, checkpointer=None):
        """
        Compile the graph into a runnable.

        Args:
            checkpointer: LangGraph checkpointer for state persistence.
                         Uses MemorySaver (in-memory) by default.
                         Use SqliteSaver or PostgresSaver for production.
        """
        if checkpointer is None:
            checkpointer = MemorySaver()

        return self._build_graph().compile()

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _extract_confidence(critic_response: str) -> float:
        """
        Extract a confidence score from the Critic's response.

        The Critic is prompted to include a score like:
            CONFIDENCE: 87/100

        Falls back to 50.0 if parsing fails.
        """
        import re

        patterns = [
            r"CONFIDENCE:\s*(\d+(?:\.\d+)?)\s*/\s*100",
            r"CONFIDENCE:\s*(\d+(?:\.\d+)?)",
            r"Score:\s*(\d+(?:\.\d+)?)\s*/\s*100",
            r"(\d+(?:\.\d+)?)\s*/\s*100",
        ]

        for pattern in patterns:
            match = re.search(pattern, critic_response, re.IGNORECASE)
            if match:
                score = float(match.group(1))
                return min(max(score, 0.0), 100.0)  # Clamp to 0-100

        return 50.0  # Default if no score found
