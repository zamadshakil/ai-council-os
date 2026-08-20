#!/usr/bin/env bash
set -euo pipefail

chrome_bin=/opt/google/chrome/google-chrome
chrome_args=(
    --password-store=basic
    --no-sandbox
    --no-first-run
    --disable-search-engine-choice-screen
    --disable-dev-shm-usage
    --ignore-gpu-blocklist
)

rm -f "$HOME"/.config/google-chrome/Singleton* 2>/dev/null || true

# Use the same proven EGL device as Blender when it is available. Chrome still
# starts without it, so a graphics-driver problem cannot make the browser icon
# fail with XFCE's opaque "Input/output error" dialog.
virtualgl=/opt/VirtualGL/bin/vglrun
if [[ -x "$virtualgl" ]] && command -v glxinfo >/dev/null 2>&1; then
    if "$virtualgl" -d egl0 glxinfo -B 2>/dev/null \
        | grep -Eqi 'OpenGL renderer string:.*NVIDIA'; then
        exec "$virtualgl" -d egl0 "$chrome_bin" "${chrome_args[@]}" "$@"
    fi
fi

exec "$chrome_bin" "${chrome_args[@]}" "$@"
