"""Safe pod-local process and API control for Flamenco 3.9.3.

Flamenco's management API has no administrator authentication of its own. The
Manager therefore binds to loopback only and is reachable exclusively through
the authenticated Council OS Blender agent. Remote Workers connect through the
loopback-only gateway in :mod:`flamenco_gateway`.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator


FLAMENCO_VERSION = "3.9.3"
MANAGER_BINARY = Path("/opt/flamenco/flamenco-manager")
WORKER_BINARY = Path("/opt/flamenco/flamenco-worker")
JOB_ID = re.compile(r"^[0-9a-fA-F-]{36}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FlamencoStartRequest(StrictModel):
    role: Literal["coordinator", "worker"]


class FlamencoJobRequest(StrictModel):
    render_job_id: str = Field(min_length=36, max_length=36)
    name: str = Field(min_length=1, max_length=160)
    source_path: str = Field(min_length=7, max_length=1000)
    output_directory: str = Field(min_length=2, max_length=1000)
    frames: str = Field(min_length=1, max_length=50_000)
    chunk_size: int = Field(default=1, ge=1, le=50)
    fps: float = Field(default=24.0, gt=0, le=240)
    image_format: Literal["PNG", "OPEN_EXR", "OPEN_EXR_MULTILAYER"] = "PNG"
    image_extension: Literal[".png", ".exr"] = ".png"
    scene: str = Field(default="Scene", min_length=1, max_length=256)
    priority: int = Field(default=50, ge=0, le=100)

    @field_validator("render_job_id")
    @classmethod
    def valid_render_job_id(cls, value: str) -> str:
        if not JOB_ID.fullmatch(value):
            raise ValueError("Invalid render job identifier")
        return value

    @field_validator("source_path", "output_directory")
    @classmethod
    def safe_workspace_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if not normalized.startswith("/workspace/") or ".." in normalized.split("/"):
            raise ValueError("Flamenco paths must stay inside /workspace")
        return normalized

    @field_validator("source_path")
    @classmethod
    def blend_source(cls, value: str) -> str:
        if not value.lower().endswith(".blend"):
            raise ValueError("Flamenco source must be a .blend file")
        return value

    @field_validator("frames")
    @classmethod
    def safe_frame_expression(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9,\-\s]+", value):
            raise ValueError("Unsupported Flamenco frame expression")
        return value


class FlamencoJobAction(StrictModel):
    action: Literal["pause", "resume", "cancel", "retry"]
    reason: str = Field(default="Council OS administrator action", max_length=500)


def _root() -> Path:
    root = Path(os.getenv("FLAMENCO_HOME", "/workspace/.council-flamenco")).resolve()
    workspace = Path(os.getenv("BLENDER_WORKSPACE_ROOT", "/workspace")).resolve()
    if root != workspace and workspace not in root.parents:
        raise RuntimeError("FLAMENCO_HOME must stay inside the persistent workspace")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _role_dir(role: str) -> Path:
    path = _root() / role
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pid_path(role: str) -> Path:
    return _role_dir(role) / f"{role}.pid"


def _pid(role: str) -> int | None:
    try:
        value = int(_pid_path(role).read_text(encoding="utf-8").strip())
        os.kill(value, 0)
        command = Path(f"/proc/{value}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        expected = "flamenco-manager" if role == "manager" else "flamenco-worker"
        return value if expected in command else None
    except (OSError, ValueError):
        return None


def _write_manager_config() -> Path:
    directory = _role_dir("manager")
    config = directory / "flamenco-manager.yaml"
    database = directory / "flamenco-manager.sqlite"
    storage = directory / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    value = f"""_meta:
  version: 3
manager_name: Council OS Flamenco
database: {database}
database_check_period: 1h
listen: 127.0.0.1:8080
autodiscoverable: false
local_manager_storage_path: {storage}
shared_storage_path: /workspace
shaman:
  enabled: false
  garbageCollect:
    period: 24h
    maxAge: 744h
task_timeout: 10m
worker_timeout: 1m
blocklist_threshold: 3
task_fail_after_softfail_count: 3
variables:
  blender:
    values:
      - platform: linux
        value: /opt/blender/blender
  blenderArgs:
    values:
      - platform: all
        value: -b -y --python /opt/council/flamenco_gpu_bootstrap.py
