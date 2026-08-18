"""Validated public request/response contracts for AI Council OS."""

from __future__ import annotations

from typing import Any, Literal
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


CouncilName = Literal["grant", "sales", "content"]
PriorityName = Literal["normal", "high"]
ApprovalAction = Literal["approve", "reject", "retry", "cancel"]
SchedulePreset = Literal[
    "manual",
    "every_5_minutes",
    "every_15_minutes",
    "every_30_minutes",
    "hourly",
    "every_3_hours",
    "every_6_hours",
    "every_12_hours",
    "daily",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginRequest(StrictModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


class CouncilRunRequest(StrictModel):
    council: CouncilName
    task_description: str = Field(min_length=3, max_length=50_000)
    context: dict[str, Any] = Field(default_factory=dict)
    priority: PriorityName = "normal"
    selected_document_hashes: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("selected_document_hashes")
    @classmethod
    def unique_document_hashes(cls, value: list[str]) -> list[str]:
        invalid = [item for item in value if not re.fullmatch(r"[a-fA-F0-9]{64}", item)]
        if invalid:
            raise ValueError("Selected document hashes must be 64 hexadecimal characters")
        return list(dict.fromkeys(value))


class ApprovalActionRequest(StrictModel):
    action: ApprovalAction
    expected_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    edited_output: str = Field(default="", max_length=200_000)
    notes: str = Field(default="", max_length=5_000)


class LegacyApprovalRequest(StrictModel):
    approved: bool
    edited_output: str = Field(default="", max_length=200_000)
    notes: str = Field(default="", max_length=5_000)
    expected_version: int = Field(default=0, ge=0)
    idempotency_key: str = Field(default="", max_length=128)


class WorkflowPatchRequest(StrictModel):
    enabled: bool | None = None
    paused: bool | None = None
    schedule_preset: SchedulePreset | None = None
    custom_prompt: str | None = Field(default=None, max_length=20_000)
    selected_document_hashes: list[str] | None = Field(default=None, max_length=50)

    @field_validator("selected_document_hashes")
    @classmethod
    def validate_document_hashes(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if any(not re.fullmatch(r"[a-fA-F0-9]{64}", item) for item in value):
            raise ValueError("Selected document hashes must be 64 hexadecimal characters")
        return list(dict.fromkeys(value))


class WorkflowTriggerRequest(StrictModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class ContentEngineRequest(StrictModel):
    video_title: str = Field(min_length=1, max_length=500)
    transcript: str = Field(min_length=20, max_length=500_000)
    video_id: str = Field(default="", max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IntegrationCredentialsRequest(StrictModel):
    display_name: str = Field(default="", max_length=120)
    credentials: dict[str, Any] = Field(min_length=1, max_length=20)


class WorkflowIntegrationLinksRequest(StrictModel):
    providers: list[str] = Field(min_length=1, max_length=10)

    @field_validator("providers")
    @classmethod
    def normalize_providers(cls, value: list[str]) -> list[str]:
        normalized = [item.strip().lower() for item in value]
        if any(not re.fullmatch(r"[a-z0-9_-]{1,50}", item) for item in normalized):
            raise ValueError("Invalid integration provider identifier")
        return list(dict.fromkeys(normalized))


class KillSwitchRequest(StrictModel):
    active: bool
    reason: str = Field(default="", max_length=500)


class BlenderPodActionRequest(StrictModel):
    action: Literal["resume", "stop"]


class BlenderTemplateJobRequest(StrictModel):
    pod_id: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    source_path: str = Field(min_length=7, max_length=500)
    output_name: str = Field(
        min_length=7,
        max_length=126,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.blend$",
    )
    frame: int = Field(default=1, ge=0, le=1_000_000)
    samples: int = Field(default=64, ge=1, le=4096)
    resolution_percent: int = Field(default=25, ge=1, le=100)
    auto_stop: bool = True
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if not normalized.lower().endswith(".blend"):
            raise ValueError("Source path must point to a .blend file")
        if any(part == ".." for part in normalized.split("/")):
            raise ValueError("Source path cannot contain parent-directory traversal")
        return normalized


class StableError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
