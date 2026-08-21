"""Minimal, truthful RunPod REST client for the Blender manager."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import httpx

from src.core.integration_context import integration_value


RUNPOD_REST_URL = "https://rest.runpod.io/v1"
RUNPOD_GRAPHQL_URL = "https://api.runpod.io/graphql"
_POD_ID = re.compile(r"^[A-Za-z0-9_-]{3,100}$")
_IMMUTABLE_BLENDER_IMAGE = re.compile(
    r"ghcr\.io/[a-z0-9._-]+/[a-z0-9._/-]+:[a-f0-9]{40}"
)
_RUNPOD_KASM_VNC_OPTIONS = (
    "-PreferBandwidth -DynamicQualityMin=4 -DynamicQualityMax=7 "
    "-DLP_ClipDelay=0 -sslOnly 0"
)


class RunPodError(RuntimeError):
    """Sanitized provider error that never includes a credential-bearing URL."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "RUNPOD_ACTION_FAILED",
        http_status: int = 502,
        provider_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.provider_status = provider_status


def _provider_failure(status: int, data: object) -> RunPodError:
    """Map provider failures to safe, stable errors without echoing its body."""
    messages: list[str] = []
    if isinstance(data, dict):
        for key in ("message", "error", "detail"):
            value = data.get(key)
            if isinstance(value, str):
                messages.append(value)
            elif isinstance(value, dict):
                messages.extend(
                    str(item) for item in value.values() if isinstance(item, str)
                )
        errors = data.get("errors")
        if isinstance(errors, list):
            messages.extend(
                str(item.get("message", ""))
                for item in errors
                if isinstance(item, dict)
            )
    description = " ".join(messages).lower()
    if status in {401, 403}:
        return RunPodError(
            "RunPod authorization failed. Re-verify the RunPod connection in Settings.",
            code="RUNPOD_AUTH_FAILED",
            http_status=502,
            provider_status=status,
        )
    if status == 404:
        return RunPodError(
            "This RunPod machine no longer exists in the connected account.",
            code="RUNPOD_POD_NOT_FOUND",
            http_status=404,
            provider_status=status,
        )
    if status == 429:
        return RunPodError(
            "RunPod is rate-limiting lifecycle requests. Wait briefly, then refresh.",
            code="RUNPOD_RATE_LIMITED",
            http_status=503,
            provider_status=status,
        )
    if status == 402 or any(
        marker in description
        for marker in ("insufficient funds", "insufficient balance", "billing", "credit")
    ):
        return RunPodError(
            "RunPod could not start billing for this machine. Check the RunPod account balance and billing status.",
            code="RUNPOD_BILLING_BLOCKED",
            http_status=409,
            provider_status=status,
        )
    if any(
        marker in description
        for marker in ("no gpu", "gpu unavailable", "not available", "no capacity", "out of stock")
    ):
        return RunPodError(
            "The stopped pod's original RunPod machine has no free GPU right now. Your /workspace remains preserved; refresh later or migrate the pod in RunPod.",
            code="RUNPOD_GPU_CAPACITY_UNAVAILABLE",
            http_status=409,
            provider_status=status,
        )
    if status == 409:
        return RunPodError(
            "RunPod cannot resume this machine in its current state. Refresh its status before trying again.",
            code="RUNPOD_POD_NOT_RESUMABLE",
            http_status=409,
            provider_status=status,
        )
    return RunPodError(
        "RunPod could not complete this machine action. Refresh the machine status and check RunPod system logs.",
        provider_status=status,
    )


def _api_key() -> str:
    key = integration_value("RUNPOD_API_KEY", "").strip()
    if not key:
        raise RunPodError("RunPod is not configured or verified")
    return key


def _agent_token() -> str:
    token = integration_value("BLENDER_AGENT_TOKEN", "").strip()
    if len(token) < 32:
        raise RunPodError("The Blender pod agent token is not configured")
    return token


