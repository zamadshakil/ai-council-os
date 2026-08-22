from __future__ import annotations

import pytest

from src.core.jobs import JobService
from src.core.models import WorkflowRunModel
from src.integrations import runpod
from src.scripts.blender_listener import (
    TemplateJobRequest,
    _gpu_evidence,
    _nvml_running_pids,
    _within_workspace,
)


def test_blender_agent_rejects_traversal_and_arbitrary_output(monkeypatch, tmp_path):
    monkeypatch.setenv("BLENDER_WORKSPACE_ROOT", str(tmp_path))
    scene = tmp_path / "scene.blend"
    scene.write_bytes(b"BLENDER")

    assert _within_workspace("scene.blend", must_exist=True) == scene.resolve()
    with pytest.raises(ValueError, match="inside the Blender workspace"):
        _within_workspace("../outside.blend", must_exist=False)
    with pytest.raises(ValueError, match="simple .blend"):
        TemplateJobRequest(
            job_id="job-safe-123",
            source_path="scene.blend",
            output_name="../../payload.py",
        )


def test_runpod_agent_url_is_derived_from_validated_pod_and_port(monkeypatch):
    monkeypatch.setenv("BLENDER_AGENT_PORT", "8001")
    assert runpod._agent_base_url("pod-safe_123") == (
        "https://pod-safe_123-8001.proxy.runpod.net"
    )
    monkeypatch.setenv("BLENDER_AGENT_PORT", "not-a-port")
    with pytest.raises(runpod.RunPodError, match="port is invalid"):
        runpod._agent_base_url("pod-safe_123")


def test_nvml_process_evidence_combines_compute_and_graphics_contexts():
    class Process:
        def __init__(self, pid):
            self.pid = pid

    class NvmlError(Exception):
        pass

    class FakeNvml:
        NVMLError = NvmlError

        @staticmethod
        def nvmlDeviceGetComputeRunningProcesses(_handle):
            return [Process(101), Process(202)]

        @staticmethod
        def nvmlDeviceGetGraphicsRunningProcesses(_handle):
            return [Process(202), Process(303)]

    assert _nvml_running_pids(FakeNvml, object()) == [101, 202, 303]


def test_nvml_process_evidence_survives_one_unsupported_context_class():
    class Process:
        pid = 404

    class NvmlError(Exception):
        pass

    class FakeNvml:
        NVMLError = NvmlError

        @staticmethod
        def nvmlDeviceGetComputeRunningProcesses(_handle):
            raise NvmlError("not supported")

        @staticmethod
        def nvmlDeviceGetGraphicsRunningProcesses(_handle):
            return [Process()]

    assert _nvml_running_pids(FakeNvml, object()) == [404]


def _completed_optix_report() -> dict:
    return {
        "status": "completed",
        "source_unchanged": True,
        "cycles_backend_selected": "OPTIX",
        "gpu": {
            "enabled_gpu_count": 1,
            "devices": [
                {"name": "NVIDIA RTX A6000", "type": "OPTIX", "enabled": True}
            ],
        },
        "frames": [
            {
                "frame_number": 1,
                "status": "completed",
                "attempts": 1,
                "size_bytes": 9_000_000,
            }
        ],
    }


def test_gpu_evidence_prefers_direct_nvml_pid_binding():
    report = _completed_optix_report()
    evidence = _gpu_evidence(
        report,
        [
            {
                "blender_pid": 42,
                "managed_blender_pid": 42,
                "managed_process_alive": True,
                "nvml_pids": [42],
                "gpu_utilization": 80,
                "vram_used_mb": 2_500,
                "vram_total_mb": 49_000,
                "host_ram_used_mb": 1_000,
                "host_ram_total_mb": 64_000,
                "power_watts": 250,
            },
            {
                "blender_pid": 42,
                "managed_blender_pid": 42,
                "managed_process_alive": True,
                "nvml_pids": [42],
                "gpu_utilization": 85,
                "vram_used_mb": 2_600,
                "vram_total_mb": 49_000,
                "host_ram_used_mb": 1_010,
                "host_ram_total_mb": 64_000,
                "power_watts": 260,
            },
        ],
        baseline=[{"gpu_utilization": 0, "vram_used_mb": 100}],
        target_pid=42,
    )

    assert evidence["gpu_process_observed"] is True
    assert evidence["gpu_compute_observed"] is True
    assert evidence["gpu_process_binding"] == "direct_nvml_pid"
    assert evidence["nvml_pid_namespace_mismatch_observed"] is False
    assert evidence["direct_nvml_pid_sample_count"] == 2


def test_gpu_evidence_correlates_isolated_container_workload_when_nvml_uses_host_pid():
    report = _completed_optix_report()
    evidence = _gpu_evidence(
        report,
        [
            {
                "blender_pid": None,
                "managed_blender_pid": 42,
                "managed_process_alive": True,
                "nvml_pids": [31_337],
                "gpu_utilization": 99,
                "vram_used_mb": 2_800,
                "vram_total_mb": 49_000,
                "host_ram_used_mb": 1_000,
                "host_ram_total_mb": 64_000,
                "power_watts": 270,
            },
            {
                "blender_pid": None,
                "managed_blender_pid": 42,
                "managed_process_alive": True,
                "nvml_pids": [],
                "gpu_utilization": 95,
                "vram_used_mb": 2_700,
                "vram_total_mb": 49_000,
                "host_ram_used_mb": 1_020,
                "host_ram_total_mb": 64_000,
                "power_watts": 260,
            },
        ],
        baseline=[{"gpu_utilization": 1, "vram_used_mb": 120}],
        target_pid=42,
    )

    assert evidence["gpu_process_observed"] is True
    assert evidence["gpu_compute_observed"] is True
    assert evidence["gpu_process_binding"] == "isolated_workload_window"
    assert evidence["nvml_pid_namespace_mismatch_observed"] is True
    assert evidence["baseline_vram_mb"] == 120
    assert evidence["correlated_gpu_sample_count"] == 2


