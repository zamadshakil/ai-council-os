"""Durable state helpers for Blender production renders."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from src.core import database as db
from src.core.models import (
    RenderArtifactModel,
    RenderFrameModel,
    RenderJobModel,
    RenderTelemetryModel,
    iso,
    utcnow,
)


TERMINAL_RENDER_STATES = {"completed", "cancelled", "failed"}


def job_resource(job: RenderJobModel) -> dict[str, Any]:
    return {
        "id": job.id,
        "pod_id": job.pod_id,
        "source_path": job.source_path,
        "source_checksum": job.source_checksum,
        "status": job.status,
        "stage": job.stage,
        "render_mode": job.render_mode,
        "output_profile": job.output_profile,
        "output_directory": job.output_directory,
        "frame_start": job.frame_start,
        "frame_end": job.frame_end,
        "frame_step": job.frame_step,
        "expected_frame_count": job.expected_frame_count,
        "completed_frame_count": job.completed_frame_count,
        "failed_frame_count": job.failed_frame_count,
        "settings": job.settings or {},
        "preflight": job.preflight or {},
        "benchmark": job.benchmark or {},
        "delivery": job.delivery or {},
        "error": job.error or "",
        "auto_stop": job.auto_stop,
        "version": job.version,
        "approved_at": iso(job.approved_at),
        "finished_at": iso(job.finished_at),
        "created_at": iso(job.created_at),
        "updated_at": iso(job.updated_at),
    }


def frame_resource(frame: RenderFrameModel) -> dict[str, Any]:
    return {
        "id": frame.id,
        "render_job_id": frame.render_job_id,
        "frame_number": frame.frame_number,
        "status": frame.status,
        "batch_key": frame.batch_key,
        "output_path": frame.output_path,
        "checksum": frame.checksum,
        "size_bytes": frame.size_bytes,
        "render_seconds": frame.render_seconds,
        "attempts": frame.attempts,
        "error": frame.error,
        "version": frame.version,
        "updated_at": iso(frame.updated_at),
    }


def telemetry_resource(sample: RenderTelemetryModel) -> dict[str, Any]:
    return {
        "stage": sample.stage,
        "gpu_index": sample.gpu_index,
        "blender_pid": sample.blender_pid,
        "gpu_utilization": sample.gpu_utilization,
        "vram_used_mb": sample.vram_used_mb,
        "vram_total_mb": sample.vram_total_mb,
        "power_watts": sample.power_watts,
        "host_ram_used_mb": sample.host_ram_used_mb,
        "host_ram_total_mb": sample.host_ram_total_mb,
        "sampled_at": iso(sample.sampled_at),
    }


def artifact_resource(item: RenderArtifactModel) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "path": item.path,
        "checksum": item.checksum,
        "size_bytes": item.size_bytes,
        "status": item.status,
        "metadata": item.metadata_json or {},
        "version": item.version,
        "created_at": iso(item.created_at),
    }


async def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    async with db.async_session() as session:
        rows = (
            await session.execute(
                select(RenderJobModel)
                .order_by(RenderJobModel.created_at.desc())
                .limit(max(1, min(limit, 200)))
            )
        ).scalars().all()
    return [job_resource(row) for row in rows]


async def get_job(job_id: str) -> RenderJobModel | None:
    async with db.async_session() as session:
        return await session.get(RenderJobModel, job_id)


async def list_frames(job_id: str) -> list[dict[str, Any]]:
    async with db.async_session() as session:
        rows = (
            await session.execute(
                select(RenderFrameModel)
                .where(RenderFrameModel.render_job_id == job_id)
                .order_by(RenderFrameModel.frame_number)
            )
        ).scalars().all()
    return [frame_resource(row) for row in rows]


async def list_telemetry(job_id: str, limit: int = 600) -> list[dict[str, Any]]:
    async with db.async_session() as session:
        rows = (
            await session.execute(
                select(RenderTelemetryModel)
                .where(RenderTelemetryModel.render_job_id == job_id)
                .order_by(RenderTelemetryModel.sampled_at.desc())
                .limit(max(1, min(limit, 2_000)))
            )
        ).scalars().all()
    return [telemetry_resource(row) for row in reversed(rows)]


async def list_artifacts(job_id: str) -> list[dict[str, Any]]:
    async with db.async_session() as session:
        rows = (
            await session.execute(
                select(RenderArtifactModel)
                .where(RenderArtifactModel.render_job_id == job_id)
                .order_by(RenderArtifactModel.created_at.desc())
            )
        ).scalars().all()
    return [artifact_resource(row) for row in rows]


async def ensure_frames(job_id: str, start: int, end: int, step: int = 1) -> int:
    numbers = list(range(start, end + 1, max(1, step)))
    async with db.async_session() as session:
        existing = set(
            (
                await session.execute(
                    select(RenderFrameModel.frame_number).where(
                        RenderFrameModel.render_job_id == job_id
                    )
                )
            ).scalars().all()
        )
        session.add_all(
            RenderFrameModel(render_job_id=job_id, frame_number=number)
            for number in numbers
            if number not in existing
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
        job = await session.get(RenderJobModel, job_id, with_for_update=True)
        if job:
            job.frame_start = start
            job.frame_end = end
            job.frame_step = max(1, step)
            job.expected_frame_count = len(numbers)
            job.version += 1
            await session.commit()
    return len(numbers)


async def persist_agent_snapshot(
    job_id: str,
    *,
    stage: str,
    agent_state: dict[str, Any],
) -> RenderJobModel:
    """Persist sanitized agent progress, telemetry, frame, and artifact evidence."""
    async with db.async_session() as session:
        job = await session.get(RenderJobModel, job_id, with_for_update=True)
        if job is None:
            raise LookupError("Render job does not exist")
        report = agent_state.get("report") if isinstance(agent_state.get("report"), dict) else {}
        status = str(agent_state.get("status") or "running")
        job.stage = stage
        job.status = "running" if status in {"queued", "running"} else job.status
        if stage == "render.preflight" and report:
            job.preflight = report
            scene = report.get("scene") if isinstance(report.get("scene"), dict) else {}
            if scene:
                start = int(scene.get("frame_start", job.frame_start or 1))
                end = int(scene.get("frame_end", job.frame_end or start))
                requested_step = (job.settings or {}).get("requested_frame_step")
                step = max(
                    1,
                    int(
                        requested_step
                        if requested_step is not None
                        else scene.get("frame_step", job.frame_step or 1)
                    ),
                )
                job.frame_start, job.frame_end, job.frame_step = start, end, step
                job.expected_frame_count = len(range(start, end + 1, step))
            job.source_checksum = str(report.get("source_checksum") or job.source_checksum)
            job.output_directory = str(report.get("output_directory") or job.output_directory)
        elif stage == "render.benchmark" and report:
            job.benchmark = report
        elif stage == "render.deliver" and report:
            job.delivery = report
        error = str(agent_state.get("error") or report.get("error") or "")
        if error:
            job.error = error[:8000]

        existing_telemetry = set(
            (
                await session.execute(
                    select(
                        RenderTelemetryModel.sampled_at,
                        RenderTelemetryModel.gpu_index,
                    ).where(
                        RenderTelemetryModel.render_job_id == job_id,
                        RenderTelemetryModel.stage == stage,
                    )
                )
            ).all()
        )
        for raw in agent_state.get("telemetry", [])[-600:]:
            if not isinstance(raw, dict):
                continue
            sampled_at: datetime | None = None
            raw_time = raw.get("sampled_at")
            if isinstance(raw_time, str):
                try:
                    sampled_at = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
                except ValueError:
                    sampled_at = None
            gpu_index = int(raw.get("gpu_index") or 0)
            if sampled_at is not None and (sampled_at, gpu_index) in existing_telemetry:
                continue
            session.add(RenderTelemetryModel(
                render_job_id=job_id,
                stage=stage,
                gpu_index=gpu_index,
                blender_pid=int(raw["blender_pid"]) if raw.get("blender_pid") else None,
                gpu_utilization=float(raw.get("gpu_utilization") or 0),
                vram_used_mb=float(raw.get("vram_used_mb") or 0),
                vram_total_mb=float(raw.get("vram_total_mb") or 0),
                power_watts=float(raw.get("power_watts") or 0),
                host_ram_used_mb=float(raw.get("host_ram_used_mb") or 0),
                host_ram_total_mb=float(raw.get("host_ram_total_mb") or 0),
                sampled_at=sampled_at or utcnow(),
            ))
            if sampled_at is not None:
                existing_telemetry.add((sampled_at, gpu_index))

        for raw in report.get("frames", []):
            if not isinstance(raw, dict) or raw.get("frame_number") is None:
                continue
            number = int(raw["frame_number"])
            row = (
                await session.execute(
                    select(RenderFrameModel).where(
                        RenderFrameModel.render_job_id == job_id,
                        RenderFrameModel.frame_number == number,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = RenderFrameModel(render_job_id=job_id, frame_number=number)
                session.add(row)
            row.status = str(raw.get("status") or "completed")
            row.output_path = str(raw.get("output_path") or row.output_path)
            row.checksum = str(raw.get("checksum") or row.checksum)
            row.size_bytes = int(raw.get("size_bytes") or row.size_bytes)
            row.render_seconds = (
                float(raw["render_seconds"]) if raw.get("render_seconds") is not None else row.render_seconds
            )
            row.attempts = max(row.attempts, int(raw.get("attempts") or 1))
            row.error = str(raw.get("error") or "")[:8000]
            row.version += 1

        for raw in report.get("artifacts", []):
            if not isinstance(raw, dict) or not raw.get("path"):
                continue
            kind, path = str(raw.get("kind") or "file"), str(raw["path"])
            item = (
                await session.execute(
                    select(RenderArtifactModel).where(
                        RenderArtifactModel.render_job_id == job_id,
                        RenderArtifactModel.kind == kind,
                        RenderArtifactModel.path == path,
                    )
                )
            ).scalar_one_or_none()
            if item is None:
                item = RenderArtifactModel(render_job_id=job_id, kind=kind, path=path)
                session.add(item)
            item.checksum = str(raw.get("checksum") or item.checksum)
            item.size_bytes = int(raw.get("size_bytes") or item.size_bytes)
            item.status = str(raw.get("status") or "available")
            item.metadata_json = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}

        job.version += 1
        await session.commit()
        await session.refresh(job)
        return job


async def refresh_frame_counts(job_id: str) -> RenderJobModel:
    async with db.async_session() as session:
        job = await session.get(RenderJobModel, job_id, with_for_update=True)
        if job is None:
            raise LookupError("Render job does not exist")
        counts = dict(
            (
                await session.execute(
                    select(RenderFrameModel.status, func.count(RenderFrameModel.id))
                    .where(RenderFrameModel.render_job_id == job_id)
                    .group_by(RenderFrameModel.status)
                )
            ).all()
        )
        job.completed_frame_count = int(counts.get("completed", 0))
        job.failed_frame_count = int(counts.get("failed", 0))
        job.version += 1
        await session.commit()
        await session.refresh(job)
        return job


async def clear_telemetry(job_id: str) -> None:
    async with db.async_session() as session:
        await session.execute(
            delete(RenderTelemetryModel).where(RenderTelemetryModel.render_job_id == job_id)
        )
        await session.commit()


def representative_frames(start: int, end: int, count: int = 7) -> list[int]:
    """Return deterministic, unique frames spanning the complete scene."""
    if end < start:
        raise ValueError("Frame end must not be before frame start")
    count = max(2, min(count, 10))
    if start == end:
        return [start]
    span = end - start
    return sorted({start + round(span * index / (count - 1)) for index in range(count)})


def frame_batches(frames: Iterable[int], size: int) -> list[list[int]]:
    values = sorted(set(int(value) for value in frames))
    size = max(1, min(int(size), 50))
    return [values[index:index + size] for index in range(0, len(values), size)]
