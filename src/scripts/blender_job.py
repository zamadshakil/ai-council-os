"""Trusted Blender-side validation, GPU repair, save-copy, and benchmark script."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def _arguments() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--preview", required=True)
    parser.add_argument("--frame", type=int, default=1)
    parser.add_argument("--samples", type=int, default=64)
    parser.add_argument("--resolution-percent", type=int, default=25)
    return parser.parse_args(values)


def _missing_assets(bpy: Any) -> list[str]:
    values: set[str] = set()
    candidates: list[str] = []
    candidates.extend(str(item.filepath) for item in bpy.data.images if item.source == "FILE")
    candidates.extend(str(item.filepath) for item in bpy.data.movieclips)
    candidates.extend(str(item.filepath) for item in bpy.data.sounds)
    candidates.extend(str(item.filepath) for item in bpy.data.fonts if getattr(item, "filepath", ""))
    candidates.extend(str(item.filepath) for item in bpy.data.libraries)
    for raw in candidates:
        if raw and not Path(bpy.path.abspath(raw)).exists():
            values.add(raw)
    return sorted(values)


def _enable_gpu(bpy: Any) -> dict[str, Any]:
    addon = bpy.context.preferences.addons.get("cycles")
    if addon is None:
        raise RuntimeError("Cycles add-on is unavailable")
    preferences = addon.preferences
    chosen_backend = ""
    backend_errors: dict[str, str] = {}
    for backend in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
        try:
            preferences.compute_device_type = backend
            preferences.get_devices()
            chosen_backend = backend
            break
        except Exception as exc:
            backend_errors[backend] = type(exc).__name__
    devices: list[dict[str, Any]] = []
    enabled_gpu_count = 0
    for device in getattr(preferences, "devices", []):
        is_gpu = str(getattr(device, "type", "CPU")).upper() != "CPU"
        device.use = is_gpu
        if is_gpu:
            enabled_gpu_count += 1
        devices.append({
            "name": str(getattr(device, "name", "unknown")),
            "type": str(getattr(device, "type", "unknown")),
            "enabled": bool(device.use),
        })
    if not chosen_backend or enabled_gpu_count == 0:
        raise RuntimeError("No supported GPU device was available to Blender Cycles")
    return {
        "backend": chosen_backend,
        "enabled_gpu_count": enabled_gpu_count,
        "devices": devices,
        "backend_errors": backend_errors,
    }


def main() -> int:
    args = _arguments()
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"status": "failed", "source_unchanged": True}
    started = time.perf_counter()
    try:
        import bpy  # Available only inside Blender.

        source = Path(args.source).resolve()
        output = Path(args.output).resolve()
        preview = Path(args.preview).resolve()
        if source == output:
            raise RuntimeError("Output path would overwrite the source template")
        scene = bpy.context.scene
        scene.render.engine = "CYCLES"
        scene.cycles.device = "GPU"
        scene.cycles.samples = args.samples
        scene.render.use_persistent_data = True
        scene.render.resolution_percentage = args.resolution_percent
        frame = min(max(args.frame, scene.frame_start), scene.frame_end)
        gpu = _enable_gpu(bpy)
        missing_assets = _missing_assets(bpy)

        output.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(output), copy=True, check_existing=False)
        scene.frame_set(frame)
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = str(preview)
        render_started = time.perf_counter()
        bpy.ops.render.render(write_still=True)
        render_seconds = time.perf_counter() - render_started

        report.update({
            "status": "completed",
            "gpu_engaged": True,
            "gpu": gpu,
            "render_engine": scene.render.engine,
            "samples": scene.cycles.samples,
            "resolution_percent": scene.render.resolution_percentage,
            "benchmark_frame": frame,
            "benchmark_seconds": round(render_seconds, 3),
            "missing_assets": missing_assets,
            "warnings": ([f"{len(missing_assets)} external assets are missing"] if missing_assets else []),
            "output_bytes": output.stat().st_size,
            "preview_bytes": preview.stat().st_size if preview.exists() else 0,
            "total_seconds": round(time.perf_counter() - started, 3),
        })
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 0
    except Exception as exc:
        report.update({"error": f"{type(exc).__name__}: {exc}", "total_seconds": round(time.perf_counter() - started, 3)})
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
