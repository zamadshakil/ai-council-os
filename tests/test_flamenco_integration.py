from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from fastapi import HTTPException

from src.scripts import blender_listener, flamenco_control, flamenco_gateway
from src.worker import DurableWorker


def test_flamenco_manager_is_loopback_only_and_bootstraps_cycles_gpu(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    state = workspace / ".council-flamenco"
    workspace.mkdir()
    monkeypatch.setenv("BLENDER_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("FLAMENCO_HOME", str(state))

    config = flamenco_control._write_manager_config().read_text(encoding="utf-8")

    assert "listen: 127.0.0.1:8080" in config
    assert "shared_storage_path: /workspace" in config
    assert "shaman:\n  enabled: false" in config
    assert "--python /opt/council/flamenco_gpu_bootstrap.py" in config
    assert "0.0.0.0:8080" not in config


def test_remote_worker_gateway_cannot_reach_manager_admin_endpoints():
    assert flamenco_gateway._allowed("/api/v3/version") is True
    assert flamenco_gateway._allowed("/api/v3/worker/sign-on") is True
    assert flamenco_gateway._allowed("/api/v3/jobs") is False
    assert flamenco_gateway._allowed("/api/v3/worker-mgt/workers") is False


def test_remote_worker_uses_distinct_coordinator_token(monkeypatch):
    monkeypatch.setenv("FLAMENCO_COORDINATOR_AGENT_URL", "https://coordinator.example")
    monkeypatch.setenv("BLENDER_AGENT_TOKEN", "local-worker-token-that-is-long-enough")
    monkeypatch.setenv(
        "FLAMENCO_COORDINATOR_AGENT_TOKEN",
        "coordinator-token-that-is-distinct-and-long-enough",
    )

    base, token = flamenco_gateway._coordinator()

    assert base == "https://coordinator.example"
    assert token == "coordinator-token-that-is-distinct-and-long-enough"


@pytest.mark.asyncio
async def test_remote_worker_token_is_scoped_to_proxy_only(monkeypatch):
    agent_token = "full-agent-token-that-is-at-least-thirty-two"
    worker_token = "worker-proxy-token-that-is-at-least-thirty-two"
    monkeypatch.setenv("BLENDER_AGENT_TOKEN", agent_token)
    monkeypatch.setenv("FLAMENCO_WORKER_PROXY_TOKEN", worker_token)

    await blender_listener._authorize(authorization=f"Bearer {agent_token}")
    await blender_listener._authorize_worker_proxy(authorization=f"Bearer {worker_token}")
    with pytest.raises(HTTPException):
        await blender_listener._authorize(authorization=f"Bearer {worker_token}")
    with pytest.raises(HTTPException):
        await blender_listener._authorize_worker_proxy(authorization=f"Bearer {agent_token}")


def test_flamenco_job_contract_rejects_non_workspace_and_script_like_frames():
    values = {
        "render_job_id": str(uuid.uuid4()),
        "name": "Safe production render",
        "source_path": "/workspace/render_jobs/job/scene.flamenco.blend",
        "output_directory": "/workspace/render_jobs/job/frames",
        "frames": "1-4000",
    }
    request = flamenco_control.FlamencoJobRequest(**values)
    assert request.chunk_size == 1
    with pytest.raises(ValidationError):
        flamenco_control.FlamencoJobRequest(**{**values, "source_path": "/tmp/scene.blend"})
    with pytest.raises(ValidationError):
        flamenco_control.FlamencoJobRequest(**{**values, "frames": "1; touch /tmp/pwned"})


@pytest.mark.asyncio
async def test_flamenco_actions_map_to_official_request_states(monkeypatch):
    job_id = str(uuid.uuid4())
    calls: list[tuple[str, str, dict | None]] = []

    async def fake_manager_request(method, path, *, payload=None, timeout=30.0):
        calls.append((method, path, payload))
        if path.endswith("/tasks"):
            return {"tasks": []}
        if path.endswith(job_id):
            return {"id": job_id, "status": "pause-requested"}
        return {"accepted": True}

    monkeypatch.setattr(flamenco_control, "manager_request", fake_manager_request)
    result = await flamenco_control.act_on_job(
        job_id,
        flamenco_control.FlamencoJobAction(action="pause", reason="Safety gate"),
    )

    assert calls[0] == (
        "POST",
        f"/api/v3/jobs/{job_id}/setstatus",
        {"status": "pause-requested", "reason": "Safety gate"},
    )
    assert result["job"]["status"] == "pause-requested"


def test_flamenco_frame_expressions_and_task_reconciliation_are_deterministic():
    assert DurableWorker._flamenco_frame_expression(1, 5, 1) == "1-5"
    assert DurableWorker._flamenco_frame_expression(1, 5, 2) == "1,3,5"
    assert DurableWorker._flamenco_task_frames("render-1-3,8,10-11") == [1, 2, 3, 8, 10, 11]
    assert DurableWorker._flamenco_task_frames("video-encoding") == []
