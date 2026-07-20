"""
llm_router.py — Unified LLM Gateway via OpenRouter

Uses a single OpenRouter API key to access all providers
(OpenAI, Anthropic, Google) through OpenAI-compatible endpoints.

Zero extra dependencies — just the `openai` package.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()


# ── Model Tier Configuration ────────────────────────────────────────────

@dataclass
class ModelTier:
    """A named tier that maps to a specific model + pricing info."""
    name: str
    model_id: str            # OpenRouter model ID
    input_cost_per_m: float  # USD per 1M input tokens
    output_cost_per_m: float # USD per 1M output tokens
    description: str


MODEL_TIERS: dict[str, ModelTier] = {
    "cheap": ModelTier(
        name="cheap",
        model_id="openai/gpt-4.1-nano",
        input_cost_per_m=0.10,
        output_cost_per_m=0.40,
        description="Ultra-cheap: routing, classification, tagging",
    ),
    "fast": ModelTier(
        name="fast",
        model_id="openai/gpt-4.1-mini",
        input_cost_per_m=0.40,
        output_cost_per_m=1.60,
        description="Fast + affordable: summaries, simple generation",
    ),
    "smart": ModelTier(
        name="smart",
        model_id="anthropic/claude-sonnet-4",
        input_cost_per_m=3.00,
        output_cost_per_m=15.00,
        description="High quality: critique, analysis, content creation",
    ),
    "reasoning": ModelTier(
        name="reasoning",
        model_id="anthropic/claude-opus-4",
        input_cost_per_m=5.00,
        output_cost_per_m=25.00,
        description="Flagship: complex reasoning, grant writing, strategy",
    ),
}


PRIORITY_TO_TIER = {
    "low": "cheap",
    "medium": "fast",
    "high": "smart",
    "critical": "reasoning",
}


# ── OpenRouter Client ────────────────────────────────────────────────────

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    """Get the OpenRouter client (OpenAI-compatible)."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.getenv("OPENROUTER_API_KEY", ""),
            base_url="https://openrouter.ai/api/v1",
        )
    return _client


# ── Core Router ──────────────────────────────────────────────────────────

def get_model_for_priority(priority: str) -> ModelTier:
    """Get the model tier for a given priority level."""
    tier_name = PRIORITY_TO_TIER.get(priority, "fast")
    return MODEL_TIERS[tier_name]


def get_model_for_role(role: str, priority: str = "medium") -> ModelTier:
    """
    Get the appropriate model based on agent role and task priority.

    Supervisors always use cheap models (they just route).
    Critics always use smart models (they need analytical depth).
    Generators and Synthesizers follow the task priority.
    """
    role_overrides = {
        "supervisor": "cheap",
        "critic": "smart",
    }

    if role in role_overrides:
        return MODEL_TIERS[role_overrides[role]]

    return get_model_for_priority(priority)


async def call_llm(
    messages: list[dict],
    tier: str = "fast",
    model_override: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> dict:
    """
    Call an LLM through OpenRouter.

    Returns:
        - content: str (the response text)
        - model: str (which model was used)
        - input_tokens: int
        - output_tokens: int
        - cost_usd: float (estimated cost)
    """
    model_tier = MODEL_TIERS.get(tier, MODEL_TIERS["fast"])
    model_id = model_override or model_tier.model_id
    client = get_client()

    response = await client.chat.completions.create(
        model=model_id,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    # Extract usage
    usage = response.usage
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0

    # Calculate cost
    cost_usd = (
        (input_tokens / 1_000_000) * model_tier.input_cost_per_m
        + (output_tokens / 1_000_000) * model_tier.output_cost_per_m
    )

    return {
        "content": response.choices[0].message.content,
        "model": model_id,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost_usd, 6),
    }


def list_available_models() -> list[dict]:
    """List all configured model tiers."""
    return [
        {
            "tier": t.name,
            "model": t.model_id,
            "input_cost": f"${t.input_cost_per_m}/1M",
            "output_cost": f"${t.output_cost_per_m}/1M",
            "description": t.description,
        }
        for t in MODEL_TIERS.values()
    ]
