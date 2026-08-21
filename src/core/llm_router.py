"""Strict OpenRouter gateway for the three production councils.

There is intentionally no provider fallback and no generic model override. A
request either runs on the model assigned to its council/role or fails loudly.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError
from src.core.integration_context import integration_value


@dataclass(frozen=True)
class CouncilModelProfile:
    generator: str
    critic: str


COUNCIL_MODEL_PROFILES: dict[str, CouncilModelProfile] = {
    "grant": CouncilModelProfile(
        # Long, high-stakes drafts use Luna's higher-reasoning mode. It is the
        # same low-cost base model, while the critic stays on another provider
        # so the generator is not grading its own work.
        generator="openai/gpt-5.6-luna-pro",
        critic="google/gemini-3.7-flash",
    ),
    "sales": CouncilModelProfile(
        generator="openai/gpt-5.6-luna",
        critic="google/gemini-3.7-flash",
    ),
    "content": CouncilModelProfile(
        generator="google/gemini-3.7-flash",
        critic="openai/gpt-5.6-luna",
    ),
}

APPROVED_MODELS = frozenset(
    model_id
    for profile in COUNCIL_MODEL_PROFILES.values()
    for model_id in (profile.generator, profile.critic)
)
BRAIN_MODEL = "google/gemini-3.7-flash"
OPERATIONAL_MODELS = APPROVED_MODELS | {BRAIN_MODEL}

# Compatibility names are deliberately mapped only to approved models. New
# production code should call ``get_council_model`` instead of selecting tiers.
_COMPATIBILITY_TIERS = {
    "fast": "openai/gpt-5.6-luna",
    "smart": "google/gemini-3.7-flash",
    "reasoning": "openai/gpt-5.6-luna-pro",
}


class ModelPolicyError(ValueError):
    """Raised when code requests an unapproved council or model."""


class StructuredOutputError(ValueError):
    """Raised when OpenRouter does not return the required JSON contract."""


def get_council_model(council: str, role: str) -> str:
    """Return the immutable model assignment for a production council role."""
    council_key = council.strip().lower()
    role_key = role.strip().lower()
    try:
        profile = COUNCIL_MODEL_PROFILES[council_key]
    except KeyError as exc:
        raise ModelPolicyError(
            f"Unsupported council {council!r}; allowed councils are grant, sales, and content."
        ) from exc
    if role_key not in {"generator", "critic"}:
        raise ModelPolicyError("Council role must be 'generator' or 'critic'.")
    return getattr(profile, role_key)


def assert_approved_model(model_id: str) -> str:
    """Validate and return a model ID without applying any substitution."""
    if model_id not in OPERATIONAL_MODELS:
        raise ModelPolicyError(f"Model {model_id!r} is not in the production allowlist.")
    return model_id


_client: AsyncOpenAI | None = None
_client_credential_fingerprint = ""


def get_client() -> AsyncOpenAI:
    """Create the OpenRouter OpenAI-compatible client from process environment."""
    global _client, _client_credential_fingerprint, _model_validation_cache
    api_key = integration_value("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is not configured.")
    credential_fingerprint = hashlib.sha256(api_key.encode()).hexdigest()
    if _client is None or not hmac.compare_digest(
        _client_credential_fingerprint, credential_fingerprint
    ):
        _client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=45.0,
            default_headers={
                "HTTP-Referer": integration_value("PUBLIC_APP_URL", "https://councilos.invalid"),
                "X-Title": "AI Council OS",
            },
        )
        _client_credential_fingerprint = credential_fingerprint
        _model_validation_cache = None
    return _client


def _read_usage_value(usage: Any, name: str, default: Any = None) -> Any:
    if usage is None:
        return default
    value = getattr(usage, name, None)
    if value is not None:
        return value
    if isinstance(usage, dict):
        return usage.get(name, default)
    extra = getattr(usage, "model_extra", None) or {}
    return extra.get(name, default)


def _extract_provider_cost(usage: Any) -> tuple[float | None, str]:
    """Return OpenRouter's reported cost; never estimate with stale price tables."""
    raw_cost = _read_usage_value(usage, "cost")
    if raw_cost is None:
        details = _read_usage_value(usage, "cost_details", {}) or {}
        if isinstance(details, dict):
            raw_cost = details.get("upstream_inference_cost")
    if raw_cost is None:
        return None, "unavailable"
    try:
        return round(float(raw_cost), 8), "provider_reported"
    except (TypeError, ValueError):
        return None, "unavailable"


def _response_metrics(response: Any, model_id: str) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    cost_usd, cost_source = _extract_provider_cost(usage)
    return {
        "model": getattr(response, "model", None) or model_id,
        "input_tokens": int(_read_usage_value(usage, "prompt_tokens", 0) or 0),
        "output_tokens": int(_read_usage_value(usage, "completion_tokens", 0) or 0),
        "cost_usd": cost_usd,
        "cost_source": cost_source,
        "provider_request_id": getattr(response, "id", None),
    }


def _is_retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    return status is None or status == 429 or (isinstance(status, int) and status >= 500)


