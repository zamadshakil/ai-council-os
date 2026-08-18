from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from src.core import integration_vault
from src.core.integration_models import IntegrationConnectionModel
from src.core.models import WorkflowDefinitionModel


@pytest.mark.asyncio
async def test_credentials_are_encrypted_write_only_and_rotation_disables_workflow(
    session_factory, monkeypatch
):
    monkeypatch.setenv(
        "INTEGRATION_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii")
    )
    monkeypatch.setattr(integration_vault, "async_session", session_factory)

    async with session_factory() as session:
        session.add(WorkflowDefinitionModel(
            id="content_engine",
            display_name="Content Engine",
            is_enabled=False,
            credential_status="untested",
        ))
        await session.commit()

    secret = "portal-secret-openrouter-key"
    await integration_vault.put_credentials("openrouter", {"api_key": secret})
    catalog = await integration_vault.list_connections()
    connection = next(item for item in catalog if item["id"] == "openrouter")
    assert connection["configured"] is True
    assert connection["configured_fields"] == ["api_key"]
    assert secret not in repr(connection)

    async with session_factory() as session:
        stored = await session.get(IntegrationConnectionModel, "openrouter")
        assert stored is not None
        assert secret not in stored.encrypted_credentials

    await integration_vault.mark_verification("openrouter", True)
    assert await integration_vault.set_workflow_links(
        "content_engine", ["openrouter"]
    ) == ["openrouter"]
    async with session_factory() as session:
        workflow = await session.get(WorkflowDefinitionModel, "content_engine")
        assert workflow is not None
        assert workflow.credential_status == "verified"
        workflow.is_enabled = True
        await session.commit()

    resolved = await integration_vault.workflow_environment("content_engine")
    assert resolved == {"OPENROUTER_API_KEY": secret}

    await integration_vault.put_credentials(
        "openrouter", {"api_key": "new-rotated-secret"}
    )
    async with session_factory() as session:
        workflow = await session.get(WorkflowDefinitionModel, "content_engine")
        assert workflow is not None
        assert workflow.credential_status == "untested"
        assert workflow.is_enabled is False

    await integration_vault.mark_verification("openrouter", True)
    assert await integration_vault.workflow_connections_verified("content_engine") is True
    async with session_factory() as session:
        workflow = await session.get(WorkflowDefinitionModel, "content_engine")
        assert workflow is not None
        assert workflow.credential_status == "verified"

    await integration_vault.mark_verification("openrouter", False, "provider rejected key")
    assert await integration_vault.workflow_connections_verified("content_engine") is False
    async with session_factory() as session:
        workflow = await session.get(WorkflowDefinitionModel, "content_engine")
        assert workflow is not None
        assert workflow.credential_status == "untested"
        assert workflow.is_enabled is False


@pytest.mark.asyncio
async def test_workflow_links_require_configured_allowed_providers(
    session_factory, monkeypatch
):
    monkeypatch.setenv(
        "INTEGRATION_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii")
    )
    monkeypatch.setattr(integration_vault, "async_session", session_factory)
    async with session_factory() as session:
        session.add(WorkflowDefinitionModel(
            id="youtube_comments",
            display_name="YouTube comments",
        ))
        await session.commit()

    with pytest.raises(ValueError, match="Required providers"):
        await integration_vault.set_workflow_links("youtube_comments", ["youtube"])

    with pytest.raises(ValueError, match="not supported"):
        await integration_vault.set_workflow_links(
            "youtube_comments", ["youtube", "openrouter", "discord"]
        )

    await integration_vault.put_credentials("openrouter", {"api_key": "key"})
    with pytest.raises(ValueError, match="Configure providers"):
        await integration_vault.set_workflow_links(
            "youtube_comments", ["youtube", "openrouter"]
        )


@pytest.mark.asyncio
async def test_hubspot_council_link_is_encrypted_verified_and_reusable(
    session_factory, monkeypatch
):
    monkeypatch.setenv(
        "INTEGRATION_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii")
    )
    monkeypatch.setattr(integration_vault, "async_session", session_factory)

    secret = "test-hubspot-token-not-a-secret"
    await integration_vault.put_credentials("hubspot", {"access_token": secret})
    with pytest.raises(ValueError, match="Verify providers"):
        await integration_vault.set_council_links("sales", ["hubspot"])

    await integration_vault.mark_verification("hubspot", True)
    assert await integration_vault.set_council_links("sales", ["hubspot"]) == [
        "hubspot"
    ]
    assert await integration_vault.provider_linked_to_target(
        "hubspot", council_id="sales"
    ) is True

    catalog = await integration_vault.list_connections()
    connection = next(item for item in catalog if item["id"] == "hubspot")
    assert connection["linked_councils"] == ["sales"]
    assert secret not in repr(connection)
    assert await integration_vault.decrypted_provider_env("hubspot") == {
        "HUBSPOT_ACCESS_TOKEN": secret
    }

    assert await integration_vault.set_council_links("sales", []) == []
    assert await integration_vault.provider_linked_to_target(
        "hubspot", council_id="sales"
    ) is False
    with pytest.raises(ValueError, match="Unsupported council"):
        await integration_vault.set_council_links("content", ["hubspot"])
