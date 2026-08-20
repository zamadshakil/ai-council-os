#!/usr/bin/env bash
set -euo pipefail

blender_bin=/opt/blender/blender
for argument in "$@"; do
    if [[ "$argument" == "-b" || "$argument" == "--background" ]]; then
        exec "$blender_bin" "$@"
    fi
done

# KasmVNC's virtual X display is software-rendered with NVIDIA's closed driver.
# Use VirtualGL's EGL backend for the interactive Blender window when the base
# image and the passed-through NVIDIA device prove that it works. Headless
# renders above intentionally bypass VirtualGL and use CUDA/OptiX directly.
virtualgl=/opt/VirtualGL/bin/vglrun
if [[ -x "$virtualgl" ]] && command -v glxinfo >/dev/null 2>&1; then
    for vgl_display in egl0 egl; do
        if "$virtualgl" -d "$vgl_display" glxinfo -B 2>/dev/null \
            | grep -Eqi 'OpenGL renderer string:.*NVIDIA'; then
            exec "$virtualgl" -d "$vgl_display" "$blender_bin" \
                --python /opt/council/blender_gui_bootstrap.py "$@"
        fi
    done
fi

exec "$blender_bin" --python /opt/council/blender_gui_bootstrap.py "$@"
