from PIL import Image, ImageDraw

from src.scripts import desktop_control


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


def test_status_requires_xfce_components_and_visible_pixels(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(desktop_control, "STATE_PATH", tmp_path / "desktop.json")
    monkeypatch.setattr(desktop_control, "_command", lambda *args, **kwargs: (0, ""))
    monkeypatch.setattr(
        desktop_control,
        "_processes",
        lambda: {name: [index + 10] for index, name in enumerate(desktop_control.REQUIRED_COMPONENTS)},
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
        lambda: {name: [index + 10] for index, name in enumerate(desktop_control.REQUIRED_COMPONENTS)},
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