async def _create_completion(
    *,
    messages: list[dict[str, str]],
    model_id: str,
    temperature: float,
    max_tokens: int,
    response_format: dict[str, Any] | None = None,
) -> Any:
    assert_approved_model(model_id)
    kwargs: dict[str, Any] = {
        "model": model_id,
        "messages": cast(Any, messages),
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            return await get_client().chat.completions.create(**kwargs)
        except Exception as exc:  # SDK exposes several transport subclasses
            last_error = exc
            if attempt == 1 or not _is_retryable(exc):
                raise
            await asyncio.sleep(0.5)
    assert last_error is not None
    raise last_error


async def call_llm(
    messages: list[dict[str, str]],
    tier: str = "fast",
    model_override: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Compatibility text call restricted to the production allowlist."""
    if model_override:
        model_id = assert_approved_model(model_override)
    else:
        try:
            model_id = _COMPATIBILITY_TIERS[tier]
        except KeyError as exc:
            raise ModelPolicyError(
                f"Tier {tier!r} is not supported; pass an approved explicit model."
            ) from exc
    response = await _create_completion(
        messages=messages,
        model_id=model_id,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content or ""
    if not content.strip():
        raise StructuredOutputError(f"Model {model_id} returned an empty response.")
    return {"content": content, **_response_metrics(response, model_id)}


OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


async def call_llm_structured(
    *,
    messages: list[dict[str, str]],
    model_id: str,
    output_model: type[OutputModelT],
    response_schema: dict[str, Any] | None = None,
    temperature: float = 0.4,
    max_tokens: int = 4096,
) -> tuple[OutputModelT, dict[str, Any]]:
    """Call one approved model and validate its response against a JSON schema.

    Providers occasionally return syntactically valid JSON that still misses a
    length, key, or type constraint. One bounded repair call is allowed for
    that specific case. It uses the same approved model, records the tokens and
    cost of both calls, and never silently swaps providers or schemas.
    """
    schema = response_schema or output_model.model_json_schema()
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": output_model.__name__.lower(),
            "strict": True,
            "schema": schema,
        },
    }
    response = await _create_completion(
        messages=messages,
        model_id=model_id,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
    )
    content = response.choices[0].message.content or ""
    if not content.strip():
        raise StructuredOutputError(f"Model {model_id} returned an empty response.")
    first_metrics = _response_metrics(response, model_id)
    try:
        parsed = output_model.model_validate(json.loads(content))
    except (json.JSONDecodeError, ValidationError) as exc:
        repair_messages = [
            {
                "role": "system",
                "content": (
                    "Repair the candidate JSON so it exactly satisfies the supplied response schema. "
                    "Preserve the intended meaning, enforce every required key and character limit, "
                    "remove unexpected keys, and return only the repaired structured response."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"VALIDATION ERROR:\n{str(exc)[:4000]}\n\n"
                    f"REQUIRED JSON SCHEMA:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
                    f"CANDIDATE JSON:\n{content}"
                ),
            },
        ]
        repair_response = await _create_completion(
            messages=repair_messages,
            model_id=model_id,
            temperature=0.0,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        repaired_content = repair_response.choices[0].message.content or ""
        try:
            parsed = output_model.model_validate(json.loads(repaired_content))
        except (json.JSONDecodeError, ValidationError) as repair_exc:
            raise StructuredOutputError(
                f"Model {model_id} returned output that failed {output_model.__name__} "
                "validation, including one bounded repair attempt."
            ) from repair_exc

        repair_metrics = _response_metrics(repair_response, model_id)
        first_cost = first_metrics.get("cost_usd")
        repair_cost = repair_metrics.get("cost_usd")
        combined_cost = (
            round(float(first_cost) + float(repair_cost), 8)
            if first_cost is not None and repair_cost is not None
            else None
        )
        return parsed, {
            "content": repaired_content,
            "model": repair_metrics["model"],
            "input_tokens": first_metrics["input_tokens"] + repair_metrics["input_tokens"],
            "output_tokens": first_metrics["output_tokens"] + repair_metrics["output_tokens"],
            "cost_usd": combined_cost,
            "cost_source": "provider_reported" if combined_cost is not None else "unavailable",
            "provider_request_id": repair_metrics.get("provider_request_id"),
            "schema_repair_attempted": True,
        }
    return parsed, {"content": content, **first_metrics, "schema_repair_attempted": False}


_model_validation_cache: tuple[float, dict[str, Any]] | None = None


async def validate_approved_models(*, cache_seconds: int = 300) -> dict[str, Any]:
    """Readiness check that proves all configured model IDs exist on OpenRouter."""
    global _model_validation_cache
    now = time.monotonic()
    if _model_validation_cache and now - _model_validation_cache[0] < cache_seconds:
        return _model_validation_cache[1]
    response = await get_client().models.list()
    available = {item.id for item in response.data}
    missing = sorted(OPERATIONAL_MODELS - available)
    result = {
        "ready": not missing,
        "approved_models": sorted(OPERATIONAL_MODELS),
        "missing_models": missing,
    }
    _model_validation_cache = (now, result)
    return result


def list_available_models() -> list[dict[str, str]]:
    """List the immutable council-role assignments."""
    return [
        {"council": council, "role": role, "model": getattr(profile, role)}
        for council, profile in COUNCIL_MODEL_PROFILES.items()
        for role in ("generator", "critic")
    ]


def get_model_router_status() -> dict[str, Any]:
    """Synchronous policy status for legacy dashboard callers."""
    return {
        "degraded": False,
        "reason": "Strict model policy active; failures never trigger a model fallback.",
        "retry_paid_models_in_seconds": 0,
        "approved_models": sorted(APPROVED_MODELS),
    }
