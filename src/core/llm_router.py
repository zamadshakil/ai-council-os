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
        model_id="openrouter/free",
        input_cost_per_m=0.00,
        output_cost_per_m=0.00,
        description="OpenRouter Auto-Free: Best available 100% free model",
    ),
    "fast": ModelTier(
        name="fast",
        model_id="openrouter/free",
        input_cost_per_m=0.00,
        output_cost_per_m=0.00,
        description="OpenRouter Auto-Free: Ultra-fast 100% free model",
    ),
    "smart": ModelTier(
        name="smart",
        model_id="openrouter/free",
        input_cost_per_m=0.00,
        output_cost_per_m=0.00,
        description="OpenRouter Auto-Free: Quality 100% free model",
    ),
    "reasoning": ModelTier(
        name="reasoning",
        model_id="openrouter/free",
        input_cost_per_m=0.00,
        output_cost_per_m=0.00,
        description="OpenRouter Auto-Free: Strategy 100% free model",
    ),
}


PRIORITY_TO_TIER = {
    "low": "fast",
    "medium": "fast",
    "high": "fast",
    "critical": "fast",
}


# ── OpenRouter Client ────────────────────────────────────────────────────

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    """Get the OpenRouter client (OpenAI-compatible)."""
    global _client
    if _client is None:
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable is not set on the server.")
        _client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=30.0,
            default_headers={
                "HTTP-Referer": "https://councilos.ai",
                "X-Title": "AI Council OS",
            },
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
    Critics and Generators follow the task priority.
    """
    if role == "supervisor":
        return MODEL_TIERS["cheap"]

    return get_model_for_priority(priority)


async def call_llm(
    messages: list[dict],
    tier: str = "fast",
    model_override: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> dict:
    """
    Call an LLM through OpenRouter with model fallbacks for network resilience.

    IMPORTANT: All fallback candidates are guaranteed zero-cost. This function will
    NEVER silently escalate to a paid model. If a caller genuinely needs a specific
    paid model, they must pass it explicitly via `model_override` — it will still
    only be retried against itself and the free router, never swapped for another
    paid model behind the scenes.
    """
    import asyncio
    model_tier = MODEL_TIERS.get(tier, MODEL_TIERS["fast"])
    primary_model = model_override or model_tier.model_id

    # Resilient fallback queue — always zero-cost. "openrouter/free" is OpenRouter's
    # own Free Models Router: it randomly selects among currently available free
    # models, so retrying against it again after a failure gives us a different
    # free model on the next attempt without ever touching a paid model.
    candidate_models = [primary_model]
    if primary_model != "openrouter/free":
        candidate_models.append("openrouter/free")

    client = get_client()
    last_error = None

    for model_id in candidate_models:
        for attempt in range(2):
            try:
                response = await client.chat.completions.create(
                    model=model_id,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                usage = response.usage
                input_tokens = usage.prompt_tokens if usage else 0
                output_tokens = usage.completion_tokens if usage else 0

                cost_usd = (
                    (input_tokens / 1_000_000) * model_tier.input_cost_per_m
                    + (output_tokens / 1_000_000) * model_tier.output_cost_per_m
                )

                return {
                    "content": response.choices[0].message.content or "",
                    "model": model_id,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": round(cost_usd, 6),
                }
            except Exception as e:
                last_error = e
                print(f"[OpenRouter Retry {attempt + 1}/2 for {model_id}] {e}")
                await asyncio.sleep(1)

    raise last_error


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
