"""Allowlisted Kasm/XFCE health checks and startup recovery.

The module deliberately exposes no command execution surface.  It only
observes the fixed Kasm display and can restart the fixed XFCE components that
make up the artist desktop.
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat


DISPLAY = os.getenv("DISPLAY", ":1").strip() or ":1"
WORKSPACE = Path(os.getenv("BLENDER_WORKSPACE_ROOT", "/workspace")).resolve()
STATE_PATH = WORKSPACE / ".council-blender" / "desktop_status.json"
LOG_PATH = WORKSPACE / "logs" / "desktop-watchdog.log"
REQUIRED_COMPONENTS = ("xfce4-session", "xfwm4", "xfdesktop", "xfce4-panel")
FATAL_WINDOW_TITLES = (
    "failed to restart the panel",
    "untrusted application launcher",
)
DESKTOP_LAUNCHERS = (
    "google-chrome.desktop",
    "Blender.desktop",
    "Renders.desktop",
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _command(command: list[str], *, timeout: int = 12) -> tuple[int, str]:
    environment = os.environ.copy()
    environment["DISPLAY"] = DISPLAY
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=environment,
        )
        return result.returncode, (result.stdout or result.stderr or "").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"{type(exc).__name__}: {exc}"


def _processes() -> dict[str, list[int]]:
    found = {name: [] for name in REQUIRED_COMPONENTS}
    try:
        import psutil

        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            name = str(process.info.get("name") or "")
            command = " ".join(process.info.get("cmdline") or [])
            for expected in REQUIRED_COMPONENTS:
                # `xfce4-panel --restart` is a short-lived D-Bus control
                # command, not the desktop panel. Counting it as healthy can
                # turn its error dialog into a false-ready Kasm session.
                if expected == "xfce4-panel" and "--restart" in command:
                    continue
                if name == expected or re.search(rf"(^|/){re.escape(expected)}(?:\s|$)", command):
                    found[expected].append(int(process.info["pid"]))
    except Exception:
        pass
    return found


def _fatal_windows() -> list[str]:
    """Return allowlisted desktop error dialogs that make a session unusable."""
    code, output = _command(["xwininfo", "-display", DISPLAY, "-root", "-tree"], timeout=8)
    if code != 0:
        return []
    lowered = output.casefold()
    return [title for title in FATAL_WINDOW_TITLES if title in lowered]


def _display_dimensions() -> tuple[int, int] | None:
    code, output = _command(["xdpyinfo", "-display", DISPLAY])
    if code != 0:
        return None
    match = re.search(r"dimensions:\s+(\d+)x(\d+)\s+pixels", output)
    if not match:
        return None
    width, height = int(match.group(1)), int(match.group(2))
    if width < 320 or height < 200 or width > 16384 or height > 16384:
        return None
    return width, height


def analyse_frame(image: Image.Image) -> dict[str, float | bool]:
    """Return bounded evidence that a framebuffer contains visible content."""
    grayscale = image.convert("L").resize((160, 90))
    statistics = ImageStat.Stat(grayscale)
    mean = float(statistics.mean[0])
    variance = float(statistics.var[0])
    histogram = grayscale.histogram()
    pixels = max(1, sum(histogram))
    nonblack_ratio = float(sum(histogram[4:]) / pixels)
    return {
        "mean_luminance": round(mean, 3),
        "luminance_variance": round(variance, 3),
        "nonblack_ratio": round(nonblack_ratio, 5),
        "nonblack": bool(mean >= 2.0 and variance >= 2.0 and nonblack_ratio >= 0.01),
    }


def _framebuffer() -> dict[str, Any]:
    dimensions = _display_dimensions()
    if not dimensions:
        return {"captured": False, "nonblack": False, "error": "X display dimensions unavailable"}
    width, height = dimensions
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "x11grab",
        "-video_size", f"{width}x{height}", "-i", DISPLAY, "-frames:v", "1",
        "-vf", "scale=320:180", "-f", "image2pipe", "-vcodec", "png", "pipe:1",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=15,
            check=False,
            env={**os.environ, "DISPLAY": DISPLAY},
        )
        if result.returncode != 0 or not result.stdout:
            error = result.stderr.decode("utf-8", errors="replace").strip()[-500:]
            return {"captured": False, "nonblack": False, "error": error or "Frame capture failed"}
        with Image.open(io.BytesIO(result.stdout)) as image:
            evidence = analyse_frame(image)
        return {"captured": True, "width": width, "height": height, **evidence}
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"captured": False, "nonblack": False, "error": f"{type(exc).__name__}: {exc}"}


def status() -> dict[str, Any]:
    x_code, x_output = _command(["xset", "-display", DISPLAY, "q"], timeout=5)
    processes = _processes()
    missing = [name for name, pids in processes.items() if not pids]
    fatal_windows = _fatal_windows() if x_code == 0 else []
    framebuffer = _framebuffer() if x_code == 0 else {
        "captured": False,
        "nonblack": False,
        "error": x_output[-500:] or "X display is unavailable",
    }
    ready = (
        x_code == 0
        and not missing
        and not fatal_windows
        and bool(framebuffer.get("nonblack"))
    )
    value = {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "checked_at": _utcnow(),
        "display": DISPLAY,
        "x11_ready": x_code == 0,
        "components": processes,
        "missing_components": missing,
        "fatal_windows": fatal_windows,
        "framebuffer": framebuffer,
    }
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = STATE_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
        temporary.replace(STATE_PATH)
    except OSError:
        pass
    return value


def _spawn(command: list[str]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("ab") as log_file:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ, "DISPLAY": DISPLAY},
        )


def _terminate_failed_panel_helpers() -> list[int]:
    """Close only failed `xfce4-panel --restart` helpers and their dialogs."""
    stopped: list[int] = []
    try:
        import psutil

        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            command = " ".join(process.info.get("cmdline") or [])
            if process.info.get("name") == "xfce4-panel" and "--restart" in command:
                process.terminate()
                stopped.append(int(process.info["pid"]))
    except Exception:
        pass
    return stopped


def _desktop_directories() -> list[Path]:
    candidates = [
        Path.home() / "Desktop",
        Path("/home/kasm-user/Desktop"),
        Path("/home/kasm-default-profile/Desktop"),
    ]
    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def ensure_desktop_launchers() -> dict[str, Any]:
    """Make only the shipped artist launchers executable and XFCE-trusted."""
    updated: list[str] = []
    missing: list[str] = []
    for launcher_name in DESKTOP_LAUNCHERS:
        paths = [directory / launcher_name for directory in _desktop_directories()]
        existing = [path for path in paths if path.is_file()]
        if not existing:
            missing.append(launcher_name)
            continue
        for path in existing:
            try:
                path.chmod(0o755)
                updated.append(str(path))
            except OSError:
                continue
            # XFCE/GLib can require both the executable bit and trusted
            # metadata for launchers copied from a default Kasm profile.
            # Failure is safe here: the executable bit remains enforced and
            # the readiness gate still rejects any resulting trust dialog.
            _command(["gio", "set", str(path), "metadata::trusted", "true"], timeout=5)
    return {"updated": updated, "missing": missing}


def recover() -> dict[str, Any]:
    """Repair only the fixed XFCE desktop components on the fixed Kasm display."""
    before = status()
    if not before["x11_ready"]:
        return {"recovered": False, "reason": "X11_NOT_READY", "before": before, "after": before}

    missing = set(before["missing_components"])
    actions: list[str] = []
    launcher_result = ensure_desktop_launchers()
    if launcher_result["updated"]:
        actions.append("trust_desktop_launchers")
    stopped_helpers = _terminate_failed_panel_helpers()
    if stopped_helpers:
        actions.append("close_failed_panel_restart_dialog")
    if "xfce4-session" in missing:
        _spawn(["xfce4-session"])
        actions.append("start_xfce_session")
        time.sleep(4)
    if "xfwm4" in missing:
        _spawn(["xfwm4", "--replace"])
        actions.append("start_window_manager")
    if "xfdesktop" in missing or not before["framebuffer"].get("nonblack"):
        _spawn(["xfdesktop", "--replace"])
        actions.append("restart_desktop")
    if "xfce4-panel" in missing:
        # `--restart` talks to an already-registered panel over the XFCE
        # session bus. It must never be used when the panel is absent: doing
        # so opens a modal "ServiceUnknown" dialog on the artist desktop.
        _spawn(["xfce4-panel"])
        actions.append("start_panel")

    time.sleep(5)
    after = status()
    return {"recovered": bool(after["ready"]), "actions": actions, "before": before, "after": after}


def watchdog() -> None:
    """Recover startup failures, then keep process-level supervision active."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    consecutive_failures = 0
    startup_deadline = time.monotonic() + 300
    ensure_desktop_launchers()
    while True:
        current = status()
        if current["ready"]:
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            process_failure = bool(current["missing_components"])
            startup_black = time.monotonic() < startup_deadline and not current["framebuffer"].get("nonblack")
            if consecutive_failures >= 3 and (process_failure or startup_black):
                result = recover()
                with LOG_PATH.open("a", encoding="utf-8") as log_file:
                    log_file.write(json.dumps({"at": _utcnow(), "recovery": result}) + "\n")
                consecutive_failures = 0
        time.sleep(10)


if __name__ == "__main__":
    watchdog()
