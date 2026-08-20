"""Trusted Blender-side preflight and render operations.

This file runs only inside Blender. It accepts structured, allowlisted values
from the authenticated pod agent and never saves over the artist's source file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any


def _arguments() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--operation", choices=("preflight", "benchmark", "frame_batch"), required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--frames", default="")
    parser.add_argument("--samples", type=int, default=0)
    parser.add_argument("--resolution-percent", type=int, default=100)
    parser.add_argument("--profile", choices=("delivery", "compositing"), default="delivery")
    parser.add_argument("--persistent-data", choices=("on", "off"), default="off")
    parser.add_argument("--backend", choices=("AUTO", "OPTIX", "CUDA"), default="AUTO")
    return parser.parse_args(values)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _missing_assets(bpy: Any) -> list[dict[str, str]]:
    values: dict[str, dict[str, str]] = {}
    candidates: list[tuple[str, str]] = []
    try:
        candidates.extend(
            (str(path), "external_resource")
            for path in bpy.utils.blend_paths(absolute=False, packed=False, local=False)
        )
    except (AttributeError, TypeError):
        pass
    for item in bpy.data.images:
        if item.source == "FILE" and not getattr(item, "packed_file", None):
            candidates.append((str(item.filepath), "image"))
    candidates.extend((str(item.filepath), "movieclip") for item in bpy.data.movieclips)
    candidates.extend((str(item.filepath), "sound") for item in bpy.data.sounds)
    candidates.extend(
        (str(item.filepath), "font") for item in bpy.data.fonts if getattr(item, "filepath", "")
    )
    candidates.extend((str(item.filepath), "library") for item in bpy.data.libraries)
    for raw, kind in candidates:
        if not raw:
            continue
        resolved = Path(bpy.path.abspath(raw))
        if not resolved.exists():
            values[f"{kind}:{raw}"] = {
                "kind": kind,
                "stored_path": raw,
                "resolved_path": str(resolved),
            }
    return [values[key] for key in sorted(values)]


def _cycles_devices(bpy: Any, *, enable: bool, preferred: str = "AUTO") -> dict[str, Any]:
    addon = bpy.context.preferences.addons.get("cycles")
    if addon is None:
        raise RuntimeError("Cycles add-on is unavailable")
    preferences = addon.preferences
    errors: dict[str, str] = {}
    chosen = ""
    devices: list[dict[str, Any]] = []
    backends = (preferred,) if preferred in {"OPTIX", "CUDA"} else ("OPTIX", "CUDA")
    for backend in backends:
        try:
            preferences.compute_device_type = backend
            refresh = getattr(preferences, "refresh_devices", None)
            if callable(refresh):
                refresh()
            else:
                preferences.get_devices()
            backend_devices = []
            for device in getattr(preferences, "devices", []):
                device_type = str(getattr(device, "type", "CPU")).upper()
                is_gpu = device_type != "CPU"
                if enable:
                    device.use = is_gpu
                backend_devices.append({
                    "name": str(getattr(device, "name", "unknown")),
                    "type": device_type,
                    "enabled": bool(getattr(device, "use", False)),
                })
            if any(item["type"] != "CPU" for item in backend_devices):
                chosen, devices = backend, backend_devices
                break
            errors[backend] = "No GPU devices returned"
        except Exception as exc:
            errors[backend] = f"{type(exc).__name__}: {exc}"
    return {
        "backend": chosen,
        "devices": devices,
        "enabled_gpu_count": sum(item["enabled"] and item["type"] != "CPU" for item in devices),
        "backend_errors": errors,
    }


def _audio_summary(scene: Any) -> dict[str, Any]:
    editor = getattr(scene, "sequence_editor", None)
    sequences = getattr(editor, "sequences_all", []) if editor else []
    audio = [str(getattr(strip, "name", "audio")) for strip in sequences if getattr(strip, "type", "") == "SOUND"]
    return {"present": bool(audio), "strip_count": len(audio), "strips": audio[:100]}


def _scene_metadata(bpy: Any, source: Path, output_directory: Path) -> dict[str, Any]:
    scene = bpy.context.scene
    render = scene.render
    image = render.image_settings
    display = getattr(scene, "display_settings", None)
    view = getattr(scene, "view_settings", None)
    disk = shutil.disk_usage(output_directory)
    cameras = [str(item.name) for item in bpy.data.cameras]
    libraries = [
        {"name": str(item.name), "path": str(item.filepath)}
        for item in bpy.data.libraries
    ]
    cache_files = [
        {"name": str(item.name), "path": str(getattr(item, "filepath", ""))}
        for item in getattr(bpy.data, "cache_files", [])
    ]
    raw_build_hash = getattr(bpy.app, "build_hash", b"")
    build_hash = (
        raw_build_hash.decode(errors="replace")
        if isinstance(raw_build_hash, bytes)
        else str(raw_build_hash)
    )
    return {
        "source_checksum": _sha256(source),
        "source_size_bytes": source.stat().st_size,
        "output_directory": str(output_directory),
        "blender": {
            "version": str(bpy.app.version_string),
            "build_hash": build_hash,
            "build_timestamp": int(getattr(bpy.app, "build_commit_timestamp", 0)),
        },
        "scene": {
            "name": str(scene.name),
            "frame_start": int(scene.frame_start),
            "frame_end": int(scene.frame_end),
            "frame_step": int(scene.frame_step),
            "fps": float(render.fps / max(0.001, render.fps_base)),
            "resolution_x": int(render.resolution_x),
            "resolution_y": int(render.resolution_y),
            "resolution_percentage": int(render.resolution_percentage),
            "render_engine": str(scene.render.engine),
            "cycles_samples": int(getattr(scene.cycles, "samples", 0)),
            "persistent_data": bool(render.use_persistent_data),
            "file_format": str(image.file_format),
            "color_depth": str(getattr(image, "color_depth", "")),
            "display_device": str(getattr(display, "display_device", "")),
            "view_transform": str(getattr(view, "view_transform", "")),
            "look": str(getattr(view, "look", "")),
            "exposure": float(getattr(view, "exposure", 0.0)),
            "gamma": float(getattr(view, "gamma", 1.0)),
            "camera": str(scene.camera.name) if scene.camera else "",
            "cameras": cameras,
            "compositor_enabled": bool(scene.use_nodes),
            "linked_library_count": len(bpy.data.libraries),
            "linked_libraries": libraries,
            "cache_file_count": len(cache_files),
            "cache_files": cache_files,
            "audio": _audio_summary(scene),
        },
        "storage": {
            "free_bytes": int(disk.free),
            "total_bytes": int(disk.total),
            "safety_free_bytes": int(disk.free * 0.8),
        },
    }


def _parse_frames(raw: str, scene: Any) -> list[int]:
    if not raw.strip():
        return []
    values = sorted({int(part) for part in raw.split(",") if part.strip()})
    invalid = [value for value in values if value < scene.frame_start or value > scene.frame_end]
    if invalid:
        raise ValueError(f"Frames outside the scene range: {invalid[:10]}")
    return values


def _prepare_render(scene: Any, args: argparse.Namespace, output_directory: Path) -> str:
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU"
    if args.samples:
        scene.cycles.samples = args.samples
    scene.render.use_persistent_data = args.persistent_data == "on"
    scene.render.resolution_percentage = args.resolution_percent
    scene.render.use_file_extension = True
    if args.profile == "compositing":
        scene.render.image_settings.file_format = "OPEN_EXR"
        scene.render.image_settings.color_depth = "16"
        scene.render.image_settings.exr_codec = "ZIP"
        extension = ".exr"
    else:
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_depth = "16"
        extension = ".png"
    output_directory.mkdir(parents=True, exist_ok=True)
    return extension


def _render_frames(bpy: Any, args: argparse.Namespace, output_directory: Path) -> list[dict[str, Any]]:
    scene = bpy.context.scene
    frames = _parse_frames(args.frames, scene)
    if not frames:
        raise ValueError("At least one frame is required for a render operation")
    extension = _prepare_render(scene, args, output_directory)
    results: list[dict[str, Any]] = []
    for frame in frames:
        output = output_directory / f"frame_{frame:06d}{extension}"
        if output.exists() and output.stat().st_size > 0:
            results.append({
                "frame_number": frame, "status": "completed", "output_path": str(output),
                "checksum": _sha256(output), "size_bytes": output.stat().st_size,
                "render_seconds": 0.0, "attempts": 0, "reused": True,
            })
            continue
        scene.frame_set(frame)
        scene.render.filepath = str(output.with_suffix(""))
        started = time.perf_counter()
        bpy.ops.render.render(write_still=True)
        elapsed = time.perf_counter() - started
        if not output.exists() or output.stat().st_size <= 0:
            raise RuntimeError(f"Blender did not create frame {frame}")
        results.append({
            "frame_number": frame, "status": "completed", "output_path": str(output),
            "checksum": _sha256(output), "size_bytes": output.stat().st_size,
            "render_seconds": round(elapsed, 3), "attempts": 1,
        })
    return results


def main() -> int:
    args = _arguments()
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "status": "failed", "operation": args.operation,
        "source_unchanged": True, "warnings": [],
    }
    started = time.perf_counter()
    try:
        import bpy

        source = Path(args.source).resolve(strict=True)
        output_directory = Path(args.output_directory).resolve()
        output_directory.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() != ".blend":
            raise ValueError("Source must be a Blender .blend file")
        report.update(_scene_metadata(bpy, source, output_directory))
        missing = _missing_assets(bpy)
        report["missing_assets"] = missing
        gpu = _cycles_devices(
            bpy,
            enable=args.operation != "preflight",
            preferred=args.backend,
        )
        report["gpu"] = gpu
        report["cycles_backend_selected"] = gpu.get("backend", "")
        if not gpu.get("backend"):
            report["warnings"].append("Blender did not discover CUDA or OptiX")
        if missing:
            report["warnings"].append(f"{len(missing)} external assets are unavailable")

        frames: list[dict[str, Any]] = []
        if args.operation in {"benchmark", "frame_batch"}:
            if missing or not gpu.get("backend"):
                report["status"] = "blocked"
            else:
                frames = _render_frames(bpy, args, output_directory)
                report["status"] = "completed"
        else:
            report["status"] = "blocked" if missing or not gpu.get("backend") else "completed"
        report["frames"] = frames
        if frames:
            rendered = [item for item in frames if not item.get("reused")]
            durations = [float(item["render_seconds"]) for item in rendered]
            sizes = [int(item["size_bytes"]) for item in frames]
            report["average_frame_seconds"] = round(sum(durations) / len(durations), 3) if durations else 0.0
            report["average_frame_bytes"] = round(sum(sizes) / len(sizes)) if sizes else 0
            report["artifacts"] = [
                {"kind": "preview" if args.operation == "benchmark" else "frame", "path": item["output_path"], "checksum": item["checksum"], "size_bytes": item["size_bytes"]}
                for item in frames
            ]
        report["total_seconds"] = round(time.perf_counter() - started, 3)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 0
    except Exception as exc:
        report.update({
            "error": f"{type(exc).__name__}: {exc}",
            "total_seconds": round(time.perf_counter() - started, 3),
        })
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
