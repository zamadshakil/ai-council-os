"""Kasm Blender bootstrap for the approval-first GUI render workflow.

The artist still starts rendering with Blender's normal Render menu. When an
active Council OS manifest exists, this handler applies only safe in-memory GPU
and image-sequence settings and records GUI progress. The .blend file is never
saved by this module.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import bpy
from bpy.app.handlers import persistent


ROOT = Path("/workspace/.council-blender")
MANIFEST = ROOT / "active_render.json"
STATE = ROOT / "gui_state.json"


def _write_state(**values: Any) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    current: dict[str, Any] = {}
    if STATE.exists():
        try:
            decoded = json.loads(STATE.read_text(encoding="utf-8"))
            current = decoded if isinstance(decoded, dict) else {}
        except (OSError, json.JSONDecodeError):
            current = {}
    current.update(values)
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, indent=2), encoding="utf-8")
    temporary.replace(STATE)


def _manifest() -> dict[str, Any]:
    if not MANIFEST.exists():
        return {}
    try:
        decoded = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _enable_cycles_gpu(
    scene: Any,
    preferred: str = "AUTO",
    *,
    force_cycles_engine: bool = False,
) -> str:
    addon = bpy.context.preferences.addons.get("cycles")
    if addon is None:
        raise RuntimeError("Cycles add-on is unavailable")
    preferences = addon.preferences
    backends = (preferred,) if preferred in {"OPTIX", "CUDA"} else ("OPTIX", "CUDA")
    for backend in backends:
        try:
            preferences.compute_device_type = backend
            refresh = getattr(preferences, "refresh_devices", None)
            refresh() if callable(refresh) else preferences.get_devices()
            enabled = 0
            for device in preferences.devices:
                device.use = str(getattr(device, "type", "CPU")).upper() != "CPU"
                enabled += int(device.use)
            if enabled:
                if force_cycles_engine:
                    scene.render.engine = "CYCLES"
                scene.cycles.device = "GPU"
                return backend
        except Exception:
            continue
    raise RuntimeError("Blender did not discover an OptiX or CUDA device")


def _configure_open_scenes() -> None:
    """Keep manual Cycles scenes on the A6000 after launch and file changes."""
    configured: list[str] = []
    skipped: list[str] = []
    failures: list[str] = []
    selected_backend = ""
    for scene in bpy.data.scenes:
        engine = str(getattr(scene.render, "engine", ""))
        if engine != "CYCLES":
            skipped.append(f"{scene.name}:{engine or 'unknown'}")
            continue
        try:
            selected_backend = _enable_cycles_gpu(scene)
            configured.append(scene.name)
        except Exception as exc:
            failures.append(f"{scene.name}:{type(exc).__name__}")
    _write_state(
        status="gpu_configured" if configured and not failures else "gpu_configuration_warning",
        error="" if not failures else "One or more Cycles scenes could not select an NVIDIA backend",
        mode="manual",
        backend=selected_backend,
        cycles_gpu_configured=bool(configured and not failures),
        configured_scenes=configured,
        skipped_non_cycles_scenes=skipped,
        failed_scenes=failures,
    )


@persistent
def council_load_post(*_: Any) -> None:
    _configure_open_scenes()


@persistent
def council_depsgraph_update(scene: Any, *_: Any) -> None:
    """Catch an artist switching a loaded scene from Eevee to Cycles."""
    if (
        str(getattr(scene.render, "engine", "")) == "CYCLES"
        and str(getattr(scene.cycles, "device", "CPU")) != "GPU"
    ):
        try:
            backend = _enable_cycles_gpu(scene)
            _write_state(
                status="gpu_configured",
                error="",
                mode="manual",
                backend=backend,
                cycles_gpu_configured=True,
                configured_scenes=[scene.name],
            )
        except Exception as exc:
            _write_state(
                status="gpu_configuration_warning",
                error=f"Cycles GPU selection failed: {type(exc).__name__}",
                mode="manual",
                cycles_gpu_configured=False,
            )


@persistent
def council_render_pre(scene: Any, *_: Any) -> None:
    manifest = _manifest()
    if not manifest:
        if str(getattr(scene.render, "engine", "")) == "CYCLES":
            try:
                backend = _enable_cycles_gpu(scene)
                _write_state(
                    status="rendering",
                    error="",
                    mode="manual",
                    backend=backend,
                    cycles_gpu_configured=True,
                    render_engine="CYCLES",
                    current_frame=int(scene.frame_current),
                )
            except Exception as exc:
                _write_state(
                    status="blocked",
                    error=f"Cycles GPU selection failed: {type(exc).__name__}",
                    mode="manual",
                    cycles_gpu_configured=False,
                    render_engine="CYCLES",
                )
                raise
        else:
            _write_state(
                status="rendering",
                error="",
                mode="manual",
                backend="ENGINE_MANAGED",
                cycles_gpu_configured=False,
                render_engine=str(getattr(scene.render, "engine", "")),
                current_frame=int(scene.frame_current),
            )
        return
    source = Path(str(manifest.get("source_path", ""))).resolve()
    current = Path(bpy.data.filepath).resolve() if bpy.data.filepath else Path()
    if current != source:
        message = f"Active Council OS job expects {source}; opened file is {current}"
        _write_state(status="blocked", error=message, job_id=manifest.get("job_id", ""))
        raise RuntimeError(message)
    backend = _enable_cycles_gpu(
        scene,
        str(manifest.get("backend") or "AUTO"),
        force_cycles_engine=True,
    )
    output_directory = Path(str(manifest["output_directory"])).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    profile = str(manifest.get("output_profile", "delivery"))
    if profile == "compositing":
        scene.render.image_settings.file_format = "OPEN_EXR"
        scene.render.image_settings.color_depth = "16"
        scene.render.image_settings.exr_codec = "ZIP"
    else:
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_depth = "16"
    scene.render.use_file_extension = True
    # Blender otherwise defaults animation output to four digits, while the
    # durable frame ledger uses six digits so long sequences sort correctly.
    scene.render.filepath = str(output_directory / "frame_######")
    scene.frame_start = int(manifest["frame_start"])
    scene.frame_end = int(manifest["frame_end"])
    scene.frame_step = int(manifest.get("frame_step", 1))
    scene.render.resolution_percentage = int(manifest.get("resolution_percent", 100))
    if int(manifest.get("samples", 0)):
        scene.cycles.samples = int(manifest["samples"])
    scene.render.use_persistent_data = bool(manifest.get("persistent_data", False))
    _write_state(
        status="rendering", error="", job_id=manifest.get("job_id", ""),
        backend=backend, source_path=str(source), output_directory=str(output_directory),
        mode="managed", cycles_gpu_configured=True, render_engine="CYCLES",
        current_frame=int(scene.frame_current),
    )


@persistent
def council_render_write(scene: Any, *_: Any) -> None:
    manifest = _manifest()
    if manifest:
        _write_state(status="rendering", job_id=manifest.get("job_id", ""), current_frame=int(scene.frame_current))


@persistent
def council_render_post(scene: Any, *_: Any) -> None:
    manifest = _manifest()
    if manifest:
        _write_state(status="frame_completed", job_id=manifest.get("job_id", ""), current_frame=int(scene.frame_current))


@persistent
def council_render_cancel(scene: Any, *_: Any) -> None:
    manifest = _manifest()
    if manifest:
        _write_state(status="cancelled", job_id=manifest.get("job_id", ""), current_frame=int(scene.frame_current))


def register() -> None:
    handlers = (
        (bpy.app.handlers.load_post, council_load_post),
        (bpy.app.handlers.depsgraph_update_post, council_depsgraph_update),
        (bpy.app.handlers.render_pre, council_render_pre),
        (bpy.app.handlers.render_write, council_render_write),
        (bpy.app.handlers.render_post, council_render_post),
        (bpy.app.handlers.render_cancel, council_render_cancel),
    )
    for collection, callback in handlers:
        if callback not in collection:
            collection.append(callback)
    _write_state(status="ready", error="", blender_version=bpy.app.version_string)
    _configure_open_scenes()


def unregister() -> None:
    for collection, callback in (
        (bpy.app.handlers.load_post, council_load_post),
        (bpy.app.handlers.depsgraph_update_post, council_depsgraph_update),
        (bpy.app.handlers.render_pre, council_render_pre),
        (bpy.app.handlers.render_write, council_render_write),
        (bpy.app.handlers.render_post, council_render_post),
        (bpy.app.handlers.render_cancel, council_render_cancel),
    ):
        if callback in collection:
            collection.remove(callback)


register()