mqtt:
  client:
    enabled: false
"""
    temporary = config.with_suffix(".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(config)
    return config


def _spawn(role: str, command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> int:
    existing = _pid(role)
    if existing:
        return existing
    log_path = _role_dir(role) / f"{role}.log"
    log_file = log_path.open("ab", buffering=0)
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )
    log_file.close()
    _pid_path(role).write_text(str(process.pid), encoding="utf-8")
    return process.pid


def _wait_for_manager(timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error = "Manager did not respond"
    while time.monotonic() < deadline:
        try:
            response = httpx.get("http://127.0.0.1:8080/api/v3/version", timeout=2)
            if response.is_success:
                value = response.json()
                return value if isinstance(value, dict) else {"version": str(value)}
            last_error = f"Manager returned HTTP {response.status_code}"
        except (httpx.HTTPError, ValueError) as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise RuntimeError(last_error)


def start_manager() -> dict[str, Any]:
    if not MANAGER_BINARY.is_file():
        raise RuntimeError("Pinned Flamenco Manager binary is unavailable")
    directory = _role_dir("manager")
    _write_manager_config()
    pid = _spawn("manager", [str(MANAGER_BINARY), "-quiet"], cwd=directory)
    version = _wait_for_manager()
    return {"role": "coordinator", "pid": pid, "version": version, "ready": True}


def _worker_manager_url() -> str:
    coordinator = os.getenv("FLAMENCO_COORDINATOR_AGENT_URL", "").strip().rstrip("/")
    if coordinator:
        return "http://127.0.0.1:8181"
    start_manager()
    return os.getenv("FLAMENCO_MANAGER_URL", "http://127.0.0.1:8080").strip()


def start_worker() -> dict[str, Any]:
    if not WORKER_BINARY.is_file():
        raise RuntimeError("Pinned Flamenco Worker binary is unavailable")
    manager_url = _worker_manager_url()
    directory = _role_dir("worker")
    home = directory / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({
        "HOME": str(home),
        "PATH": f"/opt/blender:/opt/flamenco:{env.get('PATH', '')}",
    })
    pid = _spawn(
        "worker",
        [str(WORKER_BINARY), "-manager", manager_url, "-quiet"],
        cwd=directory,
        env=env,
    )
    return {"role": "worker", "pid": pid, "manager_url": manager_url, "ready": True}


def stop_role(role: Literal["manager", "worker"]) -> dict[str, Any]:
    pid = _pid(role)
    if pid:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            # A terminated child can remain as a zombie until the pod's init
            # process reaps it.  ``kill(pid, 0)`` still succeeds for zombies,
            # while ``_pid`` deliberately rejects them because their command
            # line is empty.  Poll the validated role PID so shutdown returns
            # promptly instead of waiting the full timeout.
            if _pid(role) != pid:
                break
            time.sleep(0.2)
    _pid_path(role).unlink(missing_ok=True)
    return {"role": role, "running": False}


async def manager_request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> Any:
    if not path.startswith("/api/v3/") or ".." in path:
        raise ValueError("Invalid Flamenco API path")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method,
                f"http://127.0.0.1:8080{path}",
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise RuntimeError("Flamenco Manager is unavailable") from exc
    if response.status_code == 204:
        return {"accepted": True}
    try:
        value = response.json()
    except ValueError as exc:
        raise RuntimeError("Flamenco Manager returned an unreadable response") from exc
    if response.is_error:
        message = value.get("message") if isinstance(value, dict) else ""
        raise RuntimeError(str(message or f"Flamenco Manager returned HTTP {response.status_code}"))
    return value


async def status() -> dict[str, Any]:
    manager_pid = _pid("manager")
    worker_pid = _pid("worker")
    api: dict[str, Any] | None = None
    workers: list[dict[str, Any]] = []
    if manager_pid:
        try:
            api_value = await manager_request("GET", "/api/v3/version", timeout=3)
            api = api_value if isinstance(api_value, dict) else {"value": api_value}
            worker_value = await manager_request("GET", "/api/v3/worker-mgt/workers", timeout=3)
            if isinstance(worker_value, dict) and isinstance(worker_value.get("workers"), list):
                workers = worker_value["workers"]
        except RuntimeError:
            api = None
    return {
        "installed": MANAGER_BINARY.is_file() and WORKER_BINARY.is_file(),
        "expected_version": FLAMENCO_VERSION,
        "manager": {"running": bool(manager_pid), "pid": manager_pid, "api": api},
        "worker": {"running": bool(worker_pid), "pid": worker_pid},
        "registered_workers": workers,
        "shared_storage": "/workspace",
        "manager_exposed": False,
    }


async def submit_job(request: FlamencoJobRequest) -> dict[str, Any]:
    source = Path(request.source_path).resolve(strict=True)
    output = Path(request.output_directory).resolve(strict=False)
    workspace = Path("/workspace").resolve()
    if workspace not in source.parents or workspace not in output.parents:
        raise ValueError("Flamenco paths must stay inside /workspace")
    if not source.is_file():
        raise ValueError("Flamenco source does not exist")
    output.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": request.name,
        "type": "simple-blender-render",
        "priority": request.priority,
        "submitter_platform": "linux",
        "initial_status": "queued",
        "settings": {
            "blender_cmd": "{blender}",
            "blendfile": str(source),
            "render_output_root": str(output),
            "render_output_path": str(output / "frame_######"),
            "add_path_components": 0,
            "frames": request.frames,
            "chunk_size": request.chunk_size,
            # Council OS assembles the final delivery only after its own frame
            # validation, so Flamenco must not create a redundant preview MP4.
            "fps": 0,
            "format": request.image_format,
            "has_previews": False,
            "image_file_extension": request.image_extension,
            "scene": request.scene,
        },
        "metadata": {
            "project": "Council OS",
            "council.render_job_id": request.render_job_id,
            "council.source": str(source),
        },
    }
    existing_value = await manager_request("GET", "/api/v3/jobs")
    existing_jobs = (
        existing_value.get("jobs", [])
        if isinstance(existing_value, dict) and isinstance(existing_value.get("jobs"), list)
        else []
    )
    for existing in existing_jobs:
        metadata = existing.get("metadata") if isinstance(existing, dict) else None
        if isinstance(metadata, dict) and metadata.get("council.render_job_id") == request.render_job_id:
            return existing
    value = await manager_request("POST", "/api/v3/jobs/check", payload=payload)
    if value != {"accepted": True}:
        raise RuntimeError("Flamenco rejected the render job validation")
    result = await manager_request("POST", "/api/v3/jobs", payload=payload)
    if not isinstance(result, dict) or not JOB_ID.fullmatch(str(result.get("id") or "")):
        raise RuntimeError("Flamenco returned an invalid job identifier")
    return result


async def get_job(job_id: str) -> dict[str, Any]:
    if not JOB_ID.fullmatch(job_id):
        raise ValueError("Invalid Flamenco job identifier")
    job = await manager_request("GET", f"/api/v3/jobs/{job_id}")
    tasks = await manager_request("GET", f"/api/v3/jobs/{job_id}/tasks")
    return {"job": job, "tasks": tasks}


async def act_on_job(job_id: str, request: FlamencoJobAction) -> dict[str, Any]:
    if not JOB_ID.fullmatch(job_id):
        raise ValueError("Invalid Flamenco job identifier")
    status_by_action = {
        "pause": "pause-requested",
        "resume": "requeueing",
        "retry": "requeueing",
        "cancel": "cancel-requested",
    }
    await manager_request(
        "POST",
        f"/api/v3/jobs/{job_id}/setstatus",
        payload={"status": status_by_action[request.action], "reason": request.reason},
    )
    return await get_job(job_id)


def log_tail(role: Literal["manager", "worker"], maximum: int = 100) -> list[str]:
    path = _role_dir(role) / f"{role}.log"
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-maximum:]
    except OSError:
        return []


def state_json() -> str:
    """Small diagnostic helper used by image smoke tests."""
    return json.dumps({"manager_pid": _pid("manager"), "worker_pid": _pid("worker")})
