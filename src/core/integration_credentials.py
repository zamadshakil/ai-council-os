"""Fail-closed workflow verification bound to the current credential material."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.core.llm_router import APPROVED_MODELS, validate_approved_models


WORKFLOW_REQUIRED_ENV: dict[str, tuple[str, ...]] = {
    "telegram_control": (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_CHAT_IDS",
        "INTERNAL_SERVICE_TOKEN",
    ),
    "youtube_comments": (
        "OPENROUTER_API_KEY",
        "YOUTUBE_API_KEY",
        "YOUTUBE_CHANNEL_ID",
        "YOUTUBE_OAUTH_TOKEN",
    ),
    "reddit_prospector": (
        "OPENROUTER_API_KEY",
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
    ),
    "youtube_descriptions": (
        "OPENROUTER_API_KEY",
        "YOUTUBE_API_KEY",
        "YOUTUBE_CHANNEL_ID",
        "YOUTUBE_OAUTH_TOKEN",
    ),
    "content_engine": ("OPENROUTER_API_KEY",),
    "instagram_comments": (
        "OPENROUTER_API_KEY",
        "META_ACCESS_TOKEN",
        "INSTAGRAM_BUSINESS_ID",
    ),
}

MODEL_DEPENDENT_WORKFLOWS = frozenset(
    {"youtube_comments", "reddit_prospector", "youtube_descriptions", "content_engine", "instagram_comments"}
)


@dataclass(frozen=True)
class WorkflowVerificationState:
    status: str
    configured: bool
    fingerprint_matches: bool
    models_ready: bool | None
    message: str

    @property
    def verified(self) -> bool:
        return self.status == "verified"


def missing_workflow_configuration(workflow_id: str) -> list[str]:
    missing: list[str] = []
    for name in WORKFLOW_REQUIRED_ENV.get(workflow_id, ()):
        value = os.getenv(name, "").strip()
        if not value:
            missing.append(name)
        elif name == "YOUTUBE_OAUTH_TOKEN" and not Path(value).is_file():
            missing.append(name)
    return missing


def _credential_value_material(name: str) -> dict[str, str]:
    value = os.getenv(name, "").strip()
    material = {"value": value}
    if name == "YOUTUBE_OAUTH_TOKEN" and value:
        token_path = Path(value)
        if token_path.is_file():
            try:
                material["file_sha256"] = hashlib.sha256(token_path.read_bytes()).hexdigest()
            except OSError:
                material["file_sha256"] = "unreadable"
    return material


def workflow_credential_fingerprint(workflow_id: str) -> str:
    """Hash exact required configuration without persisting any credential value."""
    required = WORKFLOW_REQUIRED_ENV.get(workflow_id)
    if required is None or missing_workflow_configuration(workflow_id):
        return ""
    material: dict[str, Any] = {
        "schema": 1,
        "workflow": workflow_id,
        "required_configuration": {
            name: _credential_value_material(name) for name in sorted(required)
        },
    }
    if workflow_id in MODEL_DEPENDENT_WORKFLOWS:
        # A model-policy change invalidates the previous verification even if
        # the OpenRouter key itself did not change.
        material["approved_models"] = sorted(APPROVED_MODELS)
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


async def workflow_verification_state(
    definition: Any,
    *,
    check_models: bool = True,
) -> WorkflowVerificationState:
    """Return effective status, never trusting a stale persisted `verified` flag."""
    workflow_id = str(definition.id)
    if workflow_id not in WORKFLOW_REQUIRED_ENV:
        # Non-production test/custom jobs retain their explicit gate. They are
        # never scheduler-visible through the production workflow registry.
        status = str(definition.credential_status or "untested")
        return WorkflowVerificationState(
            status=status,
            configured=status == "verified",
            fingerprint_matches=status == "verified",
            models_ready=None,
            message="",
        )

    missing = missing_workflow_configuration(workflow_id)
    if missing:
        return WorkflowVerificationState(
            status="unverified",
            configured=False,
            fingerprint_matches=False,
            models_ready=None,
            message="Required configuration is missing",
        )

    settings = dict(definition.settings or {})
    persisted_status = str(definition.credential_status or "untested")
    if persisted_status != "verified":
        return WorkflowVerificationState(
            status=persisted_status,
            configured=True,
            fingerprint_matches=False,
            models_ready=None,
            message=str(settings.get("verification_message", "Not verified")),
        )

    stored_fingerprint = str(settings.get("credential_fingerprint", ""))
    current_fingerprint = workflow_credential_fingerprint(workflow_id)
    fingerprint_matches = bool(
        stored_fingerprint
        and current_fingerprint
        and hmac.compare_digest(stored_fingerprint, current_fingerprint)
    )
    if not fingerprint_matches:
        return WorkflowVerificationState(
            status="unverified",
            configured=True,
            fingerprint_matches=False,
            models_ready=None,
            message="Credentials or required model configuration changed; verify again",
        )

    if check_models and workflow_id in MODEL_DEPENDENT_WORKFLOWS:
        try:
            model_state = await validate_approved_models()
        except Exception as exc:
            return WorkflowVerificationState(
                status="unverified",
                configured=True,
                fingerprint_matches=True,
                models_ready=False,
                message=f"Model readiness check failed: {type(exc).__name__}",
            )
        if not model_state.get("ready"):
            return WorkflowVerificationState(
                status="unverified",
                configured=True,
                fingerprint_matches=True,
                models_ready=False,
                message="One or more required models are unavailable",
            )

    return WorkflowVerificationState(
        status="verified",
        configured=True,
        fingerprint_matches=True,
        models_ready=True if workflow_id in MODEL_DEPENDENT_WORKFLOWS else None,
        message=str(settings.get("verification_message", "Connection verified")),
    )
