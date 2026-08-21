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
    selected_collection_ids: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("selected_document_hashes")
    @classmethod
    def unique_document_hashes(cls, value: list[str]) -> list[str]:
        invalid = [item for item in value if not re.fullmatch(r"[a-fA-F0-9]{64}", item)]
        if invalid:
            raise ValueError("Selected document hashes must be 64 hexadecimal characters")
        return list(dict.fromkeys(value))

    @field_validator("selected_collection_ids")
    @classmethod
    def unique_collection_ids(cls, value: list[str]) -> list[str]:
        if any(not re.fullmatch(r"[A-Za-z0-9-]{8,64}", item) for item in value):
            raise ValueError("Selected collection identifiers are invalid")
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
    # Accepted only so the API can return the stable GRANT_ONLY_SETTING error.
    # Workflow evidence must be configured through the binding endpoint.
    selected_collection_ids: list[str] | None = Field(default=None, max_length=50)

    @field_validator("selected_document_hashes")
    @classmethod
    def validate_document_hashes(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if any(not re.fullmatch(r"[a-fA-F0-9]{64}", item) for item in value):
            raise ValueError("Selected document hashes must be 64 hexadecimal characters")
        return list(dict.fromkeys(value))

    @field_validator("selected_collection_ids")
    @classmethod
    def validate_collection_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if any(not re.fullmatch(r"[A-Za-z0-9-]{8,64}", item) for item in value):
            raise ValueError("Selected collection identifiers are invalid")
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
    providers: list[str] = Field(default_factory=list, max_length=10)

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
    action: Literal["resume", "stop", "prepare_runtime", "reveal_access"]
    inventory_confirmed: bool = False


class BlenderPodProvisionRequest(StrictModel):
    confirm_billing: Literal["CREATE_ONE_A6000_POD"]
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


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


class BlenderRenderJobRequest(StrictModel):
    pod_id: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    source_path: str = Field(min_length=7, max_length=1000)
    render_mode: Literal["kasm_gui", "headless"] = "headless"
    scheduler: Literal["native", "flamenco"] = "native"
    output_profile: Literal["delivery", "compositing"] = "delivery"
    frame_start: int | None = Field(default=None, ge=0, le=1_000_000)
    frame_end: int | None = Field(default=None, ge=0, le=1_000_000)
    frame_step: int = Field(default=1, ge=1, le=1000)
    samples: int = Field(default=0, ge=0, le=4096)
    resolution_percent: int = Field(default=100, ge=1, le=100)
    require_drive: bool = True
    drive_path: str = Field(default="Council OS Renders", min_length=1, max_length=500)
    auto_stop: bool = False
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")

    @field_validator("source_path")
    @classmethod
    def validate_render_source_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if not normalized.lower().endswith(".blend"):
            raise ValueError("Source path must point to a .blend file")
        if any(part == ".." for part in normalized.split("/")):
            raise ValueError("Source path cannot contain parent-directory traversal")
        return normalized

    @field_validator("drive_path")
    @classmethod
    def validate_drive_path(cls, value: str) -> str:
        normalized = value.strip(" /")
        if ".." in normalized.split("/"):
            raise ValueError("Drive path cannot contain parent-directory traversal")
        return normalized

    @field_validator("frame_end")
    @classmethod
    def validate_frame_range(cls, value: int | None, info):
        start = info.data.get("frame_start")
        if value is not None and start is not None and value < start:
            raise ValueError("Frame end cannot be before frame start")
        return value


class BlenderRenderActionRequest(StrictModel):
    action: Literal[
        "run_preflight", "approve_benchmark", "pause", "resume", "cancel",
        "retry_failed_frames", "retry_delivery", "stop_pod",
    ]
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class BlenderFlamencoProcessRequest(StrictModel):
    pod_id: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    action: Literal["start", "stop"]
    role: Literal["coordinator", "worker", "manager"]
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class StableError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchRequest(StrictModel):
    query: str = Field(min_length=1, max_length=2_000)
    collection_ids: list[str] = Field(default_factory=list, max_length=50)
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    graph_expansion: bool = True
    top_k: int = Field(default=8, ge=1, le=20)


class KnowledgeCollectionRequest(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=5_000)
    document_ids: list[str] = Field(default_factory=list, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class KnowledgeCollectionPatch(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=5_000)
    document_ids: list[str] | None = Field(default=None, max_length=500)
    metadata: dict[str, Any] | None = None
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class KnowledgeBindingsRequest(StrictModel):
    collection_ids: list[str] = Field(default_factory=list, max_length=50)
    expected_version: int = Field(default=1, ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class VersionedMutationRequest(StrictModel):
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class BrainReviewActionRequest(StrictModel):
    resource_type: Literal["entity", "fact", "relationship", "conflict", "gap"]
    resource_id: str = Field(min_length=1, max_length=100)
    action: Literal["verify", "reject", "resolve", "reopen", "supersede"]
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    notes: str = Field(default="", max_length=5_000)
    replacement_value: str = Field(default="", max_length=10_000)


class SkillRequest(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=3_000)
    scope_type: Literal["global", "council", "workflow", "integration"]
    scope_id: str = Field(default="", max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=20)
    instructions: str = Field(min_length=5, max_length=20_000)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class LearningActionRequest(StrictModel):
    action: Literal["approve", "reject"]
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    notes: str = Field(default="", max_length=5_000)


class SkillRevisionActionRequest(StrictModel):
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class MarkdownImportRequest(StrictModel):
    documents: list[dict[str, str]] = Field(min_length=1, max_length=100)
    collection_name: str = Field(default="Obsidian import", min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class MCPTokenRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    expires_in_days: int = Field(default=30, ge=1, le=365)
    scopes: list[Literal["brain:read", "council:propose", "task:read"]] = Field(
        default_factory=lambda: ["brain:read", "council:propose", "task:read"], max_length=3
    )
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class MCPTokenRevokeRequest(StrictModel):
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