def _agent_base_url(pod_id: str) -> str:
    pod_id = _pod_id(pod_id)
    raw_port = integration_value("BLENDER_AGENT_PORT", "8001").strip() or "8001"
    if not raw_port.isdigit() or not 1 <= int(raw_port) <= 65535:
        raise RunPodError("The Blender agent proxy port is invalid")
    return f"https://{pod_id}-{int(raw_port)}.proxy.runpod.net"


async def _rest(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any] | list[dict[str, Any]]:
    if not path.startswith("/") or ".." in path:
        raise ValueError("Invalid RunPod REST path")
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.request(
                method,
                f"{RUNPOD_REST_URL}{path}",
                headers={"Authorization": f"Bearer {_api_key()}"},
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise RunPodError("RunPod could not be reached") from exc
    try:
        data = response.json()
    except ValueError as exc:
        if response.is_error:
            raise _provider_failure(response.status_code, {}) from exc
        if not response.is_error and not response.content.strip():
            return {}
        raise RunPodError("RunPod returned an unreadable response") from exc
    if response.is_error:
        raise _provider_failure(response.status_code, data)
    if not isinstance(data, (dict, list)):
        raise RunPodError("RunPod returned an invalid response")
    if isinstance(data, list) and not all(isinstance(item, dict) for item in data):
        raise RunPodError("RunPod returned an invalid list response")
    return data


async def _pod_runtimes() -> dict[str, dict[str, Any]]:
    """Fetch live Pod telemetry from RunPod's documented GraphQL surface.

    The REST Pod schema intentionally does not include runtime utilization.
    Keep the API key out of errors/logs even though RunPod's legacy GraphQL
    authentication requires it as a query parameter.
    """
    query = """
    query CouncilPodRuntime {
      myself {
        pods {
          id
          desiredStatus
          machine { gpuAvailable gpuDisplayName dataCenterId }
          runtime {
            uptimeInSeconds
            gpus { id gpuUtilPercent memoryUtilPercent }
            container { cpuPercent memoryPercent }
          }
        }
      }
    }
    """
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                RUNPOD_GRAPHQL_URL,
                params={"api_key": _api_key()},
                json={"query": query},
            )
    except httpx.HTTPError as exc:
        raise RunPodError("RunPod telemetry could not be reached") from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise RunPodError("RunPod telemetry returned an unreadable response") from exc
    if response.is_error or not isinstance(payload, dict) or payload.get("errors"):
        raise RunPodError("RunPod telemetry rejected the request")
    myself = (payload.get("data") or {}).get("myself") or {}
    pods = myself.get("pods") or []
    states: dict[str, dict[str, Any]] = {}
    for item in pods:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        state = dict(item.get("runtime") or {})
        machine = item.get("machine") if isinstance(item.get("machine"), dict) else {}
        state["_gpuAvailable"] = machine.get("gpuAvailable")
        state["_gpuDisplayName"] = machine.get("gpuDisplayName")
        state["_dataCenterId"] = machine.get("dataCenterId")
        states[str(item["id"])] = state
    return states


async def _pod_resume_readiness(pod_id: str) -> dict[str, Any]:
    """Read the stopped pod's host capacity without attempting a billable start."""
    query = """
    query CouncilPodResumeReadiness($podId: String!) {
      pod(input: {podId: $podId}) {
        id
        desiredStatus
        machine { gpuAvailable gpuDisplayName dataCenterId }
      }
    }
    """
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                RUNPOD_GRAPHQL_URL,
                params={"api_key": _api_key()},
                json={"query": query, "variables": {"podId": pod_id}},
            )
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return {"status": "unknown"}
    if response.is_error or not isinstance(payload, dict) or payload.get("errors"):
        return {"status": "unknown"}
    pod = (payload.get("data") or {}).get("pod") or {}
    machine = pod.get("machine") if isinstance(pod.get("machine"), dict) else {}
    available = machine.get("gpuAvailable")
    return {
        "status": (
            "running" if pod.get("desiredStatus") == "RUNNING"
            else "capacity_unavailable" if available == 0
            else "ready" if isinstance(available, (int, float)) and available > 0
            else "unknown"
        ),
        "gpu_available": int(available) if isinstance(available, (int, float)) else None,
        "gpu_name": str(machine.get("gpuDisplayName") or "GPU"),
        "data_center": str(machine.get("dataCenterId") or ""),
    }


