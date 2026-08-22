"""Authenticated RunPod-side Blender production agent.

Only allowlisted render operations are exposed. The service never accepts
Python, shell commands, environment variables, or arbitrary destinations from
the dashboard.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

try:
    from . import desktop_control, flamenco_control
except ImportError:  # Flat /opt/council layout inside the RunPod image.
    import desktop_control
    import flamenco_control


JOB_ID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
OUTPUT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.blend$")
SAFE_REMOTE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ./_-]{0,500}$")
_processes: dict[str, asyncio.subprocess.Process] = {}
_cancel_events: dict[str, asyncio.Event] = {}
_tasks: set[asyncio.Task[Any]] = set()
_operation_lock = asyncio.Lock()


class JobCancelledError(RuntimeError):
    """Raised when the administrator cancels an allowlisted pod operation."""


def _raise_if_cancelled(job_id: str) -> None:
    event = _cancel_events.get(job_id)
    if event is not None and event.is_set():
        raise JobCancelledError("Cancelled by administrator")


async def _wait_process_or_cancel(
    job_id: str,
    process: asyncio.subprocess.Process,
) -> int:
    """Wait for a child process while making cancellation authoritative."""
    event = _cancel_events.get(job_id)
    if event is None:
        return await process.wait()
    _raise_if_cancelled(job_id)
    process_wait = asyncio.create_task(process.wait())
    cancel_wait = asyncio.create_task(event.wait())
    try:
        done, _ = await asyncio.wait(
            {process_wait, cancel_wait}, return_when=asyncio.FIRST_COMPLETED
        )
        if cancel_wait in done and cancel_wait.result():
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(asyncio.shield(process_wait), timeout=20)
                except TimeoutError:
                    process.kill()
                    await process_wait
            raise JobCancelledError("Cancelled by administrator")
        return_code = await process_wait
        _raise_if_cancelled(job_id)
        return return_code
    finally:
        for task in (process_wait, cancel_wait):
            if not task.done():
                task.cancel()
        await asyncio.gather(process_wait, cancel_wait, return_exceptions=True)


async def _communicate_or_cancel(
    job_id: str,
    process: asyncio.subprocess.Process,
    input_data: bytes | None = None,
) -> tuple[bytes, bytes]:
    """Communicate with a child process without losing cancellation."""
    event = _cancel_events.get(job_id)
    if event is None:
        return await process.communicate(input_data)
    _raise_if_cancelled(job_id)
    communicate = asyncio.create_task(process.communicate(input_data))
    cancel_wait = asyncio.create_task(event.wait())
    try:
        done, _ = await asyncio.wait(
            {communicate, cancel_wait}, return_when=asyncio.FIRST_COMPLETED
        )
        if cancel_wait in done and cancel_wait.result():
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(asyncio.shield(communicate), timeout=20)
                except TimeoutError:
                    process.kill()
                    await communicate
            raise JobCancelledError("Cancelled by administrator")
        output = await communicate
        _raise_if_cancelled(job_id)
        return output
    finally:
        for task in (communicate, cancel_wait):
            if not task.done():
                task.cancel()
        await asyncio.gather(communicate, cancel_wait, return_exceptions=True)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TemplateJobRequest(StrictModel):
    """Legacy request shape retained only for safe compatibility validation."""

    job_id: str = Field(min_length=8, max_length=128)
    source_path: str = Field(min_length=7, max_length=500)
    output_name: str = Field(min_length=7, max_length=126)
    frame: int = Field(default=1, ge=0, le=1_000_000)
    samples: int = Field(default=64, ge=1, le=4096)
    resolution_percent: int = Field(default=25, ge=1, le=100)

    @field_validator("job_id")
    @classmethod
    def valid_job_id(cls, value: str) -> str:
        if not JOB_ID.fullmatch(value):
            raise ValueError("Invalid job identifier")
        return value

    @field_validator("output_name")
    @classmethod
    def valid_output_name(cls, value: str) -> str:
        if not OUTPUT_NAME.fullmatch(value):
            raise ValueError("Output must be a simple .blend filename")
        return value


class RenderStageRequest(StrictModel):
    job_id: str = Field(min_length=8, max_length=128)
    render_job_id: str = Field(min_length=8, max_length=128)
    operation: Literal[
        "preflight", "benchmark", "observe_gui", "frame_batch",
        "prepare_flamenco", "validate", "encode", "deliver",
    ]
    source_path: str = Field(min_length=7, max_length=1000)
    output_profile: Literal["delivery", "compositing"] = "delivery"
    frames: list[int] = Field(default_factory=list, max_length=50)
    frame_start: int | None = Field(default=None, ge=0, le=1_000_000)
    frame_end: int | None = Field(default=None, ge=0, le=1_000_000)
    frame_step: int = Field(default=1, ge=1, le=1000)
    samples: int = Field(default=0, ge=0, le=4096)
    resolution_percent: int = Field(default=100, ge=1, le=100)
    expected_width: int | None = Field(default=None, ge=1, le=32768)
    expected_height: int | None = Field(default=None, ge=1, le=32768)
    persistent_data: bool = False
    backend: Literal["AUTO", "OPTIX", "CUDA"] = "AUTO"
    fps: float = Field(default=24.0, gt=0, le=240)
    drive_path: str = Field(default="Council OS Renders", max_length=500)
    require_drive: bool = True
    include_audio: bool = False

    @field_validator("job_id", "render_job_id")
    @classmethod
    def valid_ids(cls, value: str) -> str:
        if not JOB_ID.fullmatch(value):
            raise ValueError("Invalid job identifier")
        return value

    @field_validator("source_path")
    @classmethod
    def source_is_blend(cls, value: str) -> str:
        if not value.lower().endswith(".blend"):
            raise ValueError("Source must be a .blend file")
        return value

    @field_validator("frames")
    @classmethod
    def unique_frames(cls, value: list[int]) -> list[int]:
        if any(frame < 0 or frame > 1_000_000 for frame in value):
            raise ValueError("Frame number is outside the supported range")
        return sorted(set(value))

    @field_validator("drive_path")
    @classmethod
    def safe_drive_path(cls, value: str) -> str:
        if value and (not SAFE_REMOTE_PATH.fullmatch(value) or ".." in value.split("/")):
            raise ValueError("Drive path contains unsupported characters")
        return value.strip(" /")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _workspace() -> Path:
    return Path(os.getenv("BLENDER_WORKSPACE_ROOT", "/workspace")).resolve()


def _job_root() -> Path:
    value = _workspace() / ".council-blender-jobs"
    value.mkdir(parents=True, exist_ok=True)
    return value


def _render_root(render_job_id: str) -> Path:
    if not JOB_ID.fullmatch(render_job_id):
        raise ValueError("Invalid render job identifier")
    value = _workspace() / "render_jobs" / render_job_id
    value.mkdir(parents=True, exist_ok=True)
    return value


def _within_workspace(value: str, *, must_exist: bool) -> Path:
    root = _workspace()
    candidate = Path(value)
    candidate = candidate if candidate.is_absolute() else root / candidate
    candidate = candidate.resolve(strict=must_exist)
    if candidate != root and root not in candidate.parents:
        raise ValueError("Template path must stay inside the Blender workspace")
    return candidate


def _state_path(job_id: str) -> Path:
    return _job_root() / job_id / "job.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_state(job_id: str) -> dict[str, Any] | None:
    path = _state_path(job_id)
    return _read_json(path) if path.exists() else None


def _write_state(job_id: str, value: dict[str, Any]) -> None:
    path = _state_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def _log_tail(job_id: str, maximum: int = 100) -> list[str]:
    path = _state_path(job_id).parent / "operation.log"
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-maximum:]
    except OSError:
        return []


def _telemetry_tail(job_id: str, maximum: int = 180) -> list[dict[str, Any]]:
    path = _state_path(job_id).parent / "telemetry.jsonl"
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-maximum:]
        return [value for line in lines if isinstance((value := json.loads(line)), dict)]
    except (OSError, json.JSONDecodeError):
        return []


def _public_state(job_id: str) -> dict[str, Any]:
    state = _read_state(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Blender job not found")
    return {**state, "log_tail": _log_tail(job_id), "telemetry": _telemetry_tail(job_id)}


async def _authorize(authorization: str = Header(default="")) -> None:
    expected = os.getenv("BLENDER_AGENT_TOKEN", "").strip()
    supplied = authorization.removeprefix("Bearer ").strip()
    if len(expected) < 32 or not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="Blender agent authentication failed")


async def _authorize_worker_proxy(authorization: str = Header(default="")) -> None:
    """Authenticate a remote Worker without granting pod-agent privileges."""
    expected = os.getenv("FLAMENCO_WORKER_PROXY_TOKEN", "").strip()
    supplied = authorization.removeprefix("Bearer ").strip()
    if len(expected) < 32 or not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="Flamenco Worker proxy authentication failed")


def _command_output(command: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        return result.returncode, (result.stdout or result.stderr or "").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"{type(exc).__name__}: {exc}"


def _runtime_health() -> dict[str, Any]:
    blender = os.getenv("BLENDER_BINARY", "blender").strip() or "blender"
    blender_code, blender_output = _command_output([blender, "--version"])
    nvidia_code, nvidia_output = _command_output([
        "nvidia-smi", "--query-gpu=index,name,driver_version,memory.total",
        "--format=csv,noheader,nounits",
    ])
    gpus = []
    if nvidia_code == 0:
        for line in nvidia_output.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) >= 4:
                gpus.append({"index": int(parts[0]), "name": parts[1], "driver_version": parts[2], "vram_total_mb": float(parts[3])})
    renderer = ""
    virtualgl_renderer = ""
    virtualgl_display = ""
    display = os.getenv("DISPLAY", "").strip()
    if display and shutil.which("glxinfo"):
        code, output = _command_output(["glxinfo", "-B"])
        if code == 0:
            renderer = next((line.split(":", 1)[1].strip() for line in output.splitlines() if "OpenGL renderer string" in line), "")
        virtualgl = shutil.which("vglrun")
        if not virtualgl and Path("/opt/VirtualGL/bin/vglrun").is_file():
            virtualgl = "/opt/VirtualGL/bin/vglrun"
        if virtualgl:
            for candidate in ("egl0", "egl"):
                vgl_code, vgl_output = _command_output(
                    [virtualgl, "-d", candidate, "glxinfo", "-B"], timeout=30
                )
                if vgl_code != 0:
                    continue
                detected = next(
                    (
                        line.split(":", 1)[1].strip()
                        for line in vgl_output.splitlines()
                        if "OpenGL renderer string" in line
                    ),
                    "",
                )
                if detected and "llvmpipe" not in detected.lower() and "software" not in detected.lower():
                    virtualgl_renderer = detected
                    virtualgl_display = candidate
                    break
    workspace_writable = False
    workspace_error = ""
    try:
        readiness_directory = _workspace() / ".council-blender"
        readiness_directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".workspace-readiness-",
            dir=readiness_directory,
        ) as readiness_probe:
            readiness_probe.write(_utcnow())
            readiness_probe.flush()
            os.fsync(readiness_probe.fileno())
        workspace_writable = True
    except OSError as exc:
        workspace_error = f"{type(exc).__name__}: {exc}"[:300]
    required_tools = {
        "browser": bool(shutil.which("google-chrome")),
        "image_viewer": bool(shutil.which("ristretto")),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "rclone": bool(shutil.which("rclone")),
        "flamenco_manager": Path("/opt/flamenco/flamenco-manager").is_file(),
        "flamenco_worker": Path("/opt/flamenco/flamenco-worker").is_file(),
    }
    try:
        import psutil

        memory = psutil.virtual_memory()
        workspace_disk = shutil.disk_usage(_workspace())
        workspace_fs = os.statvfs(_workspace())
        host = {
            "host_ram_total_mb": round(memory.total / 1024 / 1024, 2),
            "host_ram_available_mb": round(memory.available / 1024 / 1024, 2),
            "workspace_total_bytes": int(workspace_disk.total),
            "workspace_free_bytes": int(workspace_disk.free),
            "workspace_free_inodes": int(workspace_fs.f_favail),
        }
    except (OSError, ImportError, AttributeError):
        host = {}
    desktop = desktop_control.status()
    interactive_3d_acceleration_ready = bool(
        renderer
        and "llvmpipe" not in renderer.lower()
        and "software" not in renderer.lower()
    ) or bool(virtualgl_renderer)
    ready = (
        blender_code == 0
        and nvidia_code == 0
        and bool(gpus)
        and bool(desktop.get("ready"))
        and interactive_3d_acceleration_ready
        and workspace_writable
        and all(required_tools.values())
    )
    return {
        "status": "ok" if ready else "not_ready",
        "ready": ready,
        "blender_available": blender_code == 0,
        "blender_version": blender_output.splitlines()[0] if blender_output else "",
        "nvidia_smi_available": nvidia_code == 0,
        "gpus": gpus,
        "gpu_visible": bool(gpus),
        "display": display,
        "opengl_renderer": renderer,
        "opengl_hardware_accelerated": bool(renderer and "llvmpipe" not in renderer.lower() and "software" not in renderer.lower()),
        "virtualgl_available": bool(virtualgl_renderer),
        "virtualgl_renderer": virtualgl_renderer,
        "virtualgl_display": virtualgl_display,
        "interactive_3d_acceleration_ready": interactive_3d_acceleration_ready,
        "workspace_writable": workspace_writable,
        "workspace_error": workspace_error,
        "required_tools": required_tools,
        "desktop": desktop,
        **host,
    }


def _runtime_snapshot() -> dict[str, Any]:
    samples = _sample_gpu()
    blender_processes: list[dict[str, Any]] = []
    try:
        import psutil

        for process in psutil.process_iter(["pid", "name"]):
            name = str(process.info.get("name") or "")
            if "blender" in name.lower():
                blender_processes.append({"pid": int(process.info["pid"]), "name": name})
    except Exception:
        blender_processes = []
    root = _workspace() / ".council-blender"
    return {
        "status": "ok",
        "sampled_at": _utcnow(),
        "gpu_samples": samples,
        "blender_processes": blender_processes,
        "gui_state": _read_json(root / "gui_state.json"),
        "managed_render": _read_json(root / "active_render.json"),
    }


def _sample_gpu(target_pid: int | None = None) -> list[dict[str, Any]]:
    try:
        import psutil
        import pynvml

        pynvml.nvmlInit()
        memory = psutil.virtual_memory()
        samples: list[dict[str, Any]] = []
        try:
            count = pynvml.nvmlDeviceGetCount()
            for index in range(count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(index)
                utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
                vram = pynvml.nvmlDeviceGetMemoryInfo(handle)
                try:
                    power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
                except pynvml.NVMLError:
                    power = 0.0
                pids = _nvml_running_pids(pynvml, handle)
                direct_pid_match = bool(target_pid and target_pid in pids)
                blender_pid = target_pid if direct_pid_match else next((pid for pid in pids if _is_blender_pid(pid)), None)
                samples.append({
                    "sampled_at": _utcnow(), "gpu_index": index,
                    "blender_pid": blender_pid,
                    "managed_blender_pid": target_pid,
                    "managed_process_alive": bool(target_pid and _is_blender_pid(target_pid)),
                    "nvml_pids": pids,
                    "nvml_pid_namespace_match": direct_pid_match,
                    "gpu_utilization": float(utilization.gpu),
                    "vram_used_mb": round(vram.used / 1024 / 1024, 2),
                    "vram_total_mb": round(vram.total / 1024 / 1024, 2),
                    "power_watts": round(power, 2),
                    "host_ram_used_mb": round(memory.used / 1024 / 1024, 2),
                    "host_ram_total_mb": round(memory.total / 1024 / 1024, 2),
                })
            return samples
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        return []


def _nvml_running_pids(pynvml: Any, handle: Any) -> list[int]:
    """Return every process using the device across NVML context classes.

    OptiX/Cycles is reported as a compute process on some driver branches and
    as a graphics process on others. Looking at only the compute list caused
    real 99%-utilized A6000 renders to fail the PID-evidence gate. A process is
    accepted only when NVML itself reports it in either allowlisted list.
    """
    pids: set[int] = set()
    for getter_name in (
        "nvmlDeviceGetComputeRunningProcesses",
        "nvmlDeviceGetGraphicsRunningProcesses",
    ):
        getter = getattr(pynvml, getter_name, None)
        if getter is None:
            continue
        try:
            processes = getter(handle)
        except pynvml.NVMLError:
            continue
        for process in processes or []:
            try:
                pids.add(int(process.pid))
            except (AttributeError, TypeError, ValueError):
                continue
    return sorted(pids)


def _is_blender_pid(pid: int) -> bool:
    try:
        import psutil
        return "blender" in psutil.Process(pid).name().lower()
    except Exception:
        return False


async def _monitor(job_id: str, done: asyncio.Event, target_pid: int | None = None) -> None:
    path = _state_path(job_id).parent / "telemetry.jsonl"
    while not done.is_set():
        samples = await asyncio.to_thread(_sample_gpu, target_pid)
        if samples:
            with path.open("a", encoding="utf-8") as handle:
                for sample in samples:
                    handle.write(json.dumps(sample, separators=(",", ":")) + "\n")
        try:
            await asyncio.wait_for(done.wait(), timeout=2.0)
        except TimeoutError:
            pass


def _enabled_gpu_reported(report: dict[str, Any]) -> bool:
    gpu = report.get("gpu") if isinstance(report.get("gpu"), dict) else {}
    devices = gpu.get("devices") if isinstance(gpu.get("devices"), list) else []
    return bool(
        str(report.get("cycles_backend_selected") or "") in {"OPTIX", "CUDA"}
        and int(gpu.get("enabled_gpu_count") or 0) > 0
        and any(
            isinstance(device, dict)
            and device.get("enabled") is True
            and str(device.get("type") or "").upper() != "CPU"
            for device in devices
        )
    )


def _completed_new_frame(report: dict[str, Any]) -> bool:
    frames = report.get("frames") if isinstance(report.get("frames"), list) else []
    return any(
        isinstance(frame, dict)
        and frame.get("status") == "completed"
        and not frame.get("reused")
        and int(frame.get("attempts") or 0) > 0
        and int(frame.get("size_bytes") or 0) > 0
        for frame in frames
    )


def _gpu_evidence(
    report: dict[str, Any],
    telemetry: list[dict[str, Any]],
    *,
    baseline: list[dict[str, Any]] | None = None,
    target_pid: int | None = None,
) -> dict[str, Any]:
    """Bind GPU activity to one managed Blender execution window.

    NVML exposes host PIDs on container platforms that use an isolated PID
    namespace. In that topology the numeric Blender PID cannot equal NVML's
    PID even though both describe the same process. We prefer an exact PID
    match, but can prove attribution from four independent signals inside the
    agent's serialized render lock: Blender is alive, Blender selected an
    enabled CUDA/OptiX device, and utilization plus VRAM rise materially above
    a pre-spawn baseline while a new frame is produced. Requiring an NVML PID
    here would reintroduce the container namespace bug because some managed
    platforms hide the host process list entirely. The selected method is
    persisted so the dashboard never implies that a direct PID match occurred
    when it did not.
    """
    baseline = baseline or []
    attached = [sample for sample in telemetry if sample.get("blender_pid")]
    active = [sample for sample in attached if float(sample.get("gpu_utilization") or 0) > 0]
    managed = [sample for sample in telemetry if sample.get("managed_process_alive")]
    baseline_util = max(
        (float(sample.get("gpu_utilization") or 0) for sample in baseline),
        default=0.0,
    )
    baseline_vram = max(
        (float(sample.get("vram_used_mb") or 0) for sample in baseline),
        default=0.0,
    )
    utilization_floor = max(5.0, baseline_util + 5.0)
    correlated = [
        sample
        for sample in managed
        if float(sample.get("gpu_utilization") or 0) >= utilization_floor
        and float(sample.get("vram_used_mb") or 0) >= baseline_vram + 128.0
    ]
    namespace_correlated = bool(
        target_pid
        and not attached
        and len(correlated) >= 2
        and _enabled_gpu_reported(report)
        and report.get("source_unchanged") is True
        and _completed_new_frame(report)
    )
    direct_correlated = bool(
        target_pid
        and len(active) >= 2
        and _enabled_gpu_reported(report)
        and report.get("source_unchanged") is True
        and _completed_new_frame(report)
    )
    process_observed = direct_correlated or namespace_correlated
    compute_observed = direct_correlated or namespace_correlated
    binding_method = (
        "direct_nvml_pid"
        if direct_correlated
        else "isolated_workload_window"
        if namespace_correlated
        else "none"
    )
    observed = attached or correlated or telemetry
    utils = [float(sample.get("gpu_utilization") or 0) for sample in observed]
    vrams = [float(sample.get("vram_used_mb") or 0) for sample in observed]
    total_vrams = [float(sample.get("vram_total_mb") or 0) for sample in observed]
    host_ram = [float(sample.get("host_ram_used_mb") or 0) for sample in observed]
    host_total = [float(sample.get("host_ram_total_mb") or 0) for sample in observed]
    powers = [float(sample.get("power_watts") or 0) for sample in observed]
    memory_growth = 0.0
    if len(host_ram) > 1 and host_ram[0] > 0:
        memory_growth = ((host_ram[-1] - host_ram[0]) / host_ram[0]) * 100
    return {
        "cycles_backend_selected": str(report.get("cycles_backend_selected") or ""),
        "gpu_process_observed": process_observed,
        "gpu_compute_observed": compute_observed,
        "gpu_process_binding": binding_method,
        "direct_nvml_pid_sample_count": len(attached),
        "managed_blender_pid": target_pid,
        "nvml_pid_namespace_mismatch_observed": bool(
            target_pid
            and not attached
            and any(sample.get("nvml_pids") for sample in managed)
        ),
        "nvml_context_count_max": max(
            (len(sample.get("nvml_pids") or []) for sample in telemetry),
            default=0,
        ),
        "managed_process_sample_count": len(managed),
        "correlated_gpu_sample_count": len(correlated),
        "baseline_gpu_utilization": baseline_util,
        "baseline_vram_mb": baseline_vram,
        "average_gpu_utilization": round(sum(utils) / len(utils), 2) if utils else 0.0,
        "peak_gpu_utilization": max(utils, default=0.0),
        "peak_vram_mb": max(vrams, default=0.0),
        "vram_total_mb": max(total_vrams, default=0.0),
        "peak_host_ram_mb": max(host_ram, default=0.0),
        "host_ram_total_mb": max(host_total, default=0.0),
        "host_ram_growth_percent": round(memory_growth, 2),
        "peak_power_watts": max(powers, default=0.0),
        "power_draw_samples": powers[-180:],
    }


def _drive_remote() -> str:
    return os.getenv("BLENDER_GDRIVE_REMOTE", "gdrive:").strip() or "gdrive:"


def _classify_rclone(message: str) -> str:
    lowered = message.lower()
    if "storagequotaexceeded" in lowered or "storage quota" in lowered:
        return "delivery_blocked_storage_full"
    if "userratelimitexceeded" in lowered or "rate limit" in lowered or "429" in lowered:
        return "delivery_rate_limited"
    return "delivery_failed"


async def _drive_preflight(
    render_job_id: str,
    require_drive: bool,
    operation_job_id: str | None = None,
) -> dict[str, Any]:
    if not shutil.which("rclone"):
        return {"status": "blocked" if require_drive else "unconfigured", "error_code": "rclone_unavailable"}
    remote = _drive_remote()
    process = await asyncio.create_subprocess_exec("rclone", "about", remote, "--json", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    if operation_job_id:
        _processes[operation_job_id] = process
        stdout, stderr = await _communicate_or_cancel(operation_job_id, process)
    else:
        stdout, stderr = await process.communicate()
    if process.returncode != 0:
        message = stderr.decode(errors="replace")[-1000:]
        return {"status": "blocked" if require_drive else "unavailable", "error_code": _classify_rclone(message), "message": message}
    try:
        quota = json.loads(stdout.decode())
    except json.JSONDecodeError:
        quota = {}
    probe = f"{remote.rstrip(':')}:Council OS Renders/.probe/{render_job_id}.txt"
    writer = await asyncio.create_subprocess_exec("rclone", "rcat", probe, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    if operation_job_id:
        _processes[operation_job_id] = writer
        _, write_error = await _communicate_or_cancel(
            operation_job_id, writer, b"Council OS storage probe\n"
        )
    else:
        _, write_error = await writer.communicate(b"Council OS storage probe\n")
    if writer.returncode != 0:
        message = write_error.decode(errors="replace")[-1000:]
        return {"status": "blocked", "error_code": _classify_rclone(message), "quota": quota, "message": message}
    reader = await asyncio.create_subprocess_exec("rclone", "cat", probe, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    if operation_job_id:
        _processes[operation_job_id] = reader
        read_value, read_error = await _communicate_or_cancel(
            operation_job_id, reader
        )
    else:
        read_value, read_error = await reader.communicate()
    remover = await asyncio.create_subprocess_exec("rclone", "deletefile", probe, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    if operation_job_id:
        _processes[operation_job_id] = remover
        await _communicate_or_cancel(operation_job_id, remover)
    else:
        await remover.communicate()
    if reader.returncode != 0 or read_value != b"Council OS storage probe\n":
        return {"status": "blocked", "error_code": "drive_probe_read_failed", "quota": quota, "message": read_error.decode(errors="replace")[-1000:]}
    return {"status": "ready", "quota": quota, "write_probe": "passed"}


def _telemetry_samples(job_id: str) -> list[dict[str, Any]]:
    path = _state_path(job_id).parent / "telemetry.jsonl"
    if not path.exists():
        return []
    values: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-10_000:]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            values.append(item)
    return values


async def _run_blender_pass(
    request: RenderStageRequest,
    source: Path,
    output_directory: Path,
    job_dir: Path,
    *,
    pass_name: str,
    operation: Literal["preflight", "benchmark", "frame_batch", "prepare_flamenco"],
    frames: list[int],
    backend: Literal["AUTO", "OPTIX", "CUDA"],
    persistent_data: bool,
    profile: Literal["delivery", "compositing"],
) -> dict[str, Any]:
    """Run one trusted Blender process and bind NVML samples to that PID."""
    _raise_if_cancelled(request.job_id)
    report_path = job_dir / f"report-{pass_name}.json"
    log_path = job_dir / "operation.log"
    output_directory.mkdir(parents=True, exist_ok=True)
    before = len(_telemetry_samples(request.job_id))
    baseline: list[dict[str, Any]] = []
    for sample_index in range(3):
        _raise_if_cancelled(request.job_id)
        baseline.extend(await asyncio.to_thread(_sample_gpu))
        if sample_index < 2:
            await asyncio.sleep(0.25)
    command = [
        os.getenv("BLENDER_BINARY", "blender").strip() or "blender", "-b", str(source),
        "--python", str(Path(__file__).with_name("blender_job.py").resolve()), "--",
        "--operation", operation, "--source", str(source), "--report", str(report_path),
        "--output-directory", str(output_directory), "--frames", ",".join(map(str, frames)),
        "--samples", str(request.samples), "--resolution-percent", str(request.resolution_percent),
        "--profile", profile, "--persistent-data", "on" if persistent_data else "off",
        "--backend", backend,
    ]
    state = _read_state(request.job_id) or {}
    done = asyncio.Event()
    with log_path.open("ab") as log_file:
        log_file.write(f"\n=== {pass_name} {backend} persistent={persistent_data} ===\n".encode())
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=log_file,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(job_dir),
        )
        _processes[request.job_id] = process
        state.update({"status": "running", "stage": f"benchmark_{pass_name}" if request.operation == "benchmark" else request.operation, "pid": process.pid})
        _write_state(request.job_id, state)
        monitor = asyncio.create_task(_monitor(request.job_id, done, process.pid))
        try:
            return_code = await _wait_process_or_cancel(request.job_id, process)
        finally:
            done.set()
            await monitor
    _raise_if_cancelled(request.job_id)
    report = _read_json(report_path)
    samples = _telemetry_samples(request.job_id)[before:]
    report["gpu_evidence"] = _gpu_evidence(
        report,
        samples,
        baseline=baseline,
        target_pid=process.pid,
    )
    if return_code != 0 or report.get("status") not in {"completed", "blocked"}:
        raise RuntimeError(str(report.get("error") or f"Blender exited with code {return_code}"))
    return report


def _continuous_frames(start: int, end: int, step: int, count: int) -> list[int]:
    available = list(range(start, end + 1, max(1, step)))
    if len(available) <= count:
        return available
    center = len(available) // 2
    first = max(0, min(len(available) - count, center - count // 2))
    return available[first:first + count]


def _image_similarity(first: list[dict[str, Any]], second: list[dict[str, Any]]) -> float:
    """Return a tolerant visual score; never require byte-identical GPU output."""
    from PIL import Image, ImageChops, ImageStat

    second_by_frame = {int(item["frame_number"]): item for item in second}
    scores: list[float] = []
    for item in first:
        other = second_by_frame.get(int(item["frame_number"]))
        if not other:
            continue
        with Image.open(str(item["output_path"])) as left_image, Image.open(str(other["output_path"])) as right_image:
            left = left_image.convert("RGB").resize((256, 144))
            right = right_image.convert("RGB").resize((256, 144))
            rms = ImageStat.Stat(ImageChops.difference(left, right)).rms
            scores.append(max(0.0, 1.0 - (sum(rms) / max(1, len(rms))) / 255.0))
    return round(min(scores), 6) if scores else 0.0


def _usage_within_limits(evidence: dict[str, Any]) -> tuple[bool, dict[str, float]]:
    peak_vram = float(evidence.get("peak_vram_mb") or 0)
    total_vram = float(evidence.get("vram_total_mb") or 0)
    peak_ram = float(evidence.get("peak_host_ram_mb") or 0)
    total_ram = float(evidence.get("host_ram_total_mb") or 0)
    vram_percent = peak_vram / total_vram * 100 if total_vram else 100.0
    ram_percent = peak_ram / total_ram * 100 if total_ram else 100.0
    growth = float(evidence.get("host_ram_growth_percent") or 0)
    return (
        vram_percent < 80 and ram_percent < 80 and growth < 5,
        {
            "peak_vram_percent": round(vram_percent, 2),
            "peak_host_ram_percent": round(ram_percent, 2),
            "host_ram_growth_percent": round(growth, 2),
        },
    )


def _recommended_batch_size(usage: dict[str, float]) -> int:
    """Choose a conservative process size from measured soak behavior."""
    memory_growth = float(usage.get("host_ram_growth_percent") or 0)
    peak_usage = max(
        float(usage.get("peak_vram_percent") or 100),
        float(usage.get("peak_host_ram_percent") or 100),
    )
    if memory_growth > 1:
        return 1
    if peak_usage >= 70:
        return 2
    if peak_usage >= 60:
        return 5
    return 10


async def _run_benchmark(
    request: RenderStageRequest,
    source: Path,
    render_root: Path,
    job_dir: Path,
) -> dict[str, Any]:
    if request.frame_start is None or request.frame_end is None:
        raise RuntimeError("Scene frame range is required for benchmark and soak testing")
    representative = request.frames
    if not representative:
        raise RuntimeError("Representative benchmark frames are required")
    compare_reports: dict[str, dict[str, Any]] = {}
    failures: dict[str, str] = {}
    for backend in ("OPTIX", "CUDA"):
        _raise_if_cancelled(request.job_id)
        try:
            compare_reports[backend] = await _run_blender_pass(
                request,
                source,
                render_root / "previews" / "backend" / backend.lower(),
                job_dir,
                pass_name=f"backend-{backend.lower()}",
                operation="benchmark",
                frames=representative,
                backend=backend,
                persistent_data=False,
                profile="delivery",
            )
            if compare_reports[backend].get("status") != "completed":
                raise RuntimeError("backend pass was blocked")
        except JobCancelledError:
            raise
        except Exception as exc:
            failures[backend] = f"{type(exc).__name__}: {exc}"
    if not compare_reports:
        raise RuntimeError("Both OptiX and CUDA benchmark passes failed")
    similarity = 1.0
    if "OPTIX" in compare_reports and "CUDA" in compare_reports:
        similarity = await asyncio.to_thread(
            _image_similarity,
            list(compare_reports["OPTIX"].get("frames") or []),
            list(compare_reports["CUDA"].get("frames") or []),
        )
        if similarity < 0.99:
            raise RuntimeError("OptiX and CUDA previews were not visually equivalent")
    selected_backend = "OPTIX" if "OPTIX" in compare_reports else "CUDA"

    ten_frames = _continuous_frames(
        request.frame_start, request.frame_end, request.frame_step, 10
    )
    persistence: dict[str, dict[str, Any]] = {}
    for label, enabled in (("off", False), ("on", True)):
        _raise_if_cancelled(request.job_id)
        persistence[label] = await _run_blender_pass(
            request,
            source,
            render_root / "previews" / "persistence" / label,
            job_dir,
            pass_name=f"persistence-{label}",
            operation="benchmark",
            frames=ten_frames,
            backend=selected_backend,
            persistent_data=enabled,
            profile=request.output_profile,
        )
        if persistence[label].get("status") != "completed":
            raise RuntimeError(f"Persistent-data {label} benchmark was blocked")
    off_seconds = float(persistence["off"].get("average_frame_seconds") or 0)
    on_seconds = float(persistence["on"].get("average_frame_seconds") or 0)
    improvement = ((off_seconds - on_seconds) / off_seconds * 100) if off_seconds else 0.0
    persistent_safe, persistent_usage = _usage_within_limits(
        dict(persistence["on"].get("gpu_evidence") or {})
    )
    persistent_selected = improvement >= 15 and persistent_safe

    soak_frames = _continuous_frames(
        request.frame_start, request.frame_end, request.frame_step, 50
    )
    _raise_if_cancelled(request.job_id)
    soak = await _run_blender_pass(
        request,
        source,
        render_root / "previews" / "soak",
        job_dir,
        pass_name="soak-50",
        operation="benchmark",
        frames=soak_frames,
        backend=selected_backend,
        persistent_data=persistent_selected,
        profile=request.output_profile,
    )
    soak_evidence = dict(soak.get("gpu_evidence") or {})
    soak_safe, soak_usage = _usage_within_limits(soak_evidence)
    complete_gpu_proof = bool(
        soak_evidence.get("cycles_backend_selected")
        and soak_evidence.get("gpu_process_observed")
        and soak_evidence.get("gpu_compute_observed")
    )
    soak_passed = (
        soak.get("status") == "completed"
        and len(soak.get("frames") or []) == len(soak_frames)
        and len(soak_frames) >= min(50, len(list(range(request.frame_start, request.frame_end + 1, request.frame_step))))
        and soak_safe
        and complete_gpu_proof
    )
    recommended_batch_size = _recommended_batch_size(soak_usage)
    selected_report = compare_reports[selected_backend]
    all_preview_frames = list(selected_report.get("frames") or []) + list(soak.get("frames") or [])
    sizes = [int(item.get("size_bytes") or 0) for item in soak.get("frames") or []]
    report = {
        "status": "completed" if soak_passed else "blocked",
        "operation": "benchmark",
        "source_unchanged": True,
        "source_checksum": selected_report.get("source_checksum", ""),
        "output_directory": str(render_root / "previews"),
        "scene": selected_report.get("scene") or {},
        "cycles_backend_selected": selected_backend,
        "gpu_evidence": soak_evidence,
        "frames": [],
        "benchmark_frames": all_preview_frames,
        "average_frame_seconds": float(soak.get("average_frame_seconds") or 0),
        "average_frame_bytes": round(sum(sizes) / len(sizes)) if sizes else 0,
        "recommended_batch_size": recommended_batch_size,
        "backend_comparison": {
            "selected": selected_backend,
            "visual_similarity": similarity,
            "failures": failures,
            "optix_average_seconds": float(compare_reports.get("OPTIX", {}).get("average_frame_seconds") or 0),
            "cuda_average_seconds": float(compare_reports.get("CUDA", {}).get("average_frame_seconds") or 0),
        },
        "persistent_data_comparison": {
            "selected": persistent_selected,
            "improvement_percent": round(improvement, 2),
            "off_average_seconds": off_seconds,
            "on_average_seconds": on_seconds,
            **persistent_usage,
        },
        "soak": {
            "passed": soak_passed,
            "frame_count": len(soak_frames),
            "frames": soak_frames,
            **soak_usage,
        },
        "warnings": [] if soak_passed else ["The continuous soak did not satisfy the production memory/GPU gate"],
        "artifacts": [
            {
                "kind": "preview",
                "path": item["output_path"],
                "checksum": item["checksum"],
                "size_bytes": item["size_bytes"],
                "metadata": {"frame_number": item["frame_number"], "benchmark": True},
            }
            for item in all_preview_frames
        ],
    }
    for transient in (render_root / "previews" / "persistence",):
        await asyncio.to_thread(shutil.rmtree, transient, True)
    nonselected = "cuda" if selected_backend == "OPTIX" else "optix"
    await asyncio.to_thread(
        shutil.rmtree,
        render_root / "previews" / "backend" / nonselected,
        True,
    )
    return report


async def _run_blender(request: RenderStageRequest, source: Path, render_root: Path, job_dir: Path) -> dict[str, Any]:
    if request.operation == "benchmark":
        return await _run_benchmark(request, source, render_root, job_dir)
    output_directory = render_root / "frames"
    report = await _run_blender_pass(
        request,
        source,
        output_directory,
        job_dir,
        pass_name=request.operation,
        operation=request.operation,
        frames=request.frames,
        backend=request.backend,
        persistent_data=request.persistent_data,
        profile=request.output_profile,
    )
    if request.operation == "preflight":
        report["runtime"] = await asyncio.to_thread(_runtime_health)
        _raise_if_cancelled(request.job_id)
        report["drive"] = await _drive_preflight(
            request.render_job_id, request.require_drive, request.job_id
        )
        if report["drive"].get("status") == "blocked":
            report["status"] = "blocked"
            report.setdefault("warnings", []).append("Google Drive delivery preflight failed")
    return report


def _frame_path(render_root: Path, frame: int, profile: str) -> Path:
    return render_root / "frames" / f"frame_{frame:06d}{'.exr' if profile == 'compositing' else '.png'}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_frames(request: RenderStageRequest) -> list[int]:
    if request.frames:
        return request.frames
    if request.frame_start is None or request.frame_end is None:
        raise ValueError("Frame range is required")
    if request.frame_end < request.frame_start:
        raise ValueError("Frame end cannot be before frame start")
    return list(range(request.frame_start, request.frame_end + 1, request.frame_step))


async def _observe_gui(request: RenderStageRequest, source: Path, render_root: Path, job_dir: Path) -> dict[str, Any]:
    frames = _expected_frames(request)
    manifest_root = _workspace() / ".council-blender"
    manifest_root.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_root / "active_render.json"
    manifest = {
        "job_id": request.render_job_id, "source_path": str(source),
        "output_directory": str(render_root / "frames"), "output_profile": request.output_profile,
        "frame_start": frames[0], "frame_end": frames[-1], "frame_step": request.frame_step,
        "samples": request.samples, "resolution_percent": request.resolution_percent,
        "persistent_data": request.persistent_data, "backend": request.backend,
        "created_at": _utcnow(),
    }
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    temporary.replace(manifest_path)
    cancel = _cancel_events[request.job_id]
    done = asyncio.Event()
    monitor = asyncio.create_task(_monitor(request.job_id, done, None))
    state = _read_state(request.job_id) or {}
    state.update({"status": "running", "stage": "awaiting_kasm_render", "instructions": "Open Blender in Kasm and choose Render > Render Animation"})
    _write_state(request.job_id, state)
    timeout_seconds = int(os.getenv("BLENDER_GUI_RENDER_TIMEOUT_SECONDS", "43200"))
    deadline = asyncio.get_running_loop().time() + max(600, min(timeout_seconds, 86400))
    try:
        while not cancel.is_set() and asyncio.get_running_loop().time() < deadline:
            completed = sum(_frame_path(render_root, frame, request.output_profile).exists() for frame in frames)
            state.update({"completed_frames": completed, "expected_frames": len(frames), "stage": "kasm_render_running" if completed else "awaiting_kasm_render"})
            _write_state(request.job_id, state)
            if completed == len(frames):
                break
            await asyncio.sleep(5)
        else:
            if cancel.is_set():
                raise JobCancelledError("Cancelled by administrator")
            raise RuntimeError("Kasm render did not finish before the safety timeout")
    finally:
        done.set()
        await monitor
        current = _read_json(manifest_path)
        if current.get("job_id") == request.render_job_id:
            manifest_path.unlink(missing_ok=True)
    return await asyncio.to_thread(_validate_frames, request, render_root, False)


def _validate_frames(
    request: RenderStageRequest,
    render_root: Path,
    checksums: bool = True,
    job_id: str | None = None,
) -> dict[str, Any]:
    frames = []
    missing = []
    for number in _expected_frames(request):
        if job_id:
            _raise_if_cancelled(job_id)
        path = _frame_path(render_root, number, request.output_profile)
        if not path.exists() or path.stat().st_size <= 0:
            missing.append(number)
            frames.append({"frame_number": number, "status": "failed", "output_path": str(path), "error": "Frame file is missing or empty"})
        else:
            probe_code, probe_output = _command_output([
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,pix_fmt", "-of", "json", str(path),
            ])
            try:
                stream = (json.loads(probe_output).get("streams") or [{}])[0] if probe_code == 0 else {}
            except (json.JSONDecodeError, AttributeError, IndexError):
                stream = {}
            width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
            dimension_error = bool(
                (request.expected_width and width != request.expected_width)
                or (request.expected_height and height != request.expected_height)
            )
            if probe_code != 0 or not width or not height or dimension_error:
                missing.append(number)
                frames.append({
                    "frame_number": number, "status": "failed", "output_path": str(path),
                    "size_bytes": path.stat().st_size,
                    "error": "Frame image is unreadable or has unexpected dimensions",
                })
                continue
            frames.append({
                "frame_number": number, "status": "completed", "output_path": str(path),
                "checksum": _sha256(path) if checksums else "", "size_bytes": path.stat().st_size,
                "metadata": {"width": width, "height": height, "pixel_format": str(stream.get("pix_fmt") or "")},
            })
    return {
        "status": "blocked" if missing else "completed", "frames": frames,
        "missing_frames": missing, "validated_frame_count": len(frames) - len(missing),
        "expected_frame_count": len(frames),
    }


async def _encode(request: RenderStageRequest, source: Path, render_root: Path, job_dir: Path) -> dict[str, Any]:
    _raise_if_cancelled(request.job_id)
    if request.output_profile != "delivery":
        return {"status": "completed", "warnings": ["Compositing profile retains EXR frames; MP4 encoding was skipped"], "artifacts": []}
    frames = _expected_frames(request)
    output = render_root / "delivery" / "final_4k.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    log = job_dir / "operation.log"
    audio = render_root / "delivery" / "audio.wav"
    audio_arguments: list[str] = []
    if request.include_audio:
        with log.open("ab") as log_file:
            mixdown = await asyncio.create_subprocess_exec(
                os.getenv("BLENDER_BINARY", "blender").strip() or "blender",
                "-b", str(source),
                "--python", str(Path(__file__).with_name("blender_mixdown.py").resolve()),
                "--", "--output", str(audio),
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
            )
            _processes[request.job_id] = mixdown
            mixdown_code = await _wait_process_or_cancel(request.job_id, mixdown)
        if mixdown_code != 0 or not audio.exists():
            raise RuntimeError("Blender audio mixdown failed")
        audio_arguments = ["-i", str(audio)]
    encode_frames = render_root / ".encode-frames"
    await asyncio.to_thread(shutil.rmtree, encode_frames, True)
    encode_frames.mkdir(parents=True, exist_ok=True)
    for index, frame in enumerate(frames, start=1):
        _raise_if_cancelled(request.job_id)
        frame_path = _frame_path(render_root, frame, request.output_profile)
        if not frame_path.exists() or frame_path.stat().st_size <= 0:
            raise RuntimeError(f"Frame {frame} is missing before MP4 assembly")
        staged = encode_frames / f"frame_{index:06d}.png"
        try:
            os.link(frame_path, staged)
        except OSError:
            staged.symlink_to(frame_path)
    # A deterministic sequential link set lets FFmpeg encode requested frame
    # steps without assuming that the original Blender frame numbers are dense.
    command = [
        "ffmpeg", "-y", "-framerate", f"{request.fps:g}", "-start_number", "1",
        "-i", str(encode_frames / "frame_%06d.png"), *audio_arguments,
        "-c:v", "libx264",
        "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        *(["-c:a", "aac", "-b:a", "192k", "-shortest"] if request.include_audio else []),
        "-movflags", "+faststart", str(output),
    ]
    with log.open("ab") as log_file:
        process = await asyncio.create_subprocess_exec(*command, stdout=log_file, stderr=asyncio.subprocess.STDOUT)
        _processes[request.job_id] = process
        code = await _wait_process_or_cancel(request.job_id, process)
    _raise_if_cancelled(request.job_id)
    await asyncio.to_thread(shutil.rmtree, encode_frames, True)
    if code != 0 or not output.exists() or output.stat().st_size <= 0:
        raise RuntimeError("FFmpeg did not create the final MP4")
    return {"status": "completed", "artifacts": [{"kind": "video", "path": str(output), "checksum": _sha256(output), "size_bytes": output.stat().st_size}]}


async def _deliver(request: RenderStageRequest, render_root: Path, job_dir: Path) -> dict[str, Any]:
    _raise_if_cancelled(request.job_id)
    destination = f"{_drive_remote().rstrip(':')}:{request.drive_path}/{request.render_job_id}"
    source = render_root / ("delivery" if request.output_profile == "delivery" else "frames")
    log = job_dir / "operation.log"
    command = [
        "rclone", "copy", str(source), destination, "--checksum",
        "--transfers", "2", "--checkers", "4", "--retries", "5",
        "--low-level-retries", "10", "--retries-sleep", "5s",
    ]
    with log.open("ab") as log_file:
        process = await asyncio.create_subprocess_exec(*command, stdout=log_file, stderr=asyncio.subprocess.STDOUT)
        _processes[request.job_id] = process
        code = await _wait_process_or_cancel(request.job_id, process)
    if code != 0:
        tail = "\n".join(_log_tail(request.job_id, 40))
        error_code = _classify_rclone(tail)
        raise RuntimeError(f"{error_code}: Google Drive delivery failed")
    check = await asyncio.create_subprocess_exec(
        "rclone", "check", str(source), destination, "--checksum", "--one-way",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _processes[request.job_id] = check
    check_stdout, check_stderr = await _communicate_or_cancel(request.job_id, check)
    if check.returncode != 0:
        check_message = (check_stderr or check_stdout).decode(errors="replace")[-1000:]
        error_code = _classify_rclone(check_message)
        raise RuntimeError(f"{error_code}: Google Drive checksum verification failed")
    return {"status": "completed", "destination": destination, "verified": True, "verification": "rclone_checksum_check"}


async def _execute_operation(request: RenderStageRequest, source: Path, render_root: Path, job_dir: Path) -> None:
    state = _read_state(request.job_id) or {}
    state.update({"status": "running", "stage": request.operation, "error": ""})
    _write_state(request.job_id, state)
    try:
        if request.operation in {"preflight", "benchmark", "frame_batch", "prepare_flamenco"}:
            report = await _run_blender(request, source, render_root, job_dir)
        elif request.operation == "observe_gui":
            report = await _observe_gui(request, source, render_root, job_dir)
            report["gpu_evidence"] = _gpu_evidence(report, _telemetry_tail(request.job_id, 1000))
        elif request.operation == "validate":
            report = await asyncio.to_thread(
                _validate_frames, request, render_root, True, request.job_id
            )
        elif request.operation == "encode":
            report = await _encode(request, source, render_root, job_dir)
        else:
            report = await _deliver(request, render_root, job_dir)
        _raise_if_cancelled(request.job_id)
        state.update({"status": "completed", "stage": request.operation, "report": report, "error": ""})
    except JobCancelledError:
        state.update(
            {
                "status": "cancelled",
                "stage": "cancelled",
                "error": "Cancelled by administrator",
            }
        )
    except Exception as exc:
        event = _cancel_events.get(request.job_id)
        if event is not None and event.is_set():
            state.update(
                {
                    "status": "cancelled",
                    "stage": "cancelled",
                    "error": "Cancelled by administrator",
                }
            )
        else:
            state.update({"status": "failed", "stage": request.operation, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        _processes.pop(request.job_id, None)
        latest = _read_state(request.job_id) or {}
        event = _cancel_events.get(request.job_id)
        if latest.get("status") == "cancelled" or (event is not None and event.is_set()):
            latest.update(
                {
                    "status": "cancelled",
                    "stage": "cancelled",
                    "error": "Cancelled by administrator",
                }
            )
        else:
            latest.update(state)
        _write_state(request.job_id, latest)
        _cancel_events.pop(request.job_id, None)


async def _execute(request: RenderStageRequest, source: Path, render_root: Path, job_dir: Path) -> None:
    """Serialize GPU work so one pod can never launch competing Blender jobs."""
    async with _operation_lock:
        cancel = _cancel_events.get(request.job_id)
        if cancel is not None and cancel.is_set():
            state = _read_state(request.job_id) or {}
            state.update({"status": "cancelled", "stage": "cancelled", "error": "Cancelled before execution"})
            _cancel_events.pop(request.job_id, None)
            _write_state(request.job_id, state)
            return
        await _execute_operation(request, source, render_root, job_dir)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if len(os.getenv("BLENDER_AGENT_TOKEN", "").strip()) < 32:
        raise RuntimeError("BLENDER_AGENT_TOKEN must contain at least 32 characters")
    _workspace().mkdir(parents=True, exist_ok=True)
    for state_file in _job_root().glob("*/job.json"):
        state = _read_state(state_file.parent.name)
        if state and state.get("status") == "running":
            state.update({"status": "interrupted", "error": "Pod agent restarted while the operation was running"})
            _write_state(state_file.parent.name, state)
    yield
    for event in _cancel_events.values():
        event.set()
    for process in tuple(_processes.values()):
        process.terminate()
    if _processes:
        await asyncio.gather(*(process.wait() for process in _processes.values()), return_exceptions=True)


app = FastAPI(title="Council OS Blender Production Agent", lifespan=lifespan)


@app.get("/healthz", dependencies=[Depends(_authorize)])
async def health() -> dict[str, Any]:
    return _runtime_health()


@app.get("/v1/runtime", dependencies=[Depends(_authorize)])
async def runtime() -> dict[str, Any]:
    """Return instantaneous pod-local GPU evidence without exposing commands."""
    return await asyncio.to_thread(_runtime_snapshot)


@app.get("/v1/desktop/status", dependencies=[Depends(_authorize)])
async def desktop_status() -> dict[str, Any]:
    """Report process and framebuffer evidence for the fixed Kasm display."""
    return await asyncio.to_thread(desktop_control.status)


@app.post("/v1/desktop/recover", dependencies=[Depends(_authorize)])
async def recover_desktop() -> dict[str, Any]:
    """Restart only allowlisted XFCE components; never accepts commands."""
    return await asyncio.to_thread(desktop_control.recover)


def _flamenco_error(exc: Exception) -> HTTPException:
    status = 422 if isinstance(exc, ValueError) else 503
    return HTTPException(status_code=status, detail=str(exc)[:500])


@app.get("/v1/flamenco/status", dependencies=[Depends(_authorize)])
async def flamenco_status() -> dict[str, Any]:
    """Report real Manager/Worker state without exposing Flamenco directly."""
    return await flamenco_control.status()


@app.post("/v1/flamenco/processes/start", dependencies=[Depends(_authorize)])
async def start_flamenco_process(
    request: flamenco_control.FlamencoStartRequest,
) -> dict[str, Any]:
    try:
        if request.role == "coordinator":
            manager = await asyncio.to_thread(flamenco_control.start_manager)
            worker = await asyncio.to_thread(flamenco_control.start_worker)
            return {"manager": manager, "worker": worker, "status": await flamenco_control.status()}
        worker = await asyncio.to_thread(flamenco_control.start_worker)
        return {"worker": worker, "status": await flamenco_control.status()}
    except (RuntimeError, ValueError, OSError) as exc:
        raise _flamenco_error(exc) from exc


@app.post("/v1/flamenco/processes/{role}/stop", dependencies=[Depends(_authorize)])
async def stop_flamenco_process(role: str) -> dict[str, Any]:
    if role not in {"manager", "worker"}:
        raise HTTPException(status_code=422, detail="Unsupported Flamenco process role")
    try:
        result = await asyncio.to_thread(flamenco_control.stop_role, role)
        return {"process": result, "status": await flamenco_control.status()}
    except (RuntimeError, ValueError, OSError) as exc:
        raise _flamenco_error(exc) from exc


@app.get("/v1/flamenco/logs/{role}", dependencies=[Depends(_authorize)])
async def get_flamenco_logs(role: str) -> dict[str, Any]:
    if role not in {"manager", "worker"}:
        raise HTTPException(status_code=422, detail="Unsupported Flamenco process role")
    return {"role": role, "lines": await asyncio.to_thread(flamenco_control.log_tail, role)}


@app.post("/v1/flamenco/jobs", dependencies=[Depends(_authorize)])
async def create_flamenco_job(
    request: flamenco_control.FlamencoJobRequest,
) -> dict[str, Any]:
    try:
        return await flamenco_control.submit_job(request)
    except (RuntimeError, ValueError, OSError) as exc:
        raise _flamenco_error(exc) from exc


@app.get("/v1/flamenco/jobs/{job_id}", dependencies=[Depends(_authorize)])
async def get_flamenco_job(job_id: str) -> dict[str, Any]:
    try:
        return await flamenco_control.get_job(job_id)
    except (RuntimeError, ValueError, OSError) as exc:
        raise _flamenco_error(exc) from exc


@app.post("/v1/flamenco/jobs/{job_id}/actions", dependencies=[Depends(_authorize)])
async def act_on_flamenco_job(
    job_id: str,
    request: flamenco_control.FlamencoJobAction,
) -> dict[str, Any]:
    try:
        return await flamenco_control.act_on_job(job_id, request)
    except (RuntimeError, ValueError, OSError) as exc:
        raise _flamenco_error(exc) from exc


def _worker_proxy_allowed(path: str) -> bool:
    normalized = f"/{path.lstrip('/')}"
    return normalized == "/api/v3/version" or normalized.startswith("/api/v3/worker/")


@app.api_route(
    "/v1/flamenco/worker-proxy/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    dependencies=[Depends(_authorize_worker_proxy)],
)
async def flamenco_worker_proxy(path: str, request: Request) -> Response:
    """Forward only Flamenco Worker protocol calls to the local Manager."""
    target_path = f"/{path.lstrip('/')}"
    if not _worker_proxy_allowed(target_path) or ".." in target_path:
        raise HTTPException(status_code=403, detail="Only the Flamenco Worker protocol is allowed")
    body = await request.body()
    headers: dict[str, str] = {}
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=120)) as client:
            upstream = await client.request(
                request.method,
                f"http://127.0.0.1:8080{target_path}",
                params=request.query_params,
                headers=headers,
                content=body,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Flamenco Manager is unavailable") from exc
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )


@app.post("/v1/jobs", dependencies=[Depends(_authorize)])
async def create_job(request: RenderStageRequest) -> dict[str, Any]:
    fingerprint = hashlib.sha256(
        json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    existing = _read_state(request.job_id)
    if existing is not None:
        if existing.get("request_fingerprint") != fingerprint:
            raise HTTPException(
                status_code=409,
                detail="Blender job identifier was already used for a different request",
            )
        if existing.get("status") in {"queued", "running", "completed"}:
            return _public_state(request.job_id)
    try:
        source = _within_workspace(request.source_path, must_exist=True)
        render_root = _render_root(request.render_job_id)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not source.is_file():
        raise HTTPException(status_code=422, detail="Source must be an existing .blend file")
    job_dir = _state_path(request.job_id).parent
    state = {
        "job_id": request.job_id, "render_job_id": request.render_job_id,
        "status": "queued", "stage": request.operation,
        "source_path": str(source), "operation": request.operation, "error": "",
        "request_fingerprint": fingerprint,
        "agent_attempt": int((existing or {}).get("agent_attempt") or 0) + 1,
    }
    _write_state(request.job_id, state)
    _cancel_events[request.job_id] = asyncio.Event()
    task = asyncio.create_task(_execute(request, source, render_root, job_dir))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return _public_state(request.job_id)


@app.get("/v1/jobs/{job_id}", dependencies=[Depends(_authorize)])
async def get_job(job_id: str) -> dict[str, Any]:
    if not JOB_ID.fullmatch(job_id):
        raise HTTPException(status_code=422, detail="Invalid job identifier")
    return _public_state(job_id)


@app.post("/v1/jobs/{job_id}/cancel", dependencies=[Depends(_authorize)])
async def cancel_job(job_id: str) -> dict[str, Any]:
    if not JOB_ID.fullmatch(job_id):
        raise HTTPException(status_code=422, detail="Invalid job identifier")
    state = _read_state(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Blender job not found")
    if state.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
        return _public_state(job_id)
    event = _cancel_events.get(job_id)
    if event:
        event.set()
    process = _processes.get(job_id)
    if process and process.returncode is None:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=20)
        except TimeoutError:
            process.kill()
            await process.wait()
    state.update({"status": "cancelled", "stage": "cancelled", "error": "Cancelled by administrator"})
    _write_state(job_id, state)
    return _public_state(job_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("BLENDER_AGENT_PORT", "8001")))