def test_gpu_evidence_correlates_when_managed_platform_hides_nvml_process_list():
    report = _completed_optix_report()
    telemetry = [
        {
            "blender_pid": None,
            "managed_blender_pid": 42,
            "managed_process_alive": True,
            "nvml_pids": [],
            "gpu_utilization": utilization,
            "vram_used_mb": 2_600,
            "vram_total_mb": 49_000,
            "host_ram_used_mb": 1_000,
            "host_ram_total_mb": 64_000,
            "power_watts": 250,
        }
        for utilization in (90, 99)
    ]

    evidence = _gpu_evidence(
        report,
        telemetry,
        baseline=[{"gpu_utilization": 0, "vram_used_mb": 100}],
        target_pid=42,
    )

    assert evidence["gpu_process_observed"] is True
    assert evidence["gpu_compute_observed"] is True
    assert evidence["gpu_process_binding"] == "isolated_workload_window"
    assert evidence["nvml_pid_namespace_mismatch_observed"] is False
    assert evidence["nvml_context_count_max"] == 0


def test_gpu_evidence_never_accepts_utilization_without_new_frame_and_gpu_device():
    report = _completed_optix_report()
    report["frames"][0]["reused"] = True
    report["gpu"]["enabled_gpu_count"] = 0
    evidence = _gpu_evidence(
        report,
        [
            {
                "blender_pid": None,
                "managed_blender_pid": 42,
                "managed_process_alive": True,
                "nvml_pids": [31_337],
                "gpu_utilization": 99,
                "vram_used_mb": 2_800,
                "vram_total_mb": 49_000,
                "host_ram_used_mb": 1_000,
                "host_ram_total_mb": 64_000,
                "power_watts": 270,
            },
            {
                "blender_pid": None,
                "managed_blender_pid": 42,
                "managed_process_alive": True,
                "nvml_pids": [],
                "gpu_utilization": 95,
                "vram_used_mb": 2_700,
                "vram_total_mb": 49_000,
                "host_ram_used_mb": 1_020,
                "host_ram_total_mb": 64_000,
                "power_watts": 260,
            },
        ],
        baseline=[{"gpu_utilization": 0, "vram_used_mb": 100}],
        target_pid=42,
    )

    assert evidence["gpu_process_observed"] is False
    assert evidence["gpu_compute_observed"] is False
    assert evidence["gpu_process_binding"] == "none"


@pytest.mark.asyncio
async def test_agent_verification_rejects_software_only_interactive_3d(monkeypatch):
    async def software_only(*_args, **_kwargs):
        return {
            "blender_available": True,
            "nvidia_smi_available": True,
            "gpu_visible": True,
            "workspace_writable": True,
            "required_tools": {"browser": True, "image_viewer": True},
            "desktop": {"ready": True},
            "interactive_3d_acceleration_ready": False,
        }

    monkeypatch.setattr(runpod, "_agent_request", software_only)
    monkeypatch.setattr(runpod, "_verify_kasm_proxy", lambda *_args: None)
    with pytest.raises(runpod.RunPodError) as error:
        await runpod.verify_blender_agent("pod-safe-123")
    assert error.value.code == "BLENDER_INTERACTIVE_GPU_NOT_READY"


@pytest.mark.asyncio
async def test_agent_verification_accepts_virtualgl_nvidia_path(monkeypatch):
    async def accelerated(*_args, **_kwargs):
        return {
            "blender_available": True,
            "nvidia_smi_available": True,
            "gpu_visible": True,
            "workspace_writable": True,
            "required_tools": {"browser": True, "image_viewer": True},
            "desktop": {"ready": True},
            "interactive_3d_acceleration_ready": True,
            "virtualgl_renderer": "NVIDIA RTX A6000/PCIe/SSE2",
        }

    monkeypatch.setattr(runpod, "_agent_request", accelerated)
    async def kasm_ready(*_args, **_kwargs):
        return None

    monkeypatch.setattr(runpod, "_verify_kasm_proxy", kasm_ready)
    result = await runpod.verify_blender_agent("pod-safe-123")
    assert result["interactive_3d_acceleration_ready"] is True
    assert result["kasm_proxy_reachable"] is True


@pytest.mark.asyncio
async def test_blender_job_progress_is_durable(session_factory):
    jobs = JobService(session_factory=session_factory)
    queued = await jobs.enqueue(
        workflow_id="blender_manager",
        job_type="blender.template_repair",
        payload={"pod_id": "pod-safe-123", "source_path": "/workspace/scene.blend"},
        idempotency_key="blender:durable-progress",
    )
    claim = await jobs.claim("blender-test-worker")
    assert claim is not None and claim.id == queued.id
    await jobs.progress(claim.id, "blender-test-worker", {"stage": "gpu_repair_and_benchmark"})

    async with session_factory() as session:
        saved = await session.get(WorkflowRunModel, queued.id)
    assert saved is not None
    assert saved.status == "running"
    assert saved.result == {"stage": "gpu_repair_and_benchmark"}
