"""
llm_router.py — Unified LLM Gateway via OpenRouter

Uses a single OpenRouter API key to access all providers
(OpenAI, Anthropic, Google) through OpenAI-compatible endpoints.

Zero extra dependencies — just the `openai` package.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, cast

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
        model_id="qwen/qwen3.7-flash",
        input_cost_per_m=0.03,
        output_cost_per_m=0.13,
        description="Qwen 3.7 Flash: ultra-low-cost routing and classification",
    ),
    "fast": ModelTier(
        name="fast",
        model_id="openai/gpt-5.6-luna",
        input_cost_per_m=0.10,
        output_cost_per_m=0.60,
        description="GPT-5.6 Luna: current high-quality price/performance generation",
    ),
    "smart": ModelTier(
        name="smart",
        model_id="google/gemini-3-flash-preview",
        input_cost_per_m=0.50,
        output_cost_per_m=3.00,
        description="Gemini 3 Flash: high-quality criticism and high-priority work",
    ),
    "reasoning": ModelTier(
        name="reasoning",
        model_id="google/gemini-3.1-pro-preview",
        input_cost_per_m=2.00,
        output_cost_per_m=12.00,
        description="Gemini 3.1 Pro: critical escalation only",
    ),
}

MODEL_PRICING = {
    tier.model_id: (tier.input_cost_per_m, tier.output_cost_per_m)
    for tier in MODEL_TIERS.values()
}

# Fallbacks only move laterally or downward in cost/quality; a cheap or fast
# request can never silently escalate to the Pro reasoning tier.
TIER_FALLBACKS = {
    "cheap": ["qwen/qwen3.7-flash", "openai/gpt-5.6-luna"],
    "fast": ["openai/gpt-5.6-luna", "qwen/qwen3.7-flash"],
    "smart": [
        "google/gemini-3-flash-preview",
        "openai/gpt-5.6-luna",
        "qwen/qwen3.7-flash",
    ],
    "reasoning": [
        "google/gemini-3.1-pro-preview",
        "google/gemini-3-flash-preview",
        "openai/gpt-5.6-luna",
    ],
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

    All candidates are explicit, cost-bounded, non-DeepSeek model IDs. Fallbacks
    never escalate to a more expensive tier. Generic automatic routing is forbidden.
    """
    import asyncio
    model_tier = MODEL_TIERS.get(tier, MODEL_TIERS["fast"])
    primary_model = model_override or model_tier.model_id

    if "deepseek" in primary_model.lower():
        raise ValueError("DeepSeek models are prohibited by client policy.")
    if primary_model not in MODEL_PRICING:
        raise ValueError("Model override is not in the approved cost-controlled model list.")

    candidate_models = list(dict.fromkeys([
        primary_model,
        *TIER_FALLBACKS[model_tier.name],
    ]))

    client = get_client()
    last_error = None

    for model_id in candidate_models:
        for attempt in range(2):
            try:
                response = await client.chat.completions.create(
                    model=model_id,
                    messages=cast(Any, messages),
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                content = response.choices[0].message.content or ""
                if not content.strip():
                    raise ValueError(f"Model {model_id} returned an empty response.")

                usage = response.usage
                input_tokens = usage.prompt_tokens if usage else 0
                output_tokens = usage.completion_tokens if usage else 0
                input_rate, output_rate = MODEL_PRICING[model_id]
                cost_usd = (
                    (input_tokens / 1_000_000) * input_rate
                    + (output_tokens / 1_000_000) * output_rate
                )

                return {
                    "content": content,
                    "model": model_id,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": round(cost_usd, 6),
                }
            except Exception as e:
                last_error = e
                print(f"[OpenRouter Retry {attempt + 1}/2 for {model_id}] {e}")
                await asyncio.sleep(1)

    if last_error is not None:
        raise last_error
    raise RuntimeError("No OpenRouter model candidates were available.")


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
