from __future__ import annotations

import httpx
import pytest

from src.core import rendering
from src.core.models import RenderJobModel, WorkflowRunModel
from src.integrations import runpod
from src.scripts import blender_listener


def test_representative_frames_and_batches_are_deterministic_and_disjoint():
    frames = rendering.representative_frames(1, 4000, 5)
    assert frames[0] == 1
    assert frames[-1] == 4000
    assert len(frames) == 5
    assert frames == sorted(set(frames))

    batches = rendering.frame_batches([3, 2, 2, 1, 4, 5], 2)
    assert batches == [[1, 2], [3, 4], [5]]
    assert len({frame for batch in batches for frame in batch}) == 5


def test_memory_gate_requires_real_totals_and_safe_growth():
    safe, metrics = blender_listener._usage_within_limits({
        "peak_vram_mb": 20_000,
        "vram_total_mb": 48_000,
        "peak_host_ram_mb": 40_000,
        "host_ram_total_mb": 64_000,
        "host_ram_growth_percent": 2.5,
    })
    assert safe is True
    assert metrics["peak_vram_percent"] < 80

    unsafe, _ = blender_listener._usage_within_limits({
        "peak_vram_mb": 40_000,
        "vram_total_mb": 48_000,
        "peak_host_ram_mb": 40_000,
        "host_ram_total_mb": 64_000,
        "host_ram_growth_percent": 2.5,
    })
    assert unsafe is False
    assert blender_listener._usage_within_limits({})[0] is False


def test_batch_size_falls_back_to_one_when_soak_memory_grows():
    assert blender_listener._recommended_batch_size({
        "host_ram_growth_percent": 1.1,
        "peak_vram_percent": 45,
        "peak_host_ram_percent": 50,
    }) == 1
    assert blender_listener._recommended_batch_size({
        "host_ram_growth_percent": 0.2,
        "peak_vram_percent": 72,
        "peak_host_ram_percent": 50,
    }) == 2
    assert blender_listener._recommended_batch_size({
        "host_ram_growth_percent": 0.2,
        "peak_vram_percent": 45,
        "peak_host_ram_percent": 50,
    }) == 10


def test_drive_error_codes_distinguish_quota_from_rate_limit():
    assert blender_listener._classify_rclone("403 storageQuotaExceeded") == (
        "delivery_blocked_storage_full"
    )
    assert blender_listener._classify_rclone("403 userRateLimitExceeded") == (
        "delivery_rate_limited"
    )
    assert blender_listener._classify_rclone("HTTP 429 retry later") == (
        "delivery_rate_limited"
    )


