"""Select a real Cycles GPU whenever a Flamenco task loads a scene.

Flamenco launches Blender with this script before the job's ``.blend`` file.
The persistent load handler reapplies the approved backend after Blender opens
that file. This prevents an otherwise GPU-ready worker from silently rendering
on the CPU because its ephemeral user preferences did not select a device.
"""

from __future__ import annotations

import os

import bpy
from bpy.app.handlers import persistent


def _candidate_backends(scene: object | None) -> tuple[str, ...]:
    requested = ""
    if scene is not None:
        requested = str(scene.get("council_cycles_backend", "")).upper()
    configured = os.getenv("FLAMENCO_CYCLES_BACKEND", "").strip().upper()
    ordered = [requested, configured, "OPTIX", "CUDA"]
    return tuple(dict.fromkeys(item for item in ordered if item in {"OPTIX", "CUDA"}))


def _select_cycles_gpu() -> None:
    scene = getattr(bpy.context, "scene", None)
    preferences = bpy.context.preferences.addons["cycles"].preferences
    selected = ""
    for backend in _candidate_backends(scene):
        try:
            preferences.compute_device_type = backend
            preferences.get_devices()
        except Exception:
            continue
        devices = list(getattr(preferences, "devices", ()))
        accelerated = [device for device in devices if str(device.type).upper() != "CPU"]
        if not accelerated:
            continue
        for device in devices:
            device.use = device in accelerated
        selected = backend
        break
    if not selected:
        raise RuntimeError("Flamenco worker could not select an OptiX or CUDA device")
    for candidate in bpy.data.scenes:
        candidate.render.engine = "CYCLES"
        candidate.cycles.device = "GPU"
        candidate["council_cycles_backend_selected"] = selected


@persistent
def _after_load(_unused: object) -> None:
    _select_cycles_gpu()


if _after_load not in bpy.app.handlers.load_post:
    bpy.app.handlers.load_post.append(_after_load)
_select_cycles_gpu()