def _pod_id(value: str) -> str:
    value = value.strip()
    if not _POD_ID.fullmatch(value):
        raise ValueError("Invalid RunPod pod identifier")
    return value


def validate_blender_image(value: str) -> str:
    """Accept only a public GHCR image pinned to a full Git commit SHA."""
    image_name = value.strip().lower()
    if not _IMMUTABLE_BLENDER_IMAGE.fullmatch(image_name):
        raise ValueError("Blender image must be an immutable GHCR reference pinned to a full Git SHA")
    return image_name


def _shape_pod(pod: dict[str, Any]) -> dict[str, Any]:
    runtime = pod.get("runtime") if isinstance(pod.get("runtime"), dict) else {}
    gpu = pod.get("gpu") if isinstance(pod.get("gpu"), dict) else {}
    runtime_ports = runtime.get("ports") if isinstance(runtime.get("ports"), list) else []
    configured_ports = pod.get("ports") if isinstance(pod.get("ports"), list) else []
    proxy_url = ""
    for port in [*runtime_ports, *configured_ports]:
        if isinstance(port, dict):
            private_port = port.get("privatePort") or port.get("port")
        elif isinstance(port, str):
            raw_port = port.split("/", 1)[0]
            private_port = int(raw_port) if raw_port.isdigit() else None
        else:
            private_port = None
        if private_port in {3000, 6901, 8080, 8888}:
            proxy_url = f"https://{pod.get('id')}-{private_port}.proxy.runpod.net"
            break
    uptime_seconds = int(runtime.get("uptimeInSeconds") or 0)
    if not uptime_seconds and pod.get("desiredStatus") == "RUNNING":
        raw_started = pod.get("lastStartedAt")
        if isinstance(raw_started, str):
            try:
                started = datetime.fromisoformat(raw_started.replace("Z", "+00:00"))
                uptime_seconds = max(
                    0,
                    int((datetime.now(timezone.utc) - started).total_seconds()),
                )
            except ValueError:
                pass
    container = runtime.get("container") if isinstance(runtime.get("container"), dict) else {}
    metrics_observed = any(
        key in runtime for key in ("uptimeInSeconds", "gpus", "container")
    )
    available = runtime.get("_gpuAvailable")
    desired_status = str(pod.get("desiredStatus", "UNKNOWN"))
    resume_status = (
        "running" if desired_status == "RUNNING"
        else "capacity_unavailable" if available == 0
        else "ready" if isinstance(available, (int, float)) and available > 0
        else "unknown"
    )
    return {
        "id": str(pod.get("id", "")),
        "name": str(pod.get("name", "") or pod.get("id", "")),
        "desired_status": desired_status,
        "image_name": str(pod.get("imageName") or pod.get("image") or ""),
        "gpu_count": int(pod.get("gpuCount") or gpu.get("count") or 0),
        "cost_per_hour": float(pod.get("costPerHr") or 0.0),
        "uptime_seconds": uptime_seconds,
        "gpu_utilization": [
            {
                "id": str(gpu.get("id", "")),
                "gpu_percent": float(gpu.get("gpuUtilPercent") or 0),
                "memory_percent": float(gpu.get("memoryUtilPercent") or 0),
            }
            for gpu in (runtime.get("gpus") or [])
            if isinstance(gpu, dict)
        ],
        "cpu_percent": float(container.get("cpuPercent") or 0),
        "memory_percent": float(container.get("memoryPercent") or 0),
        "telemetry_status": "live" if metrics_observed else "unavailable",
        "proxy_url": proxy_url,
        "resume_status": resume_status,
        "gpu_available_on_machine": (
            int(available) if isinstance(available, (int, float)) else None
        ),
        "machine_gpu_name": str(runtime.get("_gpuDisplayName") or ""),
        "data_center_id": str(runtime.get("_dataCenterId") or ""),
    }


