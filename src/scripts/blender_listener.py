"""Authenticated RunPod-side Blender template job agent.

The agent intentionally exposes a small, allowlisted job contract. It never
accepts Python source or shell commands from the dashboard. Jobs operate only
inside ``BLENDER_WORKSPACE_ROOT`` and always write a new ``.blend`` file.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator


JOB_ID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
OUTPUT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.blend$")
_processes: dict[str, asyncio.subprocess.Process] = {}
_tasks: set[asyncio.Task[Any]] = set()


class TemplateJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    job_id: str = Field(min_length=8, max_length=128)
    source_path: str = Field(min_length=7, max_length=500)
    output_name: str = Field(min_length=7, max_length=126)
    frame: int = Field(default=1, ge=0, le=1_000_000)
    samples: int = Field(default=64, ge=1, le=4096)
    resolution_percent: int = Field(default=25, ge=1, le=100)
    operation: Literal["validate_repair_benchmark"] = "validate_repair_benchmark"

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


def _workspace() -> Path:
    return Path(os.getenv("BLENDER_WORKSPACE_ROOT", "/workspace")).resolve()


def _job_root() -> Path:
    value = _workspace() / ".council-blender-jobs"
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


def _read_state(job_id: str) -> dict[str, Any] | None:
    path = _state_path(job_id)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_state(job_id: str, value: dict[str, Any]) -> None:
    path = _state_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def _log_tail(job_id: str, maximum: int = 80) -> list[str]:
    path = _state_path(job_id).parent / "blender.log"
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-maximum:]
    except OSError:
        return []


def _public_state(job_id: str) -> dict[str, Any]:
    state = _read_state(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Blender job not found")
    return {**state, "log_tail": _log_tail(job_id)}


async def _authorize(authorization: str = Header(default="")) -> None:
    expected = os.getenv("BLENDER_AGENT_TOKEN", "").strip()
    supplied = authorization.removeprefix("Bearer ").strip()
    if len(expected) < 32 or not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="Blender agent authentication failed")


async def _execute(request: TemplateJobRequest, source: Path, job_dir: Path) -> None:
    state = _read_state(request.job_id) or {}
    state.update({"status": "running", "stage": "starting_blender", "error": ""})
    _write_state(request.job_id, state)
    report_path = job_dir / "report.json"
    preview_path = job_dir / "benchmark.png"
    output_path = job_dir / request.output_name
    log_path = job_dir / "blender.log"
    blender = os.getenv("BLENDER_BINARY", "blender").strip() or "blender"
    trusted_script = Path(__file__).with_name("blender_job.py").resolve()
    command = [
        blender, "-b", str(source), "--python", str(trusted_script), "--",
        "--source", str(source), "--output", str(output_path),
        "--report", str(report_path), "--preview", str(preview_path),
        "--frame", str(request.frame), "--samples", str(request.samples),
        "--resolution-percent", str(request.resolution_percent),
    ]
    try:
        with log_path.open("wb") as log_file:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(job_dir),
            )
            _processes[request.job_id] = process
            state.update({"stage": "gpu_repair_and_benchmark", "pid": process.pid})
            _write_state(request.job_id, state)
            return_code = await process.wait()
        report: dict[str, Any] = {}
        if report_path.exists():
            try:
                decoded = json.loads(report_path.read_text(encoding="utf-8"))
                report = decoded if isinstance(decoded, dict) else {}
            except (OSError, json.JSONDecodeError):
                report = {}
        if return_code != 0 or not output_path.exists():
            message = str(report.get("error") or f"Blender exited with code {return_code}")
            state.update({"status": "failed", "stage": "failed", "error": message, "report": report})
        else:
            state.update({
                "status": "completed",
                "stage": "completed",
                "error": "",
                "output_path": str(output_path),
                "preview_path": str(preview_path) if preview_path.exists() else "",
                "report": report,
            })
        _write_state(request.job_id, state)
    except FileNotFoundError:
        state.update({"status": "failed", "stage": "failed", "error": "Blender executable was not found on this pod"})
        _write_state(request.job_id, state)
    except Exception as exc:
        state.update({"status": "failed", "stage": "failed", "error": f"Blender job failed: {type(exc).__name__}"})
        _write_state(request.job_id, state)
    finally:
        _processes.pop(request.job_id, None)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if len(os.getenv("BLENDER_AGENT_TOKEN", "").strip()) < 32:
        raise RuntimeError("BLENDER_AGENT_TOKEN must contain at least 32 characters")
    root = _workspace()
    root.mkdir(parents=True, exist_ok=True)
    for state_file in _job_root().glob("*/job.json"):
        state = _read_state(state_file.parent.name)
        if state and state.get("status") == "running":
            state.update({"status": "interrupted", "stage": "interrupted", "error": "Pod agent restarted while Blender was running"})
            _write_state(state_file.parent.name, state)
    yield
    for process in tuple(_processes.values()):
        process.terminate()
    if _processes:
        await asyncio.gather(*(process.wait() for process in _processes.values()), return_exceptions=True)


app = FastAPI(title="Council OS Blender GPU Agent", lifespan=lifespan)


@app.get("/healthz")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "blender_available": shutil.which(os.getenv("BLENDER_BINARY", "blender")) is not None,
        "gpu_visible": bool(os.getenv("NVIDIA_VISIBLE_DEVICES", "")),
    }


@app.post("/v1/jobs", dependencies=[Depends(_authorize)])
async def create_job(request: TemplateJobRequest) -> dict[str, Any]:
    existing = _read_state(request.job_id)
    if existing is not None:
        return _public_state(request.job_id)
    try:
        source = _within_workspace(request.source_path, must_exist=True)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if source.suffix.lower() != ".blend" or not source.is_file():
        raise HTTPException(status_code=422, detail="Source must be an existing .blend file")
    job_dir = _state_path(request.job_id).parent
    output_path = (job_dir / request.output_name).resolve()
    if source == output_path:
        raise HTTPException(status_code=422, detail="Output cannot overwrite the source template")
    state = {
        "job_id": request.job_id,
        "status": "queued",
        "stage": "queued",
        "source_path": str(source),
        "output_name": request.output_name,
        "operation": request.operation,
        "error": "",
    }
    _write_state(request.job_id, state)
    task = asyncio.create_task(_execute(request, source, job_dir))
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
    process = _processes.get(job_id)
    if process and process.returncode is None:
        process.terminate()
        await process.wait()
    state.update({"status": "cancelled", "stage": "cancelled", "error": "Cancelled by administrator"})
    _write_state(job_id, state)
    return _public_state(job_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("BLENDER_AGENT_PORT", "8001")))
