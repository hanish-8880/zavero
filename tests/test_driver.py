from PIL import Image

from zavero.driver import Shot, map_key, resize_for_model, to_screen


def test_resize_1920_to_1280():
    img, scale = resize_for_model(Image.new("RGB", (1920, 1080)))
    assert img.size == (1280, 720)
    assert scale == 1.5


def test_no_upscale():
    img, scale = resize_for_model(Image.new("RGB", (1024, 768)))
    assert img.size == (1024, 768)
    assert scale == 1.0


def test_to_screen_scales_back():
    shot = Shot("", 1280, 720, 1.5)
    assert to_screen(640, 360, shot) == (960, 540)
    assert to_screen(0, 0, shot) == (0, 0)


def test_to_screen_monitor_offset():
    shot = Shot("", 1280, 720, 2.0, left=-2560, top=0)
    assert to_screen(100, 50, shot) == (-2360, 100)


def test_map_key():
    assert map_key("CTRL") == "ctrl"
    assert map_key("Return") == "enter"
    assert map_key("ArrowUp") == "up"
    assert map_key("a") == "a"