async def list_pods() -> list[dict[str, Any]]:
    data = await _rest("GET", "/pods")
    if not isinstance(data, list):
        raise RunPodError("RunPod did not return the pod list")
    try:
        runtimes = await _pod_runtimes()
    except RunPodError:
        # Lifecycle controls remain available during a metrics-only outage,
        # but every shaped Pod explicitly reports telemetry as unavailable.
        runtimes = {}
    return [
        _shape_pod({**pod, "runtime": runtimes.get(str(pod.get("id")), {})})
        for pod in data
    ]


def _shape_template(template: dict[str, Any]) -> dict[str, Any]:
    """Return only non-secret template metadata."""
    return {
        "id": str(template.get("id", "")),
        "name": str(template.get("name", "")),
        "image_name": str(template.get("imageName", "")),
        "container_disk_gb": int(template.get("containerDiskInGb") or 0),
        "volume_gb": int(template.get("volumeInGb") or 0),
        "volume_mount_path": str(template.get("volumeMountPath") or ""),
        "ports": [str(item) for item in (template.get("ports") or [])],
    }


async def list_templates() -> list[dict[str, Any]]:
    data = await _rest("GET", "/templates")
    if not isinstance(data, list):
        raise RunPodError("RunPod did not return the template list")
    return [_shape_template(item) for item in data]


async def ensure_blender_template(
    *,
    image_name: str,
    container_disk_gb: int = 50,
    volume_gb: int = 250,
) -> dict[str, Any]:
    """Create or reuse the private, immutable Blender/Kasm Pod template.

    Runtime secrets deliberately do not live in the reusable template. They are
    generated by Council OS and attached only to the provisioned Pod.
    """
    image_name = validate_blender_image(image_name)
    if not 50 <= container_disk_gb <= 200 or not 50 <= volume_gb <= 2000:
        raise ValueError("Blender template storage is outside the approved safety range")
    image_sha = image_name.rsplit(":", 1)[-1]
    template_name = f"Council OS Blender 5.0.1 {image_sha[:12]}"
    templates = await list_templates()
    existing = next((item for item in templates if item["name"] == template_name), None)
    if existing:
        if existing["image_name"].lower() != image_name:
            raise RunPodError("The immutable Blender template name is already in use by another image")
        return existing
    created = await _rest(
        "POST",
        "/templates",
        payload={
            "imageName": image_name,
            "name": template_name,
            "category": "NVIDIA",
            "containerDiskInGb": container_disk_gb,
            "dockerEntrypoint": [],
            "dockerStartCmd": [],
            "env": {
                "BLENDER_AGENT_PORT": "8001",
                "BLENDER_WORKSPACE_ROOT": "/workspace",
                "NVIDIA_VISIBLE_DEVICES": "all",
                "NVIDIA_DRIVER_CAPABILITIES": "compute,utility,graphics,display,video",
                "VNCOPTIONS": _RUNPOD_KASM_VNC_OPTIONS,
            },
            "isPublic": False,
            "isServerless": False,
            "ports": ["6901/http", "8001/http"],
            "readme": "Council OS Blender 5.0.1 Kasm workstation and safe headless renderer.",
            "volumeInGb": volume_gb,
            "volumeMountPath": "/workspace",
        },
    )
    if not isinstance(created, dict):
        raise RunPodError("RunPod returned an invalid template response")
    return _shape_template(created)


