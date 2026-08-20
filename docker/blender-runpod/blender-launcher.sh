#!/usr/bin/env bash
set -euo pipefail

blender_bin=/opt/blender/blender
for argument in "$@"; do
    if [[ "$argument" == "-b" || "$argument" == "--background" ]]; then
        exec "$blender_bin" "$@"
    fi
done

# Modern Kasm/NVIDIA container wiring supplies GLVND directly. The runtime
# preflight rejects llvmpipe, so no wrapper or software fallback is allowed.
exec "$blender_bin" --python /opt/council/blender_gui_bootstrap.py "$@"
