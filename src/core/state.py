"""
state.py — LangGraph State Definitions

This module defines the shared state that flows through every council's
debate graph. Think of it as the "memory" that gets passed from agent to agent.

Every council uses the same base state structure, which means:
- All councils speak the same "language"
- Cross-council communication is trivial
- Observability tools can trace any council uniformly
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field
from langgraph.graph.message import add_messages


# ── Enums ────────────────────────────────────────────────────────────────

class CouncilStatus(str, Enum):
    """Tracks where a council is in its lifecycle."""
    PENDING = "pending"            # Task received, not started
    GENERATING = "generating"      # Generator is drafting V1
    CRITIQUING = "critiquing"      # Critic is reviewing
    REFINING = "refining"          # Generator is revising based on critique
    CONSENSUS = "consensus"        # Confidence threshold met
    AWAITING_APPROVAL = "awaiting_approval"  # Paused for human review
    APPROVED = "approved"          # Human approved
    REJECTED = "rejected"          # Human rejected (will feed back into learning)
    FAILED = "failed"              # Max retries exceeded or error


class AgentRole(str, Enum):
    """Standard roles inside a council."""
    SUPERVISOR = "supervisor"
    GENERATOR = "generator"
    CRITIC = "critic"
    SYNTHESIZER = "synthesizer"


class Priority(str, Enum):
    """Task priority levels for cost-based model routing."""
    LOW = "low"          # Use cheapest model (Nano/Flash-Lite)
    MEDIUM = "medium"    # Use balanced model (GPT-4.1 Mini / Haiku)
    HIGH = "high"        # Use smart model (GPT-4.1 / Sonnet)
    CRITICAL = "critical"  # Use best model (Opus / Gemini Pro)


# ── Data Models ──────────────────────────────────────────────────────────

class AgentMessage(BaseModel):
    """A single message from an agent during the debate."""
    role: AgentRole
    model_used: str = ""
    content: str
    confidence_score: float = 0.0  # 0-100, only set by Critic
    cost_usd: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HumanFeedback(BaseModel):
    """Feedback from the human approval step."""
    approved: bool
    edits: str = ""         # If rejected, what they changed
    notes: str = ""         # Free-form notes
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── The Core State ───────────────────────────────────────────────────────

class CouncilState(BaseModel):
    """
    The state object that flows through every LangGraph council.

    This is the single source of truth during a council's execution.
    Every node (agent) reads from and writes to this state.
    """

    # ── Identity ──
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    council_name: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ── Input ──
    task_description: str = ""       # What the council needs to do
    context: dict[str, Any] = Field(default_factory=dict)  # Extra context (lead data, doc content, etc.)
    priority: Priority = Priority.MEDIUM

    # ── Debate State ──
    status: CouncilStatus = CouncilStatus.PENDING
    current_draft: str = ""          # The latest version of the output
    debate_history: list[AgentMessage] = Field(default_factory=list)
    iteration: int = 0               # Current debate round
    max_iterations: int = 3          # Max debate rounds before forced consensus
    confidence_score: float = 0.0    # Latest score from Critic (0-100)
    confidence_threshold: float = 85.0  # Score needed to reach consensus

    # ── Output ──
    final_output: str = ""
    human_feedback: HumanFeedback | None = None

    # ── Cost Tracking ──
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    # ── Metadata ──
    error: str = ""
    tags: list[str] = Field(default_factory=list)
