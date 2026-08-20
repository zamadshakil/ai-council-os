"""Encrypted, write-only integration credential storage.

Secrets are encrypted with a deployment-owned Fernet key and never serialized
back to the browser, logs, audit events, workflow payloads, or job results.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select

from src.core.database import async_session
from src.core.integration_models import (
    CouncilIntegrationModel,
    IntegrationConnectionModel,
    WorkflowIntegrationModel,
)
from src.core.models import WorkflowDefinitionModel


@dataclass(frozen=True)
class CredentialField:
    key: str
    label: str
    env_name: str
    required: bool = True
    secret: bool = True
    help_text: str = ""
    internal: bool = False


@dataclass(frozen=True)
class ProviderSpec:
    provider: str
    display_name: str
    description: str
    fields: tuple[CredentialField, ...]


PROVIDERS: dict[str, ProviderSpec] = {
    "openrouter": ProviderSpec("openrouter", "OpenRouter", "Approved AI model gateway.", (
        CredentialField("api_key", "API key", "OPENROUTER_API_KEY"),
    )),
    "telegram": ProviderSpec("telegram", "Telegram", "Administrator controls and approval alerts.", (
        CredentialField("bot_token", "Bot token", "TELEGRAM_BOT_TOKEN"),
        CredentialField("admin_chat_id", "Administrator chat ID", "TELEGRAM_ALLOWED_CHAT_IDS", secret=False),
        CredentialField("webhook_secret", "Webhook secret", "TELEGRAM_WEBHOOK_SECRET", required=False),
    )),
    "youtube": ProviderSpec("youtube", "YouTube", "Comment discovery, replies, captions, and descriptions.", (
        CredentialField("channel_id", "Channel ID", "YOUTUBE_CHANNEL_ID", secret=False),
        CredentialField("api_key", "API key", "YOUTUBE_API_KEY", required=False),
        CredentialField("oauth_token_json", "OAuth token JSON", "YOUTUBE_OAUTH_TOKEN_JSON"),
        CredentialField("webhook_secret", "Webhook secret", "YOUTUBE_WEBHOOK_SECRET", required=False),
    )),
    "reddit": ProviderSpec("reddit", "Reddit", "Lead discovery with manual posting.", (
        CredentialField("client_id", "Client ID", "REDDIT_CLIENT_ID"),
        CredentialField("client_secret", "Client secret", "REDDIT_CLIENT_SECRET"),
        CredentialField("user_agent", "User agent", "REDDIT_USER_AGENT", secret=False),
    )),
    "x": ProviderSpec("x", "X / Twitter", "Approved X publishing destination.", (
        CredentialField("api_key", "API key", "TWITTER_API_KEY"),
        CredentialField("api_secret", "API secret", "TWITTER_API_SECRET"),
        CredentialField("access_token", "Access token", "TWITTER_ACCESS_TOKEN"),
        CredentialField("access_secret", "Access secret", "TWITTER_ACCESS_SECRET"),
        CredentialField("bearer_token", "Bearer token", "TWITTER_BEARER_TOKEN", required=False),
    )),
    "linkedin": ProviderSpec("linkedin", "LinkedIn", "Approved person or organization publishing.", (
        CredentialField("access_token", "Access token", "LINKEDIN_ACCESS_TOKEN"),
        CredentialField("person_id", "Person ID", "LINKEDIN_PERSON_ID", required=False, secret=False),
        CredentialField("organization_id", "Organization ID", "LINKEDIN_ORGANIZATION_ID", required=False, secret=False),
    )),
    "meta": ProviderSpec("meta", "Meta", "Facebook and Instagram publishing.", (
        CredentialField("access_token", "Access token", "META_ACCESS_TOKEN"),
        CredentialField("app_id", "Meta app ID", "META_APP_ID", required=False, secret=False),
        CredentialField("app_secret", "App secret", "META_APP_SECRET"),
        CredentialField("facebook_page_id", "Facebook Page ID", "FACEBOOK_PAGE_ID", required=False, secret=False),
        CredentialField("instagram_business_id", "Instagram Business ID", "INSTAGRAM_BUSINESS_ID", required=False, secret=False),
        CredentialField("webhook_verify_token", "Webhook verify token", "META_WEBHOOK_VERIFY_TOKEN", required=False),
        CredentialField("api_version", "Graph API version", "META_GRAPH_API_VERSION", required=False, secret=False, help_text="For example v23.0"),
    )),
    "runpod": ProviderSpec("runpod", "RunPod", "Cloud GPU control and authenticated Blender template jobs.", (
        CredentialField("api_key", "API key", "RUNPOD_API_KEY"),
        CredentialField("agent_token", "Blender agent token", "BLENDER_AGENT_TOKEN", required=False, internal=True),
        CredentialField("kasm_password", "Kasm password", "VNC_PW", required=False, internal=True),
        CredentialField("agent_port", "Blender agent proxy port", "BLENDER_AGENT_PORT", required=False, secret=False, internal=True),
        CredentialField("workspace_root", "Pod workspace root", "BLENDER_WORKSPACE_ROOT", required=False, secret=False, internal=True),
    )),
    "discord": ProviderSpec("discord", "Discord", "Approved Discord webhook publishing.", (
        CredentialField("webhook_url", "Webhook URL", "DISCORD_WEBHOOK_URL"),
    )),
    "hubspot": ProviderSpec(
        "hubspot",
        "HubSpot CRM",
        "Sync approved Sales Council leads to HubSpot contacts with an audited outreach note.",
        (
            CredentialField(
                "access_token",
                "Private app access token",
                "HUBSPOT_ACCESS_TOKEN",
                help_text=(
                    "In HubSpot Development, create a Legacy private app with "
                    "crm.objects.contacts.read and crm.objects.contacts.write scopes."
                ),
            ),
        ),
    ),
}

WORKFLOW_ALLOWED_PROVIDERS: dict[str, set[str]] = {
    "telegram_control": {"telegram", "openrouter"},
    "youtube_comments": {"youtube", "openrouter"},
    "reddit_prospector": {"reddit", "openrouter", "hubspot"},
    "youtube_descriptions": {"youtube", "openrouter"},
    "content_engine": {"openrouter", "x", "linkedin", "meta", "discord"},
    "instagram_comments": {"openrouter", "meta"},
}

COUNCIL_ALLOWED_PROVIDERS: dict[str, set[str]] = {
    "sales": {"hubspot"},
}

WORKFLOW_REQUIRED_PROVIDERS: dict[str, set[str]] = {
    "telegram_control": {"telegram"},
    "youtube_comments": {"youtube", "openrouter"},
    "reddit_prospector": {"reddit", "openrouter"},
    "youtube_descriptions": {"youtube", "openrouter"},
    "content_engine": {"openrouter"},
    "instagram_comments": {"openrouter", "meta"},
}


class VaultConfigurationError(RuntimeError):
    pass


def _fernet() -> Fernet:
    raw = os.getenv("INTEGRATION_ENCRYPTION_KEY", "").strip().encode("ascii")
    if not raw:
        raise VaultConfigurationError("Integration vault encryption is not configured")
    try:
        return Fernet(raw)
    except (ValueError, TypeError) as exc:
        raise VaultConfigurationError(
            "INTEGRATION_ENCRYPTION_KEY must be a valid Fernet key"
        ) from exc


def validate_encryption_key() -> None:
    """Fail startup without exposing or deriving the deployment-owned key."""
    _fernet()


def _fingerprint(provider: str, credentials: Mapping[str, str]) -> str:
    canonical = json.dumps(
        {"provider": provider, "credentials": dict(sorted(credentials.items()))},
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _encrypt(credentials: Mapping[str, str]) -> str:
    payload = json.dumps(dict(credentials), separators=(",", ":"), sort_keys=True)
    return _fernet().encrypt(payload.encode("utf-8")).decode("ascii")


def _decrypt(token: str) -> dict[str, str]:
    try:
        payload = _fernet().decrypt(token.encode("ascii"))
        decoded = json.loads(payload.decode("utf-8"))
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise VaultConfigurationError("Stored integration credentials cannot be decrypted") from exc
    if not isinstance(decoded, dict):
        raise VaultConfigurationError("Stored integration credential payload is invalid")
    return {str(key): str(value) for key, value in decoded.items()}


def _validate(provider: str, credentials: Mapping[str, Any]) -> dict[str, str]:
    spec = PROVIDERS.get(provider)
    if spec is None:
        raise ValueError("Unsupported integration provider")
    allowed = {field.key for field in spec.fields}
    unknown = sorted(set(credentials) - allowed)
    if unknown:
        raise ValueError(f"Unknown credential fields: {', '.join(unknown)}")
    normalized = {
        key: str(value).strip()
        for key, value in credentials.items()
        if value is not None and str(value).strip()
    }
    missing = [field.label for field in spec.fields if field.required and not normalized.get(field.key)]
    if provider == "linkedin" and not (
        normalized.get("person_id") or normalized.get("organization_id")
    ):
        missing.append("Person ID or Organization ID")
    if provider == "meta" and not (
        normalized.get("facebook_page_id") or normalized.get("instagram_business_id")
    ):
        missing.append("Facebook Page ID or Instagram Business ID")
    if missing:
        raise ValueError(f"Missing required credentials: {', '.join(missing)}")
    return normalized


def catalog_shape() -> list[dict[str, Any]]:
    return [
        {
            "id": spec.provider,
            "display_name": spec.display_name,
            "description": spec.description,
            "fields": [
                {
                    "key": field.key,
                    "label": field.label,
                    "required": field.required,
                    "secret": field.secret,
                    "help_text": field.help_text,
                }
                for field in spec.fields if not field.internal
            ],
        }
        for spec in PROVIDERS.values()
    ]


async def list_connections() -> list[dict[str, Any]]:
    async with async_session() as session:
        rows = (await session.execute(select(IntegrationConnectionModel))).scalars().all()
        links = (await session.execute(select(WorkflowIntegrationModel))).scalars().all()
        council_links = (
            await session.execute(select(CouncilIntegrationModel))
        ).scalars().all()
    by_provider = {row.provider: row for row in rows}
    workflows: dict[str, list[str]] = {}
    for link in links:
        workflows.setdefault(link.provider, []).append(link.workflow_id)
    councils: dict[str, list[str]] = {}
    for link in council_links:
        councils.setdefault(link.provider, []).append(link.council_id)
    result: list[dict[str, Any]] = []
    for item in catalog_shape():
        row = by_provider.get(item["id"])
        result.append({
            **item,
            "configured": row is not None,
            "configured_fields": sorted(row.credential_fields or []) if row else [],
            "status": row.status if row else "not_configured",
            "last_error": row.last_error if row else "",
            "verified_at": row.verified_at.isoformat() if row and row.verified_at else None,
            "version": row.version if row else 0,
            "linked_workflows": sorted(workflows.get(item["id"], [])),
            "linked_councils": sorted(councils.get(item["id"], [])),
        })
    return result


async def put_credentials(
    provider: str,
    credentials: Mapping[str, Any],
    *,
    display_name: str = "",
) -> IntegrationConnectionModel:
    normalized = _validate(provider, credentials)
    spec = PROVIDERS[provider]
    async with async_session() as session:
        row = await session.get(IntegrationConnectionModel, provider, with_for_update=True)
        if provider == "runpod":
            previous = _decrypt(row.encrypted_credentials) if row is not None else {}
            normalized.update({
                "agent_token": previous.get("agent_token") or secrets.token_urlsafe(48),
                "kasm_password": previous.get("kasm_password") or secrets.token_urlsafe(18),
                "agent_port": previous.get("agent_port") or "8001",
                "workspace_root": previous.get("workspace_root") or "/workspace",
            })
        if row is None:
            row = IntegrationConnectionModel(
                provider=provider,
                display_name=display_name.strip() or spec.display_name,
                encrypted_credentials=_encrypt(normalized),
                credential_fields=sorted(normalized),
                credential_fingerprint=_fingerprint(provider, normalized),
                status="configured",
            )
            session.add(row)
        else:
            row.display_name = display_name.strip() or row.display_name or spec.display_name
            row.encrypted_credentials = _encrypt(normalized)
            row.credential_fields = sorted(normalized)
            row.credential_fingerprint = _fingerprint(provider, normalized)
            row.status = "configured"
            row.last_error = ""
            row.verified_at = None
            row.version += 1
        linked_ids = (await session.execute(
            select(WorkflowIntegrationModel.workflow_id).where(
                WorkflowIntegrationModel.provider == provider
            )
        )).scalars().all()
        if linked_ids:
            definitions = (await session.execute(
                select(WorkflowDefinitionModel).where(WorkflowDefinitionModel.id.in_(linked_ids))
            )).scalars().all()
            for definition in definitions:
                definition.credential_status = "untested"
                definition.is_enabled = False
                definition.version += 1
        await session.commit()
        await session.refresh(row)
        return row


async def delete_credentials(provider: str) -> bool:
    async with async_session() as session:
        row = await session.get(IntegrationConnectionModel, provider, with_for_update=True)
        if row is None:
            return False
        linked_ids = (await session.execute(
            select(WorkflowIntegrationModel.workflow_id).where(
                WorkflowIntegrationModel.provider == provider
            )
        )).scalars().all()
        if linked_ids:
            definitions = (await session.execute(
                select(WorkflowDefinitionModel).where(WorkflowDefinitionModel.id.in_(linked_ids))
            )).scalars().all()
            for definition in definitions:
                definition.credential_status = "untested"
                definition.is_enabled = False
                definition.version += 1
        # Explicitly remove links so behavior is consistent on SQLite, where
        # foreign-key cascades are not guaranteed to be enabled by every tool.
        await session.execute(delete(WorkflowIntegrationModel).where(
            WorkflowIntegrationModel.provider == provider
        ))
        await session.execute(delete(CouncilIntegrationModel).where(
            CouncilIntegrationModel.provider == provider
        ))
        await session.delete(row)
        await session.commit()
        return True


async def mark_verification(provider: str, ok: bool, error: str = "") -> None:
    async with async_session() as session:
        row = await session.get(IntegrationConnectionModel, provider, with_for_update=True)
        if row is None:
            raise ValueError("Integration is not configured")
        row.status = "verified" if ok else "failed"
        row.last_error = "" if ok else error[:1000]
        row.verified_at = datetime.now(timezone.utc) if ok else None
        row.version += 1
        linked_ids = (await session.execute(
            select(WorkflowIntegrationModel.workflow_id).where(
                WorkflowIntegrationModel.provider == provider
            )
        )).scalars().all()
        for workflow_id in linked_ids:
            definition = await session.get(WorkflowDefinitionModel, workflow_id, with_for_update=True)
            if definition is None:
                continue
            linked_rows = (await session.execute(
                select(WorkflowIntegrationModel.provider, IntegrationConnectionModel.status)
                .join(
                    IntegrationConnectionModel,
                    IntegrationConnectionModel.provider == WorkflowIntegrationModel.provider,
                )
                .where(WorkflowIntegrationModel.workflow_id == workflow_id)
            )).all()
            verified_providers = {
                linked_provider for linked_provider, status in linked_rows if status == "verified"
            }
            ready = WORKFLOW_REQUIRED_PROVIDERS.get(workflow_id, set()).issubset(
                verified_providers
            )
            definition.credential_status = "verified" if ready else "untested"
            if not ready:
                definition.is_enabled = False
            definition.version += 1
        await session.commit()


async def workflow_connections_verified(workflow_id: str) -> bool:
    """Re-check required linked providers at the point of use."""
    required = WORKFLOW_REQUIRED_PROVIDERS.get(workflow_id)
    if required is None:
        return False
    async with async_session() as session:
        rows = (await session.execute(
            select(WorkflowIntegrationModel.provider, IntegrationConnectionModel.status)
            .join(
                IntegrationConnectionModel,
                IntegrationConnectionModel.provider == WorkflowIntegrationModel.provider,
            )
            .where(WorkflowIntegrationModel.workflow_id == workflow_id)
        )).all()
    verified = {provider for provider, status in rows if status == "verified"}
    return bool(rows) and required.issubset(verified)


async def decrypted_provider_env(provider: str, *, require_verified: bool = True) -> dict[str, str]:
    async with async_session() as session:
        row = await session.get(IntegrationConnectionModel, provider)
    if row is None:
        raise VaultConfigurationError(f"{provider} is not configured")
    if require_verified and row.status != "verified":
        raise VaultConfigurationError(f"{provider} credentials are not verified")
    values = _decrypt(row.encrypted_credentials)
    if _fingerprint(provider, values) != row.credential_fingerprint:
        raise VaultConfigurationError(f"{provider} credential integrity check failed")
    mapping = {field.key: field.env_name for field in PROVIDERS[provider].fields}
    return {mapping[key]: value for key, value in values.items() if key in mapping}


async def set_workflow_links(workflow_id: str, providers: list[str]) -> list[str]:
    allowed = WORKFLOW_ALLOWED_PROVIDERS.get(workflow_id)
    if allowed is None:
        raise ValueError("Unsupported workflow")
    normalized = list(dict.fromkeys(providers))
    invalid = sorted(set(normalized) - allowed)
    if invalid:
        raise ValueError(f"Providers are not supported by this workflow: {', '.join(invalid)}")
    missing_required = sorted(WORKFLOW_REQUIRED_PROVIDERS[workflow_id] - set(normalized))
    if missing_required:
        raise ValueError(f"Required providers cannot be unlinked: {', '.join(missing_required)}")
    async with async_session() as session:
        configured = set((await session.execute(
            select(IntegrationConnectionModel.provider).where(
                IntegrationConnectionModel.provider.in_(normalized)
            )
        )).scalars().all())
        not_configured = sorted(set(normalized) - configured)
        if not_configured:
            raise ValueError(f"Configure providers before linking: {', '.join(not_configured)}")
        await session.execute(delete(WorkflowIntegrationModel).where(
            WorkflowIntegrationModel.workflow_id == workflow_id
        ))
        session.add_all([
            WorkflowIntegrationModel(workflow_id=workflow_id, provider=provider)
            for provider in normalized
        ])
        definition = await session.get(WorkflowDefinitionModel, workflow_id, with_for_update=True)
        if definition:
            verified = set((await session.execute(
                select(IntegrationConnectionModel.provider).where(
                    IntegrationConnectionModel.provider.in_(normalized),
                    IntegrationConnectionModel.status == "verified",
                )
            )).scalars().all())
            required_verified = WORKFLOW_REQUIRED_PROVIDERS[workflow_id].issubset(verified)
            definition.credential_status = "verified" if required_verified else "untested"
            if not required_verified:
                definition.is_enabled = False
            definition.version += 1
        await session.commit()
    return normalized


async def set_council_links(council_id: str, providers: list[str]) -> list[str]:
    """Replace reusable provider links for a council approval destination."""

    council_id = council_id.strip().lower()
    allowed = COUNCIL_ALLOWED_PROVIDERS.get(council_id)
    if allowed is None:
        raise ValueError("Unsupported council integration target")
    normalized = list(dict.fromkeys(providers))
    invalid = sorted(set(normalized) - allowed)
    if invalid:
        raise ValueError(
            f"Providers are not supported by this council: {', '.join(invalid)}"
        )
    async with async_session() as session:
        provider_rows = (await session.execute(
            select(
                IntegrationConnectionModel.provider,
                IntegrationConnectionModel.status,
            ).where(
                IntegrationConnectionModel.provider.in_(normalized)
            )
        )).all() if normalized else []
        configured = {provider for provider, _ in provider_rows}
        not_configured = sorted(set(normalized) - configured)
        if not_configured:
            raise ValueError(
                f"Configure providers before linking: {', '.join(not_configured)}"
            )
        unverified = sorted(
            provider for provider, status in provider_rows if status != "verified"
        )
        if unverified:
            raise ValueError(
                f"Verify providers before linking: {', '.join(unverified)}"
            )
        await session.execute(delete(CouncilIntegrationModel).where(
            CouncilIntegrationModel.council_id == council_id
        ))
        session.add_all([
            CouncilIntegrationModel(council_id=council_id, provider=provider)
            for provider in normalized
        ])
        await session.commit()
    return normalized


async def provider_linked_to_target(
    provider: str,
    *,
    workflow_id: str = "",
    council_id: str = "",
) -> bool:
    """Return whether a provider remains explicitly linked at point of use."""

    async with async_session() as session:
        if workflow_id:
            row = await session.get(
                WorkflowIntegrationModel,
                {"workflow_id": workflow_id, "provider": provider},
            )
            return row is not None
        if council_id:
            row = await session.get(
                CouncilIntegrationModel,
                {"council_id": council_id, "provider": provider},
            )
            return row is not None
    return False


async def workflow_environment(workflow_id: str) -> dict[str, str]:
    async with async_session() as session:
        links = (await session.execute(
            select(WorkflowIntegrationModel.provider).where(
                WorkflowIntegrationModel.workflow_id == workflow_id
            )
        )).scalars().all()
    merged: dict[str, str] = {}
    required = WORKFLOW_REQUIRED_PROVIDERS.get(workflow_id, set())
    for provider in links:
        try:
            merged.update(await decrypted_provider_env(provider))
        except VaultConfigurationError:
            if provider in required:
                raise
    return merged
