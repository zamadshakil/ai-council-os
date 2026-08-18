"""Encrypted integration connections and reusable workflow links."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models import Base, TimestampMixin, utcnow


class IntegrationConnectionModel(Base, TimestampMixin):
    __tablename__ = "integration_connections"

    provider: Mapped[str] = mapped_column(String(50), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120))
    encrypted_credentials: Mapped[str] = mapped_column(Text)
    credential_fields: Mapped[list] = mapped_column(JSON, default=list)
    credential_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(30), default="configured")
    last_error: Mapped[str] = mapped_column(Text, default="")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(default=1)


class WorkflowIntegrationModel(Base):
    __tablename__ = "workflow_integrations"

    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_definitions.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(
        ForeignKey("integration_connections.provider", ondelete="CASCADE"), primary_key=True
    )
    purpose: Mapped[str] = mapped_column(String(80), default="primary")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CouncilIntegrationModel(Base):
    """Reusable provider links for approval-driven council destinations."""

    __tablename__ = "council_integrations"

    council_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    provider: Mapped[str] = mapped_column(
        ForeignKey("integration_connections.provider", ondelete="CASCADE"),
        primary_key=True,
    )
    purpose: Mapped[str] = mapped_column(String(80), default="approved_output")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
