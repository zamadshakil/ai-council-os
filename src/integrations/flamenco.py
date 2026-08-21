"""Council OS adapter for the authenticated pod-side Flamenco façade."""

from __future__ import annotations

import re
from typing import Any

from src.integrations.runpod import RunPodError, _agent_request, _pod_id


FLAMENCO_JOB_ID = re.compile(r"^[0-9a-fA-F-]{36}$")


async def get_flamenco_status(pod_id: str) -> dict[str, Any]:
    return await _agent_request(_pod_id(pod_id), "GET", "/v1/flamenco/status")


async def start_flamenco(pod_id: str, role: str = "coordinator") -> dict[str, Any]:
    if role not in {"coordinator", "worker"}:
        raise ValueError("Unsupported Flamenco process role")
    return await _agent_request(
        _pod_id(pod_id),
        "POST",
        "/v1/flamenco/processes/start",
        payload={"role": role},
    )


async def stop_flamenco_process(pod_id: str, role: str) -> dict[str, Any]:
    if role not in {"manager", "worker"}:
        raise ValueError("Unsupported Flamenco process role")
    return await _agent_request(
        _pod_id(pod_id), "POST", f"/v1/flamenco/processes/{role}/stop"
    )


async def get_flamenco_logs(pod_id: str, role: str) -> dict[str, Any]:
    if role not in {"manager", "worker"}:
        raise ValueError("Unsupported Flamenco process role")
    return await _agent_request(
        _pod_id(pod_id), "GET", f"/v1/flamenco/logs/{role}"
    )


async def submit_flamenco_render(
    pod_id: str,
    *,
    render_job_id: str,
    name: str,
    source_path: str,
    output_directory: str,
    frames: str,
    chunk_size: int,
    fps: float,
    image_format: str,
    image_extension: str,
    scene: str = "Scene",
    priority: int = 50,
) -> dict[str, Any]:
    return await _agent_request(
        _pod_id(pod_id),
        "POST",
        "/v1/flamenco/jobs",
        payload={
            "render_job_id": render_job_id,
            "name": name,
            "source_path": source_path,
            "output_directory": output_directory,
            "frames": frames,
            "chunk_size": chunk_size,
            "fps": fps,
            "image_format": image_format,
            "image_extension": image_extension,
            "scene": scene,
            "priority": priority,
        },
    )


async def get_flamenco_job(pod_id: str, flamenco_job_id: str) -> dict[str, Any]:
    if not FLAMENCO_JOB_ID.fullmatch(flamenco_job_id):
        raise ValueError("Invalid Flamenco job identifier")
    return await _agent_request(
        _pod_id(pod_id), "GET", f"/v1/flamenco/jobs/{flamenco_job_id}"
    )


async def act_on_flamenco_job(
    pod_id: str,
    flamenco_job_id: str,
    action: str,
    *,
    reason: str = "Council OS administrator action",
) -> dict[str, Any]:
    if action not in {"pause", "resume", "cancel", "retry"}:
        raise ValueError("Unsupported Flamenco job action")
    if not FLAMENCO_JOB_ID.fullmatch(flamenco_job_id):
        raise ValueError("Invalid Flamenco job identifier")
    try:
        return await _agent_request(
            _pod_id(pod_id),
            "POST",
            f"/v1/flamenco/jobs/{flamenco_job_id}/actions",
            payload={"action": action, "reason": reason},
        )
    except RunPodError:
        raise
