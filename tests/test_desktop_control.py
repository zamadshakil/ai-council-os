import hashlib
import os

import pytest
from PIL import Image, ImageDraw

from src.scripts import desktop_control


@pytest.fixture(autouse=True)
def _ready_launchers(monkeypatch):
    monkeypatch.setattr(
        desktop_control,
        "_launcher_status",
        lambda: {"ready": True, "directory": "/home/kasm-user/Desktop", "items": {}},
    )


def test_black_frame_is_rejected() -> None:
    evidence = desktop_control.analyse_frame(Image.new("RGB", (320, 180), "black"))

    assert evidence["nonblack"] is False
    assert evidence["mean_luminance"] == 0
    assert evidence["nonblack_ratio"] == 0


def test_visible_desktop_frame_is_accepted() -> None:
    image = Image.new("RGB", (320, 180), "#24142f")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 320, 28), fill="#20252d")
    draw.rectangle((18, 55, 92, 132), fill="#e97824")

    evidence = desktop_control.analyse_frame(image)

    assert evidence["nonblack"] is True
    assert evidence["mean_luminance"] > 2
    assert evidence["luminance_variance"] > 2


def test_status_requires_xfce_components_and_visible_pixels(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(desktop_control, "STATE_PATH", tmp_path / "desktop.json")
    monkeypatch.setattr(desktop_control, "_command", lambda *args, **kwargs: (0, ""))
    monkeypatch.setattr(
        desktop_control,
        "_processes",
        lambda: {
            name: [index + 10]
            for index, name in enumerate(desktop_control.REQUIRED_COMPONENTS)
        },
    )
    monkeypatch.setattr(
        desktop_control,
        "_framebuffer",
        lambda: {"captured": True, "nonblack": True, "mean_luminance": 20.0},
    )

    value = desktop_control.status()

    assert value["ready"] is True
    assert value["missing_components"] == []
    assert (tmp_path / "desktop.json").is_file()


def test_status_rejects_http_only_black_session(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(desktop_control, "STATE_PATH", tmp_path / "desktop.json")
    monkeypatch.setattr(desktop_control, "_command", lambda *args, **kwargs: (0, ""))
    monkeypatch.setattr(
        desktop_control,
        "_processes",
        lambda: {
            name: [index + 10]
            for index, name in enumerate(desktop_control.REQUIRED_COMPONENTS)
        },
    )
    monkeypatch.setattr(
        desktop_control,
        "_framebuffer",
        lambda: {"captured": True, "nonblack": False, "mean_luminance": 0.0},
    )

    value = desktop_control.status()

    assert value["ready"] is False
    assert value["x11_ready"] is True
    assert value["missing_components"] == []


def test_status_rejects_failed_panel_dialog(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(desktop_control, "STATE_PATH", tmp_path / "desktop.json")
    monkeypatch.setattr(desktop_control, "_command", lambda *args, **kwargs: (0, ""))
    monkeypatch.setattr(
        desktop_control,
        "_processes",
        lambda: {
            name: [index + 10]
            for index, name in enumerate(desktop_control.REQUIRED_COMPONENTS)
        },
    )
    monkeypatch.setattr(
        desktop_control,
        "_framebuffer",
        lambda: {"captured": True, "nonblack": True, "mean_luminance": 20.0},
    )
    monkeypatch.setattr(
        desktop_control,
        "_fatal_windows",
        lambda: ["failed to restart the panel"],
    )

    value = desktop_control.status()

    assert value["ready"] is False
    assert value["fatal_windows"] == ["failed to restart the panel"]


def test_recovery_starts_missing_panel_without_dbus_restart(monkeypatch) -> None:
    before = {
        "ready": False,
        "x11_ready": True,
        "missing_components": ["xfce4-panel"],
        "fatal_windows": ["failed to restart the panel"],
        "framebuffer": {"nonblack": True},
    }
    after = {
        "ready": True,
        "x11_ready": True,
        "missing_components": [],
        "fatal_windows": [],
        "framebuffer": {"nonblack": True},
    }
    statuses = iter((before, after))
    spawned: list[list[str]] = []
    monkeypatch.setattr(desktop_control, "status", lambda: next(statuses))
    monkeypatch.setattr(
        desktop_control, "_spawn", lambda command: spawned.append(command)
    )
    monkeypatch.setattr(
        desktop_control, "_terminate_failed_panel_helpers", lambda: [42]
    )
    monkeypatch.setattr(
        desktop_control,
        "ensure_desktop_launchers",
        lambda: {"updated": [], "missing": []},
    )
    monkeypatch.setattr(desktop_control.time, "sleep", lambda _seconds: None)

    result = desktop_control.recover()

    assert result["recovered"] is True
    assert spawned == [["xfce4-panel"]]
    assert "close_failed_panel_restart_dialog" in result["actions"]
    assert all("--restart" not in command for command in spawned)


def test_desktop_launchers_are_made_executable_and_trusted(
    monkeypatch, tmp_path
) -> None:
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    for name in desktop_control.DESKTOP_LAUNCHERS:
        launcher = desktop / name
        launcher.write_text("[Desktop Entry]\nType=Application\n", encoding="utf-8")
        launcher.chmod(0o644)
    commands: list[list[str]] = []
    monkeypatch.setattr(desktop_control, "_desktop_directories", lambda: [desktop])
    monkeypatch.setattr(
        desktop_control,
        "_command",
        lambda command, **_kwargs: (commands.append(command) or 0, ""),
    )

    result = desktop_control.ensure_desktop_launchers()

    assert result["missing"] == []
    assert len(result["updated"]) == len(desktop_control.DESKTOP_LAUNCHERS)
    if os.name != "nt":
        for name in desktop_control.DESKTOP_LAUNCHERS:
            assert (desktop / name).stat().st_mode & 0o111
    expected_commands: list[list[str]] = []
    for name in desktop_control.DESKTOP_LAUNCHERS:
        launcher = desktop / name
        checksum = hashlib.sha256(launcher.read_bytes()).hexdigest()
        expected_commands.extend(
            [
                [
                    "gio",
                    "set",
                    str(launcher),
                    "metadata::xfce-exe-checksum",
                    checksum,
                ],
                [
                    "gio",
                    "set",
                    "-t",
                    "string",
                    str(launcher),
                    "metadata::trusted",
                    "yes",
                ],
            ]
        )
    assert commands == expected_commands


@pytest.mark.parametrize(
    ("matching_checksum", "expected"),
    [
        (True, True),
        (False, False),
    ],
)
def test_launcher_trust_is_verified(
    monkeypatch, tmp_path, matching_checksum, expected
) -> None:
    launcher = tmp_path / "Blender.desktop"
    launcher.write_text("[Desktop Entry]\nType=Application\n", encoding="utf-8")
    launcher.chmod(0o755)
    checksum = hashlib.sha256(launcher.read_bytes()).hexdigest()
    reported = checksum if matching_checksum else "0" * 64
    monkeypatch.setattr(
        desktop_control,
        "_command",
        lambda command, **_kwargs: (
            0,
            f"attributes:\n  metadata::xfce-exe-checksum: {reported}",
        ),
    )

    assert desktop_control._launcher_trusted(launcher) is expected


def test_common_launcher_error_windows_are_fatal(monkeypatch) -> None:
    monkeypatch.setattr(
        desktop_control,
        "_command",
        lambda *args, **kwargs: (
            0,
            '0x01 "Launch Error"\n0x02 "Attention"\n0x03 "Normal Window"',
        ),
    )

    assert desktop_control._fatal_windows() == ["attention", "launch error"]