async def create_a6000_pod(
    *,
    template_id: str,
    image_name: str,
    agent_token: str,
    flamenco_proxy_token: str,
    kasm_password: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Provision exactly one on-demand RTX A6000 Kasm workstation.

    The stable provider name makes retries idempotent even if the API response
    is lost after RunPod creates the paid resource.
    """
    image_name = validate_blender_image(image_name)
    if not _POD_ID.fullmatch(template_id.strip()):
        raise ValueError("Invalid RunPod template identifier")
    if len(agent_token) < 32 or len(flamenco_proxy_token) < 32 or len(kasm_password) < 16:
        raise ValueError("Generated Blender runtime credentials are invalid")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", idempotency_key):
        raise ValueError("Invalid provisioning idempotency key")
    suffix = re.sub(r"[^a-z0-9-]", "-", idempotency_key.lower()).strip("-")[:24]
    if len(suffix) < 8:
        suffix = re.sub(r"[^a-f0-9]", "", image_name.rsplit(":", 1)[-1])[:12]
    pod_name = f"council-blender-a6000-{suffix}"
    pods = await list_pods()
    existing = next((item for item in pods if item["name"] == pod_name), None)
    if existing:
        if existing["image_name"].lower() != image_name or existing["gpu_count"] != 1:
            raise RunPodError("The idempotent Blender Pod name is already used by a different runtime")
        return existing
    created = await _rest(
        "POST",
        "/pods",
        payload={
            "cloudType": "SECURE",
            "computeType": "GPU",
            "containerDiskInGb": 50,
            "dockerEntrypoint": [],
            "dockerStartCmd": [],
            "env": {
                "BLENDER_AGENT_TOKEN": agent_token,
                "FLAMENCO_WORKER_PROXY_TOKEN": flamenco_proxy_token,
                "BLENDER_AGENT_PORT": "8001",
                "BLENDER_WORKSPACE_ROOT": "/workspace",
                "NVIDIA_VISIBLE_DEVICES": "all",
                "NVIDIA_DRIVER_CAPABILITIES": "compute,utility,graphics,display,video",
                "VNC_PW": kasm_password,
                "VNCOPTIONS": _RUNPOD_KASM_VNC_OPTIONS,
            },
            "globalNetworking": False,
            "gpuCount": 1,
            "gpuTypeIds": ["NVIDIA RTX A6000"],
            "gpuTypePriority": "custom",
            "imageName": image_name,
            "interruptible": False,
            "locked": False,
            "minRAMPerGPU": 64,
            "minVCPUPerGPU": 8,
            "name": pod_name,
            "ports": ["6901/http", "8001/http"],
            "supportPublicIp": True,
            "templateId": template_id.strip(),
            "volumeInGb": 250,
            "volumeMountPath": "/workspace",
        },
    )
    if not isinstance(created, dict):
        raise RunPodError("RunPod returned an invalid Pod response")
    shaped = _shape_pod(created)
    if shaped["gpu_count"] not in {0, 1}:
        raise RunPodError("RunPod created an unexpected multi-GPU Pod")
    return shaped


async def verify_connection() -> None:
    await list_pods()


async def _get_pod(pod_id: str) -> dict[str, Any]:
    result = await _rest("GET", f"/pods?id={pod_id}")
    if not isinstance(result, list) or not result:
        raise RunPodError("RunPod did not return the requested pod")
    return _shape_pod(result[0])


async def resume_pod(pod_id: str) -> dict[str, Any]:
    pod_id = _pod_id(pod_id)
    readiness = await _pod_resume_readiness(pod_id)
    if readiness.get("status") == "capacity_unavailable":
        location = f" in {readiness['data_center']}" if readiness.get("data_center") else ""
        raise RunPodError(
            f"This pod's original RunPod machine{location} currently has no free {readiness.get('gpu_name') or 'GPU'}. Your /workspace is preserved; refresh later or migrate the pod in RunPod.",
            code="RUNPOD_GPU_CAPACITY_UNAVAILABLE",
            http_status=409,
        )
    await _rest("POST", f"/pods/{pod_id}/start")
    return await _get_pod(pod_id)


async def stop_pod(pod_id: str) -> dict[str, Any]:
    pod_id = _pod_id(pod_id)
    await _rest("POST", f"/pods/{pod_id}/stop")
    return await _get_pod(pod_id)


async def update_pod_runtime(
    pod_id: str,
    *,
    image_name: str,
    agent_token: str,
    flamenco_proxy_token: str,
    kasm_password: str,
) -> dict[str, Any]:
    """Update a stopped pod without changing or deleting its /workspace volume."""
    pod_id = _pod_id(pod_id)
    image_name = validate_blender_image(image_name)
    if len(agent_token) < 32 or len(flamenco_proxy_token) < 32 or len(kasm_password) < 16:
        raise ValueError("Generated Blender runtime credentials are invalid")
    updated = await _rest(
        "POST",
        f"/pods/{pod_id}/update",
        payload={
            "imageName": image_name,
            "ports": ["6901/http", "8001/http"],
            "volumeMountPath": "/workspace",
            "dockerEntrypoint": [],
            "dockerStartCmd": [],
            "env": {
                "BLENDER_AGENT_TOKEN": agent_token,
                "FLAMENCO_WORKER_PROXY_TOKEN": flamenco_proxy_token,
                "BLENDER_AGENT_PORT": "8001",
                "BLENDER_WORKSPACE_ROOT": "/workspace",
                "NVIDIA_VISIBLE_DEVICES": "all",
                "NVIDIA_DRIVER_CAPABILITIES": "compute,utility,graphics,display,video",
                "VNC_PW": kasm_password,
                "VNCOPTIONS": _RUNPOD_KASM_VNC_OPTIONS,
            },
        },
    )
    if not isinstance(updated, dict):
        raise RunPodError("RunPod returned an invalid pod response")
    return _shape_pod(updated)


async def _agent_request(
    pod_id: str,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not path.startswith("/") or ".." in path:
        raise ValueError("Invalid Blender agent path")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=45)) as client:
            request_options: dict[str, Any] = {
                "headers": {"Authorization": f"Bearer {_agent_token()}"},
            }
            if payload is not None:
                request_options["json"] = payload
            response = await client.request(
                method, f"{_agent_base_url(pod_id)}{path}", **request_options
            )
    except httpx.HTTPError as exc:
        raise RunPodError("The Blender agent could not be reached on the selected pod") from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise RunPodError("The Blender agent returned an unreadable response") from exc
    if response.is_error:
        detail = data.get("detail") if isinstance(data, dict) else ""
        allowed = str(detail)[:500] if response.status_code in {404, 409, 422} else ""
        raise RunPodError(allowed or "The Blender agent rejected the request")
    if not isinstance(data, dict):
        raise RunPodError("The Blender agent returned an invalid response")
    return data


async def verify_blender_agent(pod_id: str) -> dict[str, Any]:
    """Confirm the allowlisted agent is online; never sends the RunPod API key."""
    pod_id = _pod_id(pod_id)
    data = await _agent_request(pod_id, "GET", "/healthz")
    if not data.get("blender_available"):
        raise RunPodError("Blender is not installed in the selected pod image")
    if not data.get("nvidia_smi_available") or not data.get("gpu_visible"):
        raise RunPodError("The selected pod does not expose an NVIDIA GPU to the Blender image")
    if not data.get("workspace_writable"):
        raise RunPodError(
            "The selected pod cannot write to its persistent workspace",
            code="BLENDER_WORKSPACE_NOT_WRITABLE",
            http_status=503,
        )
    required_tools = data.get("required_tools") if isinstance(data.get("required_tools"), dict) else {}
    missing_tools = [name for name, available in required_tools.items() if not available]
    if missing_tools:
        raise RunPodError(
            "The Blender runtime is missing required tools: " + ", ".join(missing_tools),
            code="BLENDER_RUNTIME_INCOMPLETE",
            http_status=503,
        )
    desktop = data.get("desktop") if isinstance(data.get("desktop"), dict) else {}
    if not desktop.get("ready"):
        missing = ", ".join(desktop.get("missing_components") or [])
        detail = f" Missing components: {missing}." if missing else ""
        raise RunPodError(
            "Kasm is reachable, but its Linux desktop is not ready." + detail,
            code="BLENDER_DESKTOP_NOT_READY",
            http_status=503,
        )
    return data


async def get_blender_runtime(pod_id: str) -> dict[str, Any]:
    """Read the agent's instantaneous GPU/GUI state for a verified pod."""
    pod_id = _pod_id(pod_id)
    return await _agent_request(pod_id, "GET", "/v1/runtime")


async def submit_render_stage(
    pod_id: str,
    *,
    job_id: str,
    render_job_id: str,
    operation: str,
    source_path: str,
    output_profile: str = "delivery",
    frames: list[int] | None = None,
    frame_start: int | None = None,
    frame_end: int | None = None,
    frame_step: int = 1,
    samples: int = 0,
    resolution_percent: int = 100,
    expected_width: int | None = None,
    expected_height: int | None = None,
    persistent_data: bool = False,
    backend: str = "AUTO",
    fps: float = 24.0,
    drive_path: str = "Council OS Renders",
    require_drive: bool = True,
    include_audio: bool = False,
) -> dict[str, Any]:
    """Submit one allowlisted stage to the authenticated pod agent."""
    if operation not in {
        "preflight", "benchmark", "observe_gui", "frame_batch",
        "prepare_flamenco", "validate", "encode", "deliver",
    }:
        raise ValueError("Unsupported Blender render operation")
    if backend not in {"AUTO", "OPTIX", "CUDA"}:
        raise ValueError("Unsupported Blender compute backend")
    return await _agent_request(
        pod_id,
        "POST",
        "/v1/jobs",
        payload={
            "job_id": job_id,
            "render_job_id": render_job_id,
            "operation": operation,
            "source_path": source_path,
            "output_profile": output_profile,
            "frames": list(frames or []),
            "frame_start": frame_start,
            "frame_end": frame_end,
            "frame_step": frame_step,
            "samples": samples,
            "resolution_percent": resolution_percent,
            "expected_width": expected_width,
            "expected_height": expected_height,
            "persistent_data": persistent_data,
            "backend": backend,
            "fps": fps,
            "drive_path": drive_path,
            "require_drive": require_drive,
            "include_audio": include_audio,
        },
    )


async def submit_blender_job(
    pod_id: str,
    *,
    job_id: str,
    source_path: str,
    output_name: str,
    frame: int,
    samples: int,
    resolution_percent: int,
) -> dict[str, Any]:
    # Deprecated compatibility path. The new agent never writes a repaired
    # .blend copy; it runs an in-memory benchmark and preserves the source.
    return await submit_render_stage(
        pod_id,
        job_id=job_id,
        render_job_id=job_id,
        operation="benchmark",
        source_path=source_path,
        frames=[frame],
        samples=samples,
        resolution_percent=resolution_percent,
        require_drive=False,
    )


async def get_blender_job(pod_id: str, job_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"^[A-Za-z0-9._:-]{8,128}$", job_id):
        raise ValueError("Invalid Blender job identifier")
    return await _agent_request(pod_id, "GET", f"/v1/jobs/{job_id}")


async def cancel_blender_job(pod_id: str, job_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"^[A-Za-z0-9._:-]{8,128}$", job_id):
        raise ValueError("Invalid Blender job identifier")
    return await _agent_request(pod_id, "POST", f"/v1/jobs/{job_id}/cancel")
