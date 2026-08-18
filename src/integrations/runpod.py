"""Minimal, truthful RunPod GraphQL client for the Blender manager."""

from __future__ import annotations

import re
from typing import Any

import httpx

from src.core.integration_context import integration_value


RUNPOD_GRAPHQL_URL = "https://api.runpod.io/graphql"
_POD_ID = re.compile(r"^[A-Za-z0-9_-]{3,100}$")


class RunPodError(RuntimeError):
    """Sanitized provider error that never includes a credential-bearing URL."""


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


async def _graphql(query: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(
            RUNPOD_GRAPHQL_URL,
            headers={"Authorization": f"Bearer {_api_key()}"},
            json={"query": query},
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise RunPodError("RunPod returned an unreadable response") from exc
    if response.is_error or payload.get("errors"):
        raise RunPodError("RunPod rejected the request")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RunPodError("RunPod did not return the requested data")
    return data


def _pod_id(value: str) -> str:
    value = value.strip()
    if not _POD_ID.fullmatch(value):
        raise ValueError("Invalid RunPod pod identifier")
    return value


def _shape_pod(pod: dict[str, Any]) -> dict[str, Any]:
    runtime = pod.get("runtime") if isinstance(pod.get("runtime"), dict) else {}
    ports = runtime.get("ports") if isinstance(runtime.get("ports"), list) else []
    proxy_url = ""
    for port in ports:
        if not isinstance(port, dict):
            continue
        private_port = port.get("privatePort")
        if private_port in {3000, 6901, 8080, 8888}:
            proxy_url = f"https://{pod.get('id')}-{private_port}.proxy.runpod.net"
            break
    return {
        "id": str(pod.get("id", "")),
        "name": str(pod.get("name", "") or pod.get("id", "")),
        "desired_status": str(pod.get("desiredStatus", "UNKNOWN")),
        "image_name": str(pod.get("imageName", "")),
        "gpu_count": int(pod.get("gpuCount") or 0),
        "cost_per_hour": float(pod.get("costPerHr") or 0.0),
        "uptime_seconds": int(runtime.get("uptimeInSeconds") or 0),
        "gpu_utilization": [
            {
                "id": str(gpu.get("id", "")),
                "gpu_percent": float(gpu.get("gpuUtilPercent") or 0),
                "memory_percent": float(gpu.get("memoryUtilPercent") or 0),
            }
            for gpu in (runtime.get("gpus") or [])
            if isinstance(gpu, dict)
        ],
        "proxy_url": proxy_url,
    }


async def list_pods() -> list[dict[str, Any]]:
    data = await _graphql(
        """query { myself { pods { id name desiredStatus imageName gpuCount costPerHr
        runtime { uptimeInSeconds ports { privatePort } gpus { id gpuUtilPercent memoryUtilPercent } }
        } } }"""
    )
    pods = (data.get("myself") or {}).get("pods") or []
    return [_shape_pod(pod) for pod in pods if isinstance(pod, dict)]


async def verify_connection() -> None:
    await _graphql("query { myself { pods { id } } }")


async def resume_pod(pod_id: str) -> dict[str, Any]:
    pod_id = _pod_id(pod_id)
    data = await _graphql(
        f'mutation {{ podResume(input: {{ podId: "{pod_id}", gpuCount: 1 }}) '
        "{ id name desiredStatus imageName gpuCount costPerHr } }"
    )
    pod = data.get("podResume")
    if not isinstance(pod, dict):
        raise RunPodError("RunPod did not confirm the pod resume action")
    return _shape_pod(pod)


async def stop_pod(pod_id: str) -> dict[str, Any]:
    pod_id = _pod_id(pod_id)
    data = await _graphql(
        f'mutation {{ podStop(input: {{ podId: "{pod_id}" }}) '
        "{ id name desiredStatus imageName gpuCount costPerHr } }"
    )
    pod = data.get("podStop")
    if not isinstance(pod, dict):
        raise RunPodError("RunPod did not confirm the pod stop action")
    return _shape_pod(pod)


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
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f"{_agent_base_url(pod_id)}/healthz")
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RunPodError("The Blender agent health check failed") from exc
    if response.is_error or not isinstance(data, dict) or data.get("status") != "ok":
        raise RunPodError("The Blender agent is not ready")
    if not data.get("blender_available"):
        raise RunPodError("Blender is not installed in the selected pod image")
    return data


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
    return await _agent_request(
        pod_id,
        "POST",
        "/v1/jobs",
        payload={
            "job_id": job_id,
            "operation": "validate_repair_benchmark",
            "source_path": source_path,
            "output_name": output_name,
            "frame": frame,
            "samples": samples,
            "resolution_percent": resolution_percent,
        },
    )


async def get_blender_job(pod_id: str, job_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"^[A-Za-z0-9._:-]{8,128}$", job_id):
        raise ValueError("Invalid Blender job identifier")
    return await _agent_request(pod_id, "GET", f"/v1/jobs/{job_id}")


async def cancel_blender_job(pod_id: str, job_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"^[A-Za-z0-9._:-]{8,128}$", job_id):
        raise ValueError("Invalid Blender job identifier")
    return await _agent_request(pod_id, "POST", f"/v1/jobs/{job_id}/cancel")