@pytest.mark.asyncio
async def test_agent_health_requires_the_generated_bearer_token(monkeypatch, tmp_path):
    token = "render-agent-token-that-is-longer-than-thirty-two-characters"
    monkeypatch.setenv("BLENDER_AGENT_TOKEN", token)
    monkeypatch.setenv("BLENDER_WORKSPACE_ROOT", str(tmp_path))
    transport = httpx.ASGITransport(app=blender_listener.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://agent") as client:
        anonymous = await client.get("/healthz")
        assert anonymous.status_code == 401
        authorized = await client.get(
            "/healthz", headers={"Authorization": f"Bearer {token}"}
        )
        assert authorized.status_code == 200
        assert "gpu_visible" in authorized.json()


@pytest.mark.asyncio
async def test_runtime_update_preserves_workspace_and_uses_immutable_image(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_rest(method, path, *, payload=None):
        captured.update({"method": method, "path": path, "payload": payload})
        return {
            "id": "pod-safe-123",
            "name": "smoke pod",
            "desiredStatus": "EXITED",
            "imageName": payload["imageName"],
            "gpu": {"count": 1},
            "ports": payload["ports"],
        }

    monkeypatch.setattr(runpod, "_rest", fake_rest)
    image = f"ghcr.io/astrofood/ai-council-blender:{'a' * 40}"
    result = await runpod.update_pod_runtime(
        "pod-safe-123",
        image_name=image,
        agent_token="a" * 48,
        kasm_password="b" * 20,
    )
    payload = captured["payload"]
    assert captured["method"] == "POST"
    assert captured["path"] == "/pods/pod-safe-123/update"
    assert result["image_name"] == image
    assert result["gpu_count"] == 1
    assert result["proxy_url"] == "https://pod-safe-123-6901.proxy.runpod.net"
    assert payload["volumeMountPath"] == "/workspace"
    assert "volumeInGb" not in payload
    assert "containerDiskInGb" not in payload
    assert payload["ports"] == ["6901/http", "8001/http"]
    assert payload["env"]["NVIDIA_DRIVER_CAPABILITIES"] == (
        "compute,utility,graphics,display,video"
    )
    with pytest.raises(ValueError, match="immutable"):
        await runpod.update_pod_runtime(
            "pod-safe-123",
            image_name="ghcr.io/astrofood/ai-council-blender:latest",
            agent_token="a" * 48,
            kasm_password="b" * 20,
        )


@pytest.mark.asyncio
async def test_pod_lifecycle_uses_current_rest_contract(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def fake_rest(method, path, *, payload=None):
        calls.append((method, path))
        if method == "GET":
            return [{
                "id": "pod-safe-123",
                "desiredStatus": "RUNNING" if len(calls) == 2 else "EXITED",
                "gpu": {"count": 1},
            }]
        return {
            "id": "pod-safe-123",
            "desiredStatus": "RUNNING" if path.endswith("/start") else "EXITED",
            "gpu": {"count": 1},
        }

    monkeypatch.setattr(runpod, "_rest", fake_rest)
    started = await runpod.resume_pod("pod-safe-123")
    stopped = await runpod.stop_pod("pod-safe-123")

    assert calls == [
        ("POST", "/pods/pod-safe-123/start"),
        ("GET", "/pods?id=pod-safe-123"),
        ("POST", "/pods/pod-safe-123/stop"),
        ("GET", "/pods?id=pod-safe-123"),
    ]
    assert started["desired_status"] == "RUNNING"
    assert stopped["desired_status"] == "EXITED"


@pytest.mark.asyncio
async def test_list_pods_uses_current_rest_shape(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def fake_rest(method, path, *, payload=None):
        calls.append((method, path))
        return [{
            "id": "pod-safe-123",
            "name": "A6000 smoke",
            "desiredStatus": "EXITED",
            "image": "runpod/pytorch:current",
            "gpu": {"count": 1},
            "costPerHr": "0.53",
            "ports": ["6901/http", "8001/http"],
        }]

    monkeypatch.setattr(runpod, "_rest", fake_rest)
    pods = await runpod.list_pods()
    assert calls == [("GET", "/pods")]
    assert pods[0]["gpu_count"] == 1
    assert pods[0]["cost_per_hour"] == 0.53
    assert pods[0]["proxy_url"] == "https://pod-safe-123-6901.proxy.runpod.net"


@pytest.mark.asyncio
async def test_blender_template_is_immutable_reusable_and_contains_no_secrets(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []
    image = f"ghcr.io/astrofood/ai-council-blender:{'c' * 40}"

    async def fake_rest(method, path, *, payload=None):
        calls.append((method, path, payload))
        if method == "GET":
            return []
        return {
            "id": "template-safe-1",
            "name": payload["name"],
            "imageName": payload["imageName"],
            "containerDiskInGb": payload["containerDiskInGb"],
            "volumeInGb": payload["volumeInGb"],
            "volumeMountPath": payload["volumeMountPath"],
            "ports": payload["ports"],
        }

    monkeypatch.setattr(runpod, "_rest", fake_rest)
    template = await runpod.ensure_blender_template(image_name=image)
    assert calls[0][:2] == ("GET", "/templates")
    assert calls[1][:2] == ("POST", "/templates")
    request = calls[1][2]
    assert request["imageName"] == image
    assert request["volumeInGb"] == 250
    assert request["ports"] == ["6901/http", "8001/http"]
    assert "BLENDER_AGENT_TOKEN" not in request["env"]
    assert "VNC_PW" not in request["env"]
    assert template["id"] == "template-safe-1"


@pytest.mark.asyncio
async def test_a6000_provisioning_is_exactly_one_secure_on_demand_gpu(monkeypatch):
    captured: dict[str, object] = {}
    image = f"ghcr.io/astrofood/ai-council-blender:{'d' * 40}"

    async def fake_list_pods():
        return []

    async def fake_rest(method, path, *, payload=None):
        captured.update({"method": method, "path": path, "payload": payload})
        return {
            "id": "pod-a6000-safe",
            "name": payload["name"],
            "desiredStatus": "RUNNING",
            "imageName": payload["imageName"],
            "gpuCount": 1,
            "ports": payload["ports"],
        }

    monkeypatch.setattr(runpod, "list_pods", fake_list_pods)
    monkeypatch.setattr(runpod, "_rest", fake_rest)
    pod = await runpod.create_a6000_pod(
        template_id="template-safe-1",
        image_name=image,
        agent_token="a" * 48,
        kasm_password="b" * 20,
        idempotency_key="provision-test-123",
    )
    request = captured["payload"]
    assert captured["method"] == "POST"
    assert captured["path"] == "/pods"
    assert request["cloudType"] == "SECURE"
    assert request["interruptible"] is False
    assert request["gpuCount"] == 1
    assert request["gpuTypeIds"] == ["NVIDIA RTX A6000"]
    assert request["gpuTypePriority"] == "custom"
    assert request["minRAMPerGPU"] == 64
    assert request["volumeInGb"] == 250
    assert request["volumeMountPath"] == "/workspace"
    assert pod["gpu_count"] == 1


@pytest.mark.asyncio
async def test_render_snapshots_are_idempotent_and_truthful(session_factory, monkeypatch):
    monkeypatch.setattr(rendering.db, "async_session", session_factory)
    async with session_factory() as session:
        job = RenderJobModel(
            pod_id="pod-safe-123",
            source_path="/workspace/scene.blend",
            frame_step=3,
            settings={"requested_frame_step": 3},
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = job.id

    assert await rendering.ensure_frames(job_id, 1, 3) == 3
    assert await rendering.ensure_frames(job_id, 1, 3) == 3
    await rendering.persist_agent_snapshot(
        job_id,
        stage="render.frame_batch",
        agent_state={
            "status": "completed",
            "telemetry": [{
                "gpu_index": 0,
                "blender_pid": 123,
                "gpu_utilization": 91,
                "vram_used_mb": 20_000,
                "vram_total_mb": 48_000,
                "power_watts": 260,
                "host_ram_used_mb": 30_000,
                "host_ram_total_mb": 64_000,
            }],
            "report": {"frames": [{
                "frame_number": 1,
                "status": "completed",
                "output_path": "/workspace/render_jobs/job/frames/frame_000001.png",
                "checksum": "f" * 64,
                "size_bytes": 1024,
                "render_seconds": 30.0,
            }]},
        },
    )
    counted = await rendering.refresh_frame_counts(job_id)
    assert counted.expected_frame_count == 3
    assert counted.completed_frame_count == 1
    assert len(await rendering.list_frames(job_id)) == 3
    samples = await rendering.list_telemetry(job_id)
    assert samples[0]["blender_pid"] == 123
    assert samples[0]["gpu_utilization"] == 91


@pytest.mark.asyncio
async def test_preflight_snapshot_preserves_requested_frame_step(session_factory, monkeypatch):
    monkeypatch.setattr(rendering.db, "async_session", session_factory)
    async with session_factory() as session:
        job = RenderJobModel(
            pod_id="pod-safe-123",
            source_path="/workspace/scene.blend",
            frame_step=3,
            settings={"requested_frame_step": 3},
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = job.id

    updated = await rendering.persist_agent_snapshot(
        job_id,
        stage="render.preflight",
        agent_state={
            "status": "completed",
            "report": {
                "source_checksum": "a" * 64,
                "scene": {"frame_start": 1, "frame_end": 10, "frame_step": 1},
            },
        },
    )
    assert updated.frame_step == 3
    assert updated.expected_frame_count == 4


@pytest.mark.asyncio
async def test_render_stage_job_type_is_persisted(session_factory):
    async with session_factory() as session:
        run = WorkflowRunModel(
            workflow_id="blender_manager",
            job_type="blender.render_stage",
            payload={"render_job_id": "render-safe-123", "stage": "render.preflight"},
            idempotency_key="render:render-safe-123:render.preflight",
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        assert run.job_type == "blender.render_stage"
