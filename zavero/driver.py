"""Screen capture, DPI scaling and action execution.

All coordinate conversion lives here. The model sees a screenshot that is
SCREENSHOT_WIDTH px wide; the real screen is usually bigger. `scale` maps
model pixels back to real screen pixels.
"""
import base64
import ctypes
import io
import sys
import time
from dataclasses import dataclass

from PIL import Image

from zavero import config

_dpi_set = False


def set_dpi_aware() -> None:
    """Make Windows report real pixels (needed at 125%/150% scaling)."""
    global _dpi_set
    if _dpi_set or sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()
    _dpi_set = True


@dataclass
class Shot:
    """A screenshot ready for the model, plus how to map its pixels back."""
    data_url: str
    width: int
    height: int
    scale: float  # real_px = model_px * scale
    left: int = 0
    top: int = 0


def resize_for_model(img: Image.Image, target_width: int = config.SCREENSHOT_WIDTH) -> tuple[Image.Image, float]:
    """Downscale to target_width (never upscale). Returns (image, scale)."""
    if img.width <= target_width:
        return img, 1.0
    scale = img.width / target_width
    height = round(img.height / scale)
    return img.resize((target_width, height), Image.LANCZOS), scale


def to_screen(x: float, y: float, shot: Shot) -> tuple[int, int]:
    """Convert model coordinates to real screen coordinates."""
    return round(x * shot.scale) + shot.left, round(y * shot.scale) + shot.top


def encode(img: Image.Image) -> str:
    """JPEG data URL (about 3x smaller than PNG, so each step uploads faster; same click accuracy)."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def screenshot(monitor: int = 1) -> Shot:
    """Capture a monitor (1 = primary) and prepare it for the model."""
    import mss

    set_dpi_aware()
    with mss.MSS() as sct:
        mon = sct.monitors[monitor]
        raw = sct.grab(mon)
    img = Image.frombytes("RGB", raw.size, raw.rgb)
    small, scale = resize_for_model(img)
    return Shot(encode(small), small.width, small.height, scale, mon["left"], mon["top"])


# pyautogui key names differ from the model's (xdotool-style) names.
_KEY_MAP = {
    "ctrl": "ctrl", "control": "ctrl", "alt": "alt", "shift": "shift",
    "cmd": "win", "super": "win", "meta": "win", "win": "win",
    "enter": "enter", "return": "enter", "esc": "esc", "escape": "esc",
    "space": "space", "tab": "tab", "backspace": "backspace", "delete": "delete",
    "arrowup": "up", "arrowdown": "down", "arrowleft": "left", "arrowright": "right",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "pageup": "pageup", "pagedown": "pagedown", "home": "home", "end": "end",
}


def map_key(key: str) -> str:
    """Translate a model key name to a pyautogui key name."""
    k = key.strip().lower().replace("_", "")
    return _KEY_MAP.get(k, k)


def _get(action, name, default=None):
    """Read a field from an SDK object or a dict."""
    if isinstance(action, dict):
        return action.get(name, default)
    return getattr(action, name, default)


def execute(action, shot: Shot) -> None:
    """Run one computer action with pyautogui. Coordinates come from `shot`."""
    import pyautogui

    set_dpi_aware()
    pyautogui.FAILSAFE = True  # slam mouse into a corner to abort
    kind = _get(action, "type")

    if kind == "click":
        x, y = to_screen(_get(action, "x"), _get(action, "y"), shot)
        button = _get(action, "button", "left")
        if button not in ("left", "right", "middle"):
            button = "middle" if button == "wheel" else "left"
        pyautogui.click(x, y, button=button)
    elif kind == "double_click":
        x, y = to_screen(_get(action, "x"), _get(action, "y"), shot)
        pyautogui.doubleClick(x, y)
    elif kind == "move":
        x, y = to_screen(_get(action, "x"), _get(action, "y"), shot)
        pyautogui.moveTo(x, y)
    elif kind == "drag":
        path = [to_screen(_get(p, "x"), _get(p, "y"), shot) for p in _get(action, "path", [])]
        if path:
            pyautogui.moveTo(*path[0])
            pyautogui.mouseDown()
            for px, py in path[1:]:
                pyautogui.moveTo(px, py, duration=0.1)
            pyautogui.mouseUp()
    elif kind == "scroll":
        x, y = to_screen(_get(action, "x"), _get(action, "y"), shot)
        pyautogui.moveTo(x, y)
        sy = _get(action, "scroll_y", 0) or 0
        sx = _get(action, "scroll_x", 0) or 0
        if sy:
            pyautogui.scroll(-int(sy), x, y)  # model: +y = down; pyautogui: +y = up
        if sx:
            pyautogui.hscroll(int(sx), x, y)
    elif kind == "keypress":
        keys = [map_key(k) for k in _get(action, "keys", [])]
        if len(keys) == 1:
            pyautogui.press(keys[0])
        elif keys:
            pyautogui.hotkey(*keys)
    elif kind == "type":
        _type_text(_get(action, "text", ""))
    elif kind == "wait":
        time.sleep(1.5)
    elif kind == "screenshot":
        pass
    else:
        raise ValueError(f"Unknown action type: {kind}")


def _type_text(text: str) -> None:
    """Type text. Non-ASCII (Telugu/Hindi) goes through the clipboard."""
    import pyautogui

    if text.isascii():
        pyautogui.write(text, interval=0.02)
        return
    import subprocess
    subprocess.run(["clip"], input=text.encode("utf-16-le"), check=True)
    pyautogui.hotkey("ctrl", "v")
