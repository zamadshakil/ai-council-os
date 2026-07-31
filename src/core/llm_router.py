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

EMERGENCY_FREE_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"

MODEL_PRICING = {
    **{
        tier.model_id: (tier.input_cost_per_m, tier.output_cost_per_m)
        for tier in MODEL_TIERS.values()
    },
    EMERGENCY_FREE_MODEL: (0.0, 0.0),
}

# Fallbacks only move laterally or downward in cost/quality; a cheap or fast
# request can never silently escalate to the Pro reasoning tier.
TIER_FALLBACKS = {
    "cheap": ["qwen/qwen3.7-flash", EMERGENCY_FREE_MODEL],
    "fast": ["openai/gpt-5.6-luna", "qwen/qwen3.7-flash", EMERGENCY_FREE_MODEL],
    "smart": [
        "google/gemini-3-flash-preview",
        "openai/gpt-5.6-luna",
        "qwen/qwen3.7-flash",
        EMERGENCY_FREE_MODEL,
    ],
    "reasoning": [
        "google/gemini-3.1-pro-preview",
        "google/gemini-3-flash-preview",
        "openai/gpt-5.6-luna",
        EMERGENCY_FREE_MODEL,
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


# Circuit breaker: once we see the account's per-key spending limit exceeded,
# stop wasting time (and cascading debate-loop latency) retrying paid models
# that will just 403 again. Skip straight to the free fallback until the
# cooldown expires, so the client's key-limit issue doesn't also make every
# task feel broken/slow on top of costing them nothing extra to fix.
_key_limit_exhausted_until: float = 0.0
_KEY_LIMIT_COOLDOWN_SECONDS = 600  # retry paid tiers again every 10 minutes


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
    import time
    global _key_limit_exhausted_until

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

    if time.monotonic() < _key_limit_exhausted_until:
        # Known-exhausted right now: go straight to the guaranteed-free model.
        candidate_models = [EMERGENCY_FREE_MODEL]

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

                if model_id != EMERGENCY_FREE_MODEL:
                    # A paid model just worked, so the key limit (if it was
                    # tripped before) is no longer blocking us. Clear the breaker.
                    _key_limit_exhausted_until = 0.0

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
                # A key spending-limit 403 will not recover on retry; move straight
                # to the next approved fallback (ultimately the free emergency model),
                # and trip the breaker so subsequent calls skip the paid tiers
                # entirely for a while instead of re-discovering the same 403s.
                if getattr(e, "status_code", None) == 403:
                    if "key limit" in str(e).lower() or "limit exceeded" in str(e).lower():
                        _key_limit_exhausted_until = time.monotonic() + _KEY_LIMIT_COOLDOWN_SECONDS
                    break
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


def get_model_router_status() -> dict:
    """
    Report whether we're currently forced onto the free emergency model due
    to the OpenRouter key's spending limit, so the dashboard/Telegram can
    tell the client honestly why responses might be slower/lower-quality
    right now instead of silently degrading.
    """
    import time
    remaining = _key_limit_exhausted_until - time.monotonic()
    degraded = remaining > 0
    return {
        "degraded": degraded,
        "reason": "OpenRouter key spending limit exceeded — running on free fallback model only"
        if degraded else "Normal (cost-efficient paid models)",
        "retry_paid_models_in_seconds": max(0, int(remaining)) if degraded else 0,
    }
