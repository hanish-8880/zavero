"""Transparent, always-on-top overlay: Zavero's avatar (Chai), glass speech bubble and target ring.

Other threads drive it only through the signals (thread-safe). Coordinates passed in are
real screen pixels (what driver.to_screen returns); the overlay converts them to Qt pixels.
The overlay blanks itself for a moment around each model screenshot, so the model never sees
the avatar, but screen recordings (demo video) still do.

Clicks pass straight through the full-screen overlay. Chai itself lives in a small separate
window on top, so it can be dragged anywhere (that spot becomes its new home) or clicked to twirl.

Preview without the rest of the app:
    python -m zavero.overlay
"""
import ctypes
import html
import math
import random
import re
import sys
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QCursor, QFont, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QRadialGradient, QRegion, QTextDocument, QTransform,
)
from PyQt6.QtWidgets import QApplication, QWidget

R = 32  # avatar radius
BUBBLE_W = 290
FONTS = ["Segoe UI Variable Text", "Segoe UI", "Nirmala UI"]  # Nirmala UI covers Telugu + Devanagari

CHAI = (QColor("#F7DDBD"), QColor("#D59A62"), QColor("#9C5B2A"))  # light, mid, dark caramel
EYE = QColor("#120B1A")
BLUSH = QColor("#EE7A8C")
ACCENT = QColor("#B8733A")
MOODS = {
    "info": QColor("#B8733A"),
    "listen": QColor("#0A84FF"),
    "warn": QColor("#F59E0B"),
    "done": QColor("#16A34A"),
    "error": QColor("#DC2626"),
    "hold": QColor("#B8733A"),  # waits for the user (guide step, question): never fades by itself
}
TARGET = QColor("#FFB020")
# Teacher pens for diagram explanations (talk.COLORS)
PENS = {"red": "#E53935", "blue": "#1E66F5", "green": "#1F9D55", "orange": "#F59E0B", "purple": "#8E44AD"}
STEP_S = 3.2  # seconds per explained step: ~1.3 s to draw, the rest to read the caption
FAST_MS, IDLE_MS = 16, 33   # frame time while Chai moves / while it rests
TYPE_S = 0.016              # bubble typewriter: seconds per character
POP_S = 0.35                # bubble pop-in time
TYPE_MAX = 300              # longer answers appear at once (long Telugu text shouldn't drag)


KEEP_MOODS = ("listen", "hold")  # bubbles that stay: live transcript, and ones waiting for the user
FADE_S = 0.4
HOVER_ALPHA, HOVER_S = 0.15, 0.15  # see-through while the mouse is over the bubble
DISMISS_AFTER_S = 1.5              # a click / typing closes a bubble that has been up this long


def reading_time(text: str) -> float:
    """How long a bubble stays before fading: max(6 s, 2.5 s + 55 ms per character), at most 25 s."""
    return min(25.0, max(6.0, 2.5 + 0.055 * len(text)))


def safe_area(avail: QRectF, overlay_origin: QPointF, margin: float = 12) -> QRectF:
    """The screen's work area (no taskbar) in overlay coordinates, shrunk by margin."""
    return QRectF(avail.x() - overlay_origin.x() + margin, avail.y() - overlay_origin.y() + margin,
                  avail.width() - 2 * margin, avail.height() - 2 * margin)


def smoothstep(p: float) -> float:
    return p * p * (3 - 2 * p)


def ease_out_back(x: float) -> float:
    """0 -> 1 with a small overshoot (springy pop)."""
    c1 = 1.70158
    return 1 + (c1 + 1) * (x - 1) ** 3 + c1 * (x - 1) ** 2


def bezier_flight(p0: QPointF, p2: QPointF) -> tuple[QPointF, float]:
    """Control point and duration for a curved flight (Clicky's numbers): the midpoint lifted by
    min(distance * 0.2, 80) px, duration clamp(distance / 800, 0.6, 1.4) s."""
    d = p2 - p0
    dist = math.hypot(d.x(), d.y())
    mid = (p0 + p2) / 2
    return QPointF(mid.x(), mid.y() - min(dist * 0.2, 80)), min(max(dist / 800, 0.6), 1.4)


def bezier(p0: QPointF, p1: QPointF, p2: QPointF, t: float) -> tuple[QPointF, QPointF]:
    """Point and tangent of a quadratic Bezier at t."""
    u = 1 - t
    pos = p0 * (u * u) + p1 * (2 * u * t) + p2 * (t * t)
    tan = (p1 - p0) * (2 * u) + (p2 - p1) * (2 * t)
    return pos, tan


def partial_markup(text: str, n: int) -> str:
    """First n characters for the typewriter, with an open **bold** closed so it renders as bold."""
    part = text[:n]
    return part + "**" if part.count("**") % 2 else part


def to_html(text: str) -> str:
    """Escape text, turn **bold** into <b>, keep line breaks."""
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return t.replace("\n", "<br>")


def ui_font(pt: float, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(FONTS)
    f.setPointSizeF(pt)
    if bold:
        f.setWeight(QFont.Weight.DemiBold)
    return f


# --- Chai, the wool-felt buddy ------------------------------------------------
def _chai_point(a: float) -> tuple[float, float]:
    """Chai's cloud outline in design units (about 208 wide), same shape as design/zavero-buddies.html."""
    k = 1 - 0.85 * max(0.0, math.sin(a))  # bumps fade out towards the flat bottom
    r = 104 * (1 + 0.075 * math.cos(7 * a + math.pi / 2) * k)
    return r * math.cos(a), r * math.sin(a) * 0.86 + 8


_CHAI_PTS = [(a, *_chai_point(a)) for a in (i / 64 * math.tau for i in range(64))]
_BOTTOM = 96  # lowest point of the cloud, used as the squash anchor
_rnd = random.Random(11)
# Stray fibres on the fuzzy edge: (position along segment, angle jitter, length, light?) - fixed, so no flicker.
_EDGE = [[(k / 4 + _rnd.uniform(-0.1, 0.1), _rnd.uniform(-0.6, 0.6), _rnd.uniform(1.0, 2.8), _rnd.random() < 0.55)
          for k in range(4)] for _ in _CHAI_PTS]
_FELT: QImage | None = None


def _felt_tile() -> QImage:
    """Dense tiny wool fibres on a transparent tile. Made once (seeded) and tiled over the body."""
    global _FELT
    if _FELT is None:
        size = 96
        screen = QApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen else 1.0
        img = QImage(int(size * dpr), int(size * dpr), QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rnd = random.Random(7)
        for _ in range(2600):
            x, y = rnd.uniform(0, size), rnd.uniform(0, size)
            ang, ln = rnd.uniform(0, math.tau), rnd.uniform(1.0, 2.8)
            if rnd.random() < 0.5:
                col = QColor(255, 248, 236, rnd.randint(30, 70))
            else:
                col = QColor(80, 40, 12, rnd.randint(25, 55))
            pen = QPen(col, rnd.uniform(0.4, 0.75))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            dx, dy = math.cos(ang) * ln, math.sin(ang) * ln
            for ox in (-size, 0, size):  # wrap around so the tile is seamless
                for oy in (-size, 0, size):
                    p.drawLine(QPointF(x + ox, y + oy), QPointF(x + ox + dx, y + oy + dy))
        p.end()
        _FELT = img
    return _FELT


def _smooth(pts: list[tuple[float, float]]) -> QPainterPath:
    """Closed Catmull-Rom curve through the points."""
    n = len(pts)
    path = QPainterPath(QPointF(*pts[0]))
    for i in range(n):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        path.cubicTo(
            QPointF(p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6),
            QPointF(p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6),
            QPointF(*p2),
        )
    return path


def paint_chai(p: QPainter, c: QPointF, size: float, t: float, look: QPointF = QPointF(),
               listening: bool = False, happy: bool = False, eye_open: float = 1.0,
               steam: bool = True, rot: float = 0.0, spin: float = 1.0) -> None:
    """Draw Chai centred at c. size ~ body radius in px; look in [-1, 1]; rot in degrees;
    spin = horizontal scale during a twirl (face hidden when < 0)."""
    s = size / 104
    breathe = math.sin(t * 1.3)
    sx, sy, wob, eye_scale = 1 + 0.035 * breathe, 1 + 0.045 * breathe, 0.028, 1.0
    if listening:  # leans in, wobbles faster, eyes bigger
        sx, sy, wob, eye_scale = sx * 1.05, sy * 1.05, 0.05, 1.15
    p.save()
    p.translate(c.x(), c.y() + _BOTTOM * s)
    p.rotate(rot)
    p.scale(s * sx * spin, s * sy)
    p.translate(0, -_BOTTOM)

    if steam:  # three soft wisps rising from the warm head
        for i, x in enumerate((-26, 0, 26)):
            ph = (t * 0.35 + i / 3) % 1
            col = QColor(CHAI[2])
            col.setAlphaF(math.sin(math.pi * ph) * 0.5)
            pen = QPen(col, 7)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            y0 = -96 - ph * 30
            wisp = QPainterPath(QPointF(x, y0))
            wisp.cubicTo(QPointF(x + 8, y0 - 10), QPointF(x - 8, y0 - 20), QPointF(x, y0 - 30))
            wisp.cubicTo(QPointF(x + 8, y0 - 40), QPointF(x - 8, y0 - 50), QPointF(x, y0 - 60))
            p.drawPath(wisp)

    # body: living outline, matte caramel wool
    speed = 1.6 if listening else 1.0
    pts = []
    for a, x, y in _CHAI_PTS:
        k = 1 + wob * (math.sin(3 * a + t * 1.7 * speed + 5.2) + 0.6 * math.sin(5 * a - t * 2.3 * speed + 10.4)) / 1.6
        pts.append((x * k, y * k))
    body = _smooth(pts)
    p.setPen(Qt.PenStyle.NoPen)
    g = QRadialGradient(QPointF(-22, -30), 175)
    for stop, col in zip((0, 0.5, 1), CHAI):
        g.setColorAt(stop, col)
    p.setBrush(QBrush(g))
    p.drawPath(body)
    shade = QRadialGradient(QPointF(-18, -26), 150)  # soft 3D: darker towards the lower edge
    shade.setColorAt(0.55, QColor(0, 0, 0, 0))
    shade.setColorAt(1, QColor(70, 30, 8, 95))
    p.setBrush(QBrush(shade))
    p.drawPath(body)
    light = QRadialGradient(QPointF(-40, -46), 70)  # broad matte light, no glossy shine
    light.setColorAt(0, QColor(255, 250, 240, 55))
    light.setColorAt(1, QColor(255, 250, 240, 0))
    p.setBrush(QBrush(light))
    p.drawPath(body)

    # felt fibres + fuzzy edge, drawn in screen pixels so they stay tiny at any size
    world = p.transform()
    dev_body = world.map(body)
    dev_pts = [world.map(QPointF(x, y)) for x, y in pts]
    centre = world.map(QPointF(0, 0))
    p.save()
    p.resetTransform()
    felt = QBrush(_felt_tile())
    felt.setTransform(QTransform.fromTranslate(c.x(), c.y()))  # texture travels with Chai
    p.fillPath(dev_body, felt)
    light_fibre, dark_fibre = QColor(CHAI[0]), QColor(CHAI[1])
    light_fibre.setAlpha(170)
    dark_fibre.setAlpha(150)
    n = len(dev_pts)
    for i, a0 in enumerate(dev_pts):
        a1 = dev_pts[(i + 1) % n]
        for u, jit, ln, is_light in _EDGE[i]:
            base = a0 + (a1 - a0) * u
            out = base - centre
            norm = math.hypot(out.x(), out.y()) or 1
            ang = math.atan2(out.y(), out.x()) + jit
            start = base - out * (0.8 / norm)
            pen = QPen(light_fibre if is_light else dark_fibre, 0.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(start, start + QPointF(math.cos(ang) * ln, math.sin(ang) * ln))
    p.restore()

    if spin > 0:  # face only when Chai faces us
        p.setOpacity(min(1.0, spin * 4))
        # face slides toward where Chai looks; a bit bigger than the design so it reads when small
        p.translate(look.x() * 12, 16 + look.y() * 8)
        p.scale(1.25, 1.25)
        p.setPen(Qt.PenStyle.NoPen)
        for bx in (-46, 46):
            blush = QRadialGradient(QPointF(bx, 21), 15)
            col = QColor(BLUSH)
            col.setAlpha(160 if happy else 115)
            blush.setColorAt(0, col)
            col.setAlpha(0)
            blush.setColorAt(1, col)
            p.setBrush(QBrush(blush))
            p.drawEllipse(QPointF(bx, 21), 16, 10)
        for ex in (-32, 32):
            eye = QPointF(ex + look.x() * 6, look.y() * 5)
            if happy:
                pen = QPen(EYE, 5)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                arc = QPainterPath(eye + QPointF(-10, 4))
                arc.quadTo(eye + QPointF(0, -9), eye + QPointF(10, 4))
                p.drawPath(arc)
                p.setPen(Qt.PenStyle.NoPen)
                continue
            p.setBrush(EYE)  # black safety-button eyes, like a real plush toy
            p.drawEllipse(eye, 10 * eye_scale, max(1.0, 14 * eye_scale * eye_open))
            if eye_open > 0.5:
                p.setBrush(QColor(255, 255, 255, 230))
                p.drawEllipse(eye + QPointF(-3.2, -5.2), 3.2, 3.2)
        pen = QPen(QColor("#3A1D10"), 4)  # stitched smile
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        smile = QPainterPath(QPointF(-10, 22))
        smile.quadTo(QPointF(0, 31), QPointF(10, 22))
        p.drawPath(smile)
    p.restore()


def avatar_icon(size: int = 64) -> QIcon:
    """Chai as an icon (system tray)."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint_chai(p, QPointF(size / 2, size / 2), size * 0.42, 0.0, steam=False)
    p.end()
    return QIcon(pix)


# --- the overlay window ---------------------------------------------------------
CHAI_W, CHAI_H = 140, 160          # Chai's own window
CHAI_CX, CHAI_CY = 70, 90          # where Chai's centre sits inside it


class _ChaiWindow(QWidget):
    """Small top-level window that draws Chai and catches drags. Everything else is in Overlay."""

    def __init__(self, ov: "Overlay") -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.ov = ov
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.resize(CHAI_W, CHAI_H)

    def set_click_through(self, on: bool) -> None:
        """While Chai rides next to the mouse, clicks must go to the app underneath (WS_EX_TRANSPARENT)."""
        if sys.platform != "win32" or not self.isVisible():
            return
        hwnd = int(self.winId())
        user32 = ctypes.windll.user32
        ex = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
        user32.SetWindowLongW(hwnd, -20, (ex | 0x20) if on else (ex & ~0x20))

    def offset(self) -> QPointF:
        """This window's top-left in overlay coordinates."""
        g = self.ov.geometry()
        return QPointF(self.x() - g.x(), self.y() - g.y())

    def paintEvent(self, event) -> None:
        if self.ov._invisible:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(-self.offset())
        self.ov._paint_avatar(p)

    def _local(self, e) -> QPointF:
        g = self.ov.geometry()
        return e.globalPosition() - QPointF(g.x(), g.y())

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.ov._drag_start(self._local(e))

    def mouseMoveEvent(self, e) -> None:
        self.ov._drag_move(self._local(e))

    def mouseReleaseEvent(self, e) -> None:
        self.ov._drag_end()


class Overlay(QWidget):
    show_text = pyqtSignal(str, str)   # text, mood
    point_at = pyqtSignal(int, int)    # real screen px
    set_label = pyqtSignal(str)        # small chip next to the target ("Pay Bill", "ఇక్కడే!"); after point_at
    tap_at = pyqtSignal(int, int)      # real screen px
    go_home = pyqtSignal()             # avatar back to its corner, no target
    set_listening = pyqtSignal(bool)
    set_level = pyqtSignal(float)      # mic loudness 0..1 while listening (voice.mic_level)
    set_mode = pyqtSignal(str)         # "Guide" / "Doing" / ...
    set_thinking = pyqtSignal(bool)    # thinking dots while waiting for the model
    hide_text = pyqtSignal()
    dismiss = pyqtSignal()             # user clicked elsewhere / started typing: close a non-"hold" bubble
    attention = pyqtSignal()           # Chai twirls to catch the user's eye (reminders)
    show_board = pyqtSignal(bytes, list, float)  # PNG of a diagram, steps (talk.clean_drawing), its x on screen 0..1
    hide_board = pyqtSignal()
    _capture_sig = pyqtSignal(bool)    # blocking: hide/show around model screenshots

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        screen = QApplication.primaryScreen()
        self._dpr = screen.devicePixelRatio()
        self.setGeometry(screen.geometry())

        self._home = QPointF(self.width() - 70, self.height() - 130)
        self._thinking = False
        self._avatar = QPointF(self._home)
        self._target: QPointF | None = None
        self._text = ""
        self._mood = "info"
        self._mode = "Guide"
        self._listening = False
        self._level = 0.0        # smoothed mic level: jumps up, decays x0.72 per 70 ms (Clicky's feel)
        self._taps: list[tuple[QPointF, float]] = []
        self._t = 0.0
        self._look = QPointF(0, 0)
        self._blink_at, self._double, self._next_blink = -9.0, False, 2.0
        self._cursor = QPointF(-999, -999)
        self._pet = 0.0          # 0..1, rises while the mouse strokes Chai
        self._twirl_at = -9.0
        self._hover = False
        self._hwnd = 0
        self._drag: QPointF | None = None   # offset from cursor to avatar while dragging
        self._press = QPointF()
        self._moved = False
        self._chai = _ChaiWindow(self)

        # Curved flight: (start, control, end, start time, duration), driven by _tick with real time.
        self._flight: tuple[QPointF, QPointF, QPointF, float, float] | None = None
        self._scale = 1.0    # puffs up mid-flight
        self._lean = 0.0     # degrees, leans toward where it flies
        self._clock0 = self._last = time.perf_counter()
        self._dt = 0.033
        self._text_born = -99.0                  # bubble pop + typewriter start
        self._bubble_size = (0.0, 0.0)
        self._bubble_last = QRectF()
        self._shown_at = -99.0      # when the current bubble text appeared
        self._fade = 1.0            # 1 -> 0 while the bubble fades out
        self._hover_alpha = 1.0     # drops to HOVER_ALPHA while the mouse is over the bubble
        self._bubble_anim = False
        self._target_last = QRectF()
        self._label, self._label_born, self._label_at = "", 0.0, [0.0]  # chip text, start, per-char times
        self.follow_mode = "auto"   # set from main.py (saved in data/state.json); see FOLLOW_MODES
        self._following = False
        self.show_mode = "always"   # or "talk": only while the user talks / Zavero helps (tray, state.json)
        self._opacity = 1.0
        self._through = False
        self._vel = QPointF()
        self._active_at = -99.0

        if sys.platform == "win32":  # 1 ms timer resolution so 16 ms frames are really 16 ms
            ctypes.windll.winmm.timeBeginPeriod(1)
            QApplication.instance().aboutToQuit.connect(lambda: ctypes.windll.winmm.timeEndPeriod(1))
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(IDLE_MS)

        self.show_text.connect(self._on_text)
        self.point_at.connect(self._on_point)
        self.set_label.connect(self._on_label)
        self.tap_at.connect(self._on_tap)
        self.go_home.connect(self._on_home)
        self.set_listening.connect(self._on_listening)
        self.set_level.connect(lambda v: setattr(self, "_level", max(v, self._level)))
        self.set_mode.connect(self._on_mode)
        self.set_thinking.connect(self._on_thinking)
        self.hide_text.connect(lambda: self._on_text("", self._mood))
        self.dismiss.connect(self._on_dismiss)
        self.attention.connect(lambda: setattr(self, "_twirl_at", self._t))
        self._board: tuple[QImage, list, float, float] | None = None  # image, marks, side, start time
        self.show_board.connect(self._on_board)
        self.hide_board.connect(lambda: (setattr(self, "_board", None), self.update()))
        self._invisible = False
        self._capture_sig.connect(self._set_invisible, Qt.ConnectionType.BlockingQueuedConnection)

    # --- window setup ---------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_chai()
        self._chai.show()
        if sys.platform == "win32":
            self._hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            ex = user32.GetWindowLongW(self._hwnd, -20)  # GWL_EXSTYLE
            # WS_EX_TRANSPARENT | WS_EX_NOACTIVATE: clicks pass through, never steals focus
            user32.SetWindowLongW(self._hwnd, -20, ex | 0x20 | 0x08000000)
            self._raise_timer = QTimer(self)
            self._raise_timer.timeout.connect(self._stay_on_top)
            self._raise_timer.start(1000)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._chai.hide()

    def _stay_on_top(self) -> None:
        """Other always-on-top windows can cover us; push back to the top without taking focus.
        Chai goes last so it stays above the overlay."""
        # HWND_TOPMOST, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
        flags = 0x0002 | 0x0001 | 0x0010 | 0x0040
        ctypes.windll.user32.SetWindowPos(self._hwnd, -1, 0, 0, 0, 0, flags)
        ctypes.windll.user32.SetWindowPos(int(self._chai.winId()), -1, 0, 0, 0, 0, flags)

    def _sync_chai(self) -> None:
        """Keep Chai's little window centred on the avatar position."""
        g = self.geometry()
        self._chai.move(round(g.x() + self._avatar.x() - CHAI_CX), round(g.y() + self._avatar.y() - CHAI_CY))
        self._chai.update()

    def _set_invisible(self, on: bool) -> None:
        self._invisible = on
        self.repaint()
        self._chai.repaint()

    def hide_for_capture(self) -> None:
        """Call from a worker thread right before a model screenshot. Blocks until hidden."""
        self._capture_sig.emit(True)
        time.sleep(0.08)  # let Windows redraw the screen without us

    def show_after_capture(self) -> None:
        self._capture_sig.emit(False)

    def local(self, x: int, y: int) -> QPointF:
        """Real screen px -> overlay px."""
        g = self.geometry()
        return QPointF(x / self._dpr - g.x(), y / self._dpr - g.y())

    def _on_chai(self, pt: QPointF) -> bool:
        d = pt - self._avatar
        return math.hypot(d.x(), d.y()) < R + 8

    def is_on_avatar(self, x: int, y: int) -> bool:
        """True if real screen px (x, y) is on Chai (safe to call from any thread)."""
        return not self._invisible and self._opacity > 0 and self._on_chai(self.local(x, y))

    # --- dragging Chai (events come from _ChaiWindow, in overlay coordinates) ----
    def _drag_start(self, pos: QPointF) -> None:
        if self._on_chai(pos):
            self._flight = None
            self._drag, self._press, self._moved = self._avatar - pos, QPointF(pos), False
            self._chai.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _drag_move(self, pos: QPointF) -> None:
        if self._drag is None:
            return
        d = pos - self._press
        if math.hypot(d.x(), d.y()) > 4:
            self._moved = True
        if self._moved:
            self._set_avatar(self._clamp(pos + self._drag))

    def _drag_end(self) -> None:
        if self._drag is None:
            return
        self._drag = None
        self._chai.setCursor(Qt.CursorShape.OpenHandCursor)
        if self._moved:
            self._home = QPointF(self._avatar)  # Chai lives where the user put it
        else:
            self._twirl_at = self._t  # a simple click = happy twirl

    def _clamp(self, pt: QPointF) -> QPointF:
        return QPointF(min(max(pt.x(), R + 8), self.width() - R - 8),
                       min(max(pt.y(), R + 40), self.height() - R - 12))

    # --- slots ----------------------------------------------------------
    def _on_text(self, text: str, mood: str) -> None:
        old = self._text
        self._text, self._mood = text, mood
        if text and text != old:
            self._active_at = self._shown_at = self._t
            self._fade = 1.0
        if text:
            _, w, h = self._bubble_doc(text)
            self._bubble_size = (w, h)
        # Pop in and type out real messages; live transcripts ("listen") just update in place.
        if text and mood != "listen" and text != old:
            self._text_born = self._t
        elif mood == "listen":
            self._text_born = -99.0
        self.update()

    def _on_dismiss(self) -> None:
        if self._text and self._mood not in KEEP_MOODS and self._t - self._shown_at >= DISMISS_AFTER_S:
            self._shown_at = -999.0  # past its reading time: _step_bubble fades it out now

    def _step_bubble(self) -> None:
        """Fade a bubble out after its reading time; make it see-through while the mouse is over it."""
        old = (self._fade, self._hover_alpha)
        if self._text and self._mood not in KEEP_MOODS and self._t - self._shown_at > reading_time(self._text):
            self._fade = max(0.0, self._fade - self._dt / FADE_S)
            if self._fade == 0:
                self._on_text("", self._mood)
                self._fade = 1.0
        over = bool(self._text) and self._bubble_last.contains(self._cursor)
        goal = HOVER_ALPHA if over else 1.0
        step = (1 - HOVER_ALPHA) * self._dt / HOVER_S
        self._hover_alpha = max(goal, self._hover_alpha - step) if over else min(goal, self._hover_alpha + step)
        self._bubble_anim = (self._fade, self._hover_alpha) != old

    def _on_board(self, png: bytes, marks: list, side: float) -> None:
        img = QImage.fromData(png)
        self._board = (img, marks, side, self._t) if not img.isNull() else None
        self._target = None
        self.update()

    def _on_point(self, x: int, y: int) -> None:
        self._target = self.local(x, y)
        self._label = ""
        if self._drag is None:
            self._fly_to(self._perch(self._target))

    def _on_label(self, text: str) -> None:
        """Chip text next to the target, typed one letter every 30-60 ms (random, feels hand-written)."""
        self._label, self._label_born = text.strip()[:40], self._t
        at, acc = [], 0.0
        for _ in self._label:
            acc += random.uniform(0.03, 0.06)
            at.append(acc)
        self._label_at = at or [0.0]
        self.update()

    def _on_tap(self, x: int, y: int) -> None:
        self._taps.append((self.local(x, y), self._t))

    def _on_home(self) -> None:
        self._target = None
        if self._drag is None and not self._should_follow():  # while following, the spring takes over
            self._fly_to(self._home)

    def _on_listening(self, on: bool) -> None:
        self._listening = on
        self._active_at = self._t
        self.update()

    def _on_thinking(self, on: bool) -> None:
        self._thinking = on
        self._active_at = self._t
        self.update()

    # --- follow the mouse (F27) -----------------------------------------
    FOLLOW_MODES = ("auto", "always", "corner")  # auto = ride beside the mouse while helping, corner when idle
    FOLLOW_GAP = QPointF(48, 40)                 # Clicky rides +35/+25 with a tiny cursor; Chai is bigger
    ACTIVE_S = 12                                # after the last message, "helping" lasts this long

    def _should_follow(self) -> bool:
        if (self.follow_mode == "corner" or self._drag is not None or self._flight is not None
                or self._target is not None or self._board or self._invisible):
            return False
        if self.follow_mode == "always":
            return True
        return self._listening or self._thinking or (bool(self._text) and self._t - self._active_at < self.ACTIVE_S)

    def _follow_goal(self) -> QPointF:
        """Below-right of the cursor, flipped near the screen edges so Chai never hides off-screen."""
        c, g = self._cursor, self.FOLLOW_GAP
        x = c.x() + g.x() if c.x() + g.x() + R + 8 < self.width() else c.x() - g.x()
        y = c.y() + g.y() if c.y() + g.y() + R + 12 < self.height() else c.y() - g.y()
        return self._clamp(QPointF(x, y))

    def _step_follow(self) -> None:
        following = self._should_follow()
        if following:  # critically damped spring: same feel as Clicky's buddy
            dt = self._dt
            self._vel += (self._follow_goal() - self._avatar) * (180 * dt)
            self._vel *= 0.75 ** (dt * 60)
            step = self._vel * dt
            if math.hypot(step.x(), step.y()) > 0.05:
                self._set_avatar(self._avatar + step)
        elif self._following:  # stopped helping: go back to the corner (unless pointing somewhere)
            self._vel = QPointF()
            if self._target is None and self._flight is None and self._drag is None:
                self._fly_to(self._home)
        self._following = following

    def _step_visibility(self) -> None:
        """Tray "Only while I talk": appear on the hotkey, fade out (0.4 s) once Zavero is done helping."""
        want = (self.show_mode == "always" or self._listening or self._thinking or self._target is not None
                or bool(self._board) or self._drag is not None or self._flight is not None
                or (bool(self._text) and self._t - self._active_at < self.ACTIVE_S))
        op = 1.0 if want else max(0.0, self._opacity - self._dt / 0.4)
        if op != self._opacity:
            self._opacity = op
            self.setWindowOpacity(op)
            self._chai.setWindowOpacity(op)
        # A riding or faded-out Chai must never catch the user's clicks.
        through = self._following or op == 0
        if through != self._through:
            self._through = through
            self._chai.set_click_through(through)

    def _on_mode(self, mode: str) -> None:
        self._mode = mode
        self.update()

    def _set_avatar(self, p) -> None:
        """Move Chai's own small window; the big overlay repaints only what changed (in _tick)."""
        self._avatar = QPointF(p)
        self._sync_chai()

    def _fly_to(self, p: QPointF) -> None:
        """Curved flight with smoothstep easing, a scale pulse and a lean toward the travel direction."""
        start = QPointF(self._avatar)
        d = p - start
        if math.hypot(d.x(), d.y()) < 2:
            self._flight = None
            return
        ctrl, dur = bezier_flight(start, p)
        self._flight = (start, ctrl, QPointF(p), self._t, dur)
        self._timer.setInterval(FAST_MS)

    def _perch(self, t: QPointF) -> QPointF:
        """Where the avatar sits next to a target: up-left of it, or flipped near edges."""
        dx = -62 if t.x() > 120 else 62
        dy = -62 if t.y() > 120 else 62
        return self._clamp(QPointF(t.x() + dx, t.y() + dy))

    def _tick(self) -> None:
        # Real elapsed time, so a slow frame never makes motion stutter or slow down.
        now = time.perf_counter()
        dt = min(0.1, now - self._last)
        self._last, self._dt = now, dt
        self._t = now - self._clock0
        self._taps = [(p, b) for p, b in self._taps if self._t - b < 0.7]
        self._level *= 0.72 ** (dt / 0.07)
        before = QPointF(self._avatar)
        self._step_flight()

        cur = QPointF(self.mapFromGlobal(QCursor.pos()))
        d = cur - self._cursor
        speed = math.hypot(d.x(), d.y()) / max(dt, 1e-3)
        self._cursor = cur
        self._step_follow()
        self._step_visibility()
        self._step_bubble()
        hover = self._on_chai(cur) and not self._invisible  # catch clicks only while the mouse is on Chai
        if self._drag is None and hover != self._hover:
            self._chai.setCursor(Qt.CursorShape.OpenHandCursor if hover else Qt.CursorShape.ArrowCursor)
        self._hover = hover
        stroking = hover and speed > 40 and self._drag is None
        self._pet += ((1.0 if stroking else 0.0) - self._pet) * (0.18 if stroking else 0.06) * dt / 0.033
        self._timer.setInterval(FAST_MS if self._flight or self._following else IDLE_MS)
        self._repaint_changed(self._avatar != before)
        self._chai.update()

    def _step_flight(self) -> None:
        if self._flight is None:
            self._scale += (1.0 - self._scale) * 0.3
            self._lean += (0.0 - self._lean) * 0.2
            return
        p0, p1, p2, born, dur = self._flight
        prog = min(1.0, (self._t - born) / dur)
        pos, tan = bezier(p0, p1, p2, smoothstep(prog))
        n = math.hypot(tan.x(), tan.y()) or 1
        self._lean = 15 * tan.x() / n  # a creature leans into the flight, it doesn't spin like an arrow
        self._scale = 1 + 0.2 * math.sin(prog * math.pi)
        self._set_avatar(pos)
        if prog >= 1:
            self._flight = None

    def _repaint_changed(self, moved: bool) -> None:
        """Repaint only the parts of the full-screen overlay that change, never the whole screen each frame."""
        region = QRegion()

        def add(r: QRectF) -> None:
            nonlocal region
            if not r.isEmpty():
                region = region.united(QRegion(r.toAlignedRect()))

        if self._target is not None:  # pulsing ring + dashed line to Chai + label chip
            t, a = self._target, self._avatar
            reach = 0.15 * math.hypot(t.x() - a.x(), t.y() - a.y()) + 40
            box = QRectF(t, a).normalized().adjusted(-reach, -reach, reach, reach)
            box = box.united(QRectF(t.x() - 280, t.y() - 30, 560, 60))  # label chip, either side
            add(box)
            add(self._target_last)
            self._target_last = box
        elif not self._target_last.isEmpty():
            add(self._target_last)
            self._target_last = QRectF()
        for pos, _ in self._taps:
            add(QRectF(pos.x() - 45, pos.y() - 45, 90, 90))
        if self._board:
            add(getattr(self, "_board_rect", QRectF(self.rect())).adjusted(-20, -20, 20, 30))
        if self._text:
            age = self._t - self._text_born
            typing = age < POP_S or (len(self._text) <= TYPE_MAX and age < len(self._text) * TYPE_S + 0.1)
            if moved or typing or self._bubble_anim:
                add(self._bubble_rect(*self._bubble_size).adjusted(-12, -12, 12, 16))
                add(self._bubble_last)
        if not region.isEmpty():
            self.update(region)

    # --- painting -------------------------------------------------------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        if self._invisible:
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._target is not None:
            self._paint_target(p)
        for pos, born in self._taps:
            age = (self._t - born) / 0.7
            c = QColor(TARGET)
            c.setAlphaF(max(0.0, 1 - age))
            p.setPen(QPen(c, 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            r = 6 + 32 * age
            p.drawEllipse(pos, r, r)
        if self._board:
            self._paint_board(p)
        if self._text:  # Chai itself is painted by its own window (_ChaiWindow)
            self._paint_bubble(p)

    def _paint_target(self, p: QPainter) -> None:
        t = self._target
        pulse = 15 + 3 * math.sin(self._t * 5)
        glow = QColor(TARGET)
        glow.setAlpha(40)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(t, pulse + 5, pulse + 5)
        p.setPen(QPen(TARGET, 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(t, pulse, pulse)
        # dashed curve from the avatar to the target
        a = self._avatar
        d = t - a
        dist = math.hypot(d.x(), d.y())
        if dist > R + pulse + 4:
            start = a + d * (R / dist)
            end = t - d * ((pulse + 4) / dist)
            mid = (start + end) / 2 + QPointF(-d.y(), d.x()) * 0.15
            path = QPainterPath(start)
            path.quadTo(mid, end)
            pen = QPen(TARGET, 2, Qt.PenStyle.DashLine)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawPath(path)
        if self._label:
            self._paint_label(p, t, pulse)

    def _paint_label(self, p: QPainter, t: QPointF, pulse: float) -> None:
        """Dark pill beside the ring with the thing's name, typed letter by letter."""
        age = self._t - self._label_born
        shown = self._label[:sum(1 for at in self._label_at if at <= age)]
        if not shown:
            return
        font = ui_font(9, bold=True)
        p.setFont(font)
        full_w = p.fontMetrics().horizontalAdvance(self._label) + 22
        w, h = p.fontMetrics().horizontalAdvance(shown) + 22, 26
        x = t.x() + pulse + 12
        if x + full_w > self.width() - 8:  # no room on the right: put it on the left of the ring
            x = t.x() - pulse - 12 - full_w
        box = QRectF(x, t.y() - h / 2, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(15, 23, 42, 40))
        p.drawRoundedRect(box.adjusted(-1, 1, 1, 3), h / 2, h / 2)
        p.setBrush(QColor(15, 23, 42, 225))
        p.drawRoundedRect(box, h / 2, h / 2)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, shown)

    def _paint_avatar(self, p: QPainter) -> None:
        a = self._avatar
        lift = 0.0
        tw = (self._t - self._twirl_at) / 0.9
        spin = 1.0
        if 0 <= tw < 1:  # twirl: spin once with a little hop
            e = 2 * tw * tw if tw < 0.5 else 1 - (-2 * tw + 2) ** 2 / 2
            spin = math.cos(math.tau * e)
            lift = math.sin(math.pi * tw) * 14
        if self._drag is not None and self._moved:
            lift = 6  # held up in the air while dragging
        c = QPointF(a.x(), a.y() + math.sin(self._t * 2.2) * 1.5 - lift)

        mood = MOODS["listen"] if self._listening else ACCENT
        if self._listening:
            for k in range(2):
                phase = (self._t * 1.2 + k * 0.5) % 1.0
                ring = QColor(mood)
                ring.setAlphaF(0.45 * (1 - phase))
                p.setPen(QPen(ring, 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, R + 8 + 20 * phase, R + 8 + 20 * phase)
        # soft ground shadow, smaller while Chai is up in the air
        shadow = QRadialGradient(QPointF(a.x(), a.y() + R + 6), R * 0.85)
        shadow.setColorAt(0, QColor(0, 0, 0, max(15, 60 - int(lift * 3))))
        shadow.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(shadow))
        p.drawEllipse(QPointF(a.x(), a.y() + R + 6), R * 0.85 * (1 - lift / 40), 6)

        # where Chai looks: the target, up-right while thinking, else the mouse
        if self._target is not None:
            d = self._target - a
            n = math.hypot(d.x(), d.y()) or 1
            look = QPointF(d.x() / n * 0.85, d.y() / n * 0.85)
        elif self._thinking:
            look = QPointF(0.75, -0.85)
        else:
            d = self._cursor - a
            n = math.hypot(d.x(), d.y())
            look = QPointF(d.x() / (n + 60), d.y() / (n + 60))
        self._look += (look - self._look) * min(1.0, 0.22 * self._dt / 0.033)

        if self._t > self._next_blink:  # random blinks, sometimes a double blink
            self._blink_at = self._t
            self._double = random.random() < 0.25
            self._next_blink = self._t + 2 + random.random() * 3.5
        d0 = self._t - self._blink_at
        closed = math.sin(math.pi * d0 / 0.16) if d0 < 0.16 else 0.0
        if self._double and 0.26 < d0 < 0.42:
            closed = math.sin(math.pi * (d0 - 0.26) / 0.16)

        # lean toward the look + into the flight + petting wiggle
        rot = self._look.x() * 5 + self._lean + math.sin(self._t * 14) * 4 * self._pet
        happy = (self._mood == "done" and bool(self._text)) or self._pet > 0.45 or spin < 0.95
        paint_chai(p, c, R * self._scale, self._t, self._look, listening=self._listening, happy=happy,
                   eye_open=1 - closed, steam=not self._thinking, rot=rot, spin=spin)
        if self._listening:  # live mic wave: five bars under Chai, so a dead mic shows right away
            for k, shape in enumerate((0.4, 0.7, 1.0, 0.7, 0.4)):
                wobble = 0.12 * (1 + math.sin(self._t * 7 + k * 1.3))
                bar = 3 + 15 * min(1.0, self._level * shape + wobble * shape)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(mood)
                p.drawRoundedRect(QRectF(a.x() - 18 + k * 8 - 2, a.y() + R + 20 - bar / 2, 4, bar), 2, 2)
        if self._thinking:  # three bouncing dots above the head
            for k in range(3):
                dy = -abs(math.sin(self._t * 6 + k * 0.7)) * 5
                pos = c + QPointF(-10 + k * 10, -R - 12 + dy)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 235))
                p.drawEllipse(pos, 4.5, 4.5)
                p.setBrush(mood)
                p.drawEllipse(pos, 2.6, 2.6)

    @staticmethod
    def _bubble_doc(text: str, width: float | None = None) -> tuple[QTextDocument, float, float]:
        """Laid-out bubble text and the bubble size (w, h) it needs. width fixes the text width."""
        pad = 14
        doc = QTextDocument()
        doc.setDefaultFont(ui_font(10.5))
        doc.setDocumentMargin(0)
        doc.setHtml(f"<div style='color:#0F172A; line-height:125%'>{to_html(text)}</div>")
        if width is None:
            doc.setTextWidth(BUBBLE_W - 2 * pad)
            width = max(160, min(BUBBLE_W, doc.idealWidth() + 2 * pad))
        doc.setTextWidth(width - 2 * pad)
        return doc, width, doc.size().height() + 44  # text + header + padding

    def _paint_bubble(self, p: QPainter) -> None:
        pad = 14
        w, h = self._bubble_size  # sized for the full text, so the bubble doesn't jump while typing
        age = self._t - self._text_born
        text = self._text
        if len(text) <= TYPE_MAX and age < len(text) * TYPE_S:
            text = partial_markup(text, int(age / TYPE_S) + 1)
        doc, _, _ = self._bubble_doc(text, w)
        rect = self._bubble_rect(w, h)
        self._bubble_last = rect.adjusted(-12, -12, 12, 16)
        radius = 16
        mood = MOODS.get(self._mood, ACCENT)
        p.save()
        p.setOpacity(self._fade * self._hover_alpha)  # fading out / see-through under the mouse
        if age < POP_S:  # springy pop from half size, growing out of the side next to Chai
            s = 0.5 + 0.5 * ease_out_back(age / POP_S)
            o = QPointF(min(max(self._avatar.x(), rect.left()), rect.right()),
                        min(max(self._avatar.y(), rect.top()), rect.bottom()))
            p.translate(o)
            p.scale(s, s)
            p.translate(-o)

        # soft layered shadow
        p.setPen(Qt.PenStyle.NoPen)
        for grow, alpha in ((10, 10), (6, 14), (3, 18)):
            p.setBrush(QColor(15, 23, 42, alpha))
            p.drawRoundedRect(rect.adjusted(-grow / 2, grow / 3, grow / 2, grow), radius + grow / 2, radius + grow / 2)
        # frosted glass: see-through white with a faint tint of the mood colour
        glass = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        glass.setColorAt(0, QColor(255, 255, 255, 212))
        glass.setColorAt(1, QColor(250, 248, 253, 178))
        p.setBrush(QBrush(glass))
        p.drawRoundedRect(rect, radius, radius)
        tint = QColor(mood)
        tint.setAlpha(14)
        p.setBrush(tint)
        p.drawRoundedRect(rect, radius, radius)
        # top sheen
        sheen = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + h * 0.55))
        sheen.setColorAt(0, QColor(255, 255, 255, 110))
        sheen.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(sheen))
        p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius - 1, radius - 1)
        # hairline edges: bright inner, faint dark outer
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(15, 23, 42, 38), 1))
        p.drawRoundedRect(rect.adjusted(-0.5, -0.5, 0.5, 0.5), radius + 0.5, radius + 0.5)
        p.setPen(QPen(QColor(255, 255, 255, 210), 1))
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius - 0.5, radius - 0.5)

        # header: mood dot + "ZAVERO · GUIDE"
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(mood)
        p.drawEllipse(QPointF(rect.x() + pad + 3.5, rect.y() + 15.5), 3.5, 3.5)
        head = ui_font(7.5, bold=True)
        head.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
        p.setFont(head)
        p.setPen(QColor(71, 85, 105))
        p.drawText(QRectF(rect.x() + pad + 12, rect.y() + 8, w - 2 * pad - 12, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"ZAVERO · {self._mode.upper()}")
        p.translate(rect.x() + pad, rect.y() + 28)
        doc.drawContents(p)
        p.restore()

    def _paint_board(self, p: QPainter) -> None:
        """Enlarged diagram in a glass panel. Coloured strokes (circle / path / arrow) draw themselves one
        step at a time, like a teacher with pens, with a caption saying what each stroke means."""
        img, steps, side, born = self._board
        iw, ih = img.width() / self._dpr, img.height() / self._dpr  # logical size of the crop
        k = min(min(640, self.width() * 0.47) / iw, min(420, self.height() * 0.55) / ih, 3.0)  # enlarge, max 3x
        w, h, pad, head, cap = iw * k, ih * k, 12, 26, 58
        W, H = w + 2 * pad, h + 2 * pad + head + cap
        x = self.width() - W - 28 if side < 0.5 else 28  # opposite side from the real diagram
        panel = QRectF(x, 48, W, H)
        self._board_rect = panel  # the bubble keeps out of it
        p.setPen(Qt.PenStyle.NoPen)
        for grow, alpha in ((14, 10), (8, 14), (3, 20)):
            p.setBrush(QColor(15, 23, 42, alpha))
            p.drawRoundedRect(panel.adjusted(-grow / 2, grow / 3, grow / 2, grow), 20, 20)
        p.setBrush(QColor(255, 255, 255, 240))
        p.setPen(QPen(QColor(255, 255, 255, 220), 1))
        p.drawRoundedRect(panel, 18, 18)
        p.setPen(QColor(71, 85, 105))
        head_font = ui_font(7.5, bold=True)
        head_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
        p.setFont(head_font)
        p.drawText(QRectF(x + pad + 4, 48 + 6, W - 2 * pad, 18), Qt.AlignmentFlag.AlignLeft,
                   "ZAVERO · WHITEBOARD" if side < 0 else "ZAVERO · DIAGRAM")
        p.setFont(ui_font(7.5))
        p.drawText(QRectF(x + pad, 48 + 6, W - 2 * pad - 4, 18), Qt.AlignmentFlag.AlignRight, "Esc to close")

        area = QRectF(x + pad, 48 + head + pad - 4, w, h)
        p.save()
        clip = QPainterPath()
        clip.addRoundedRect(area, 10, 10)
        p.setClipPath(clip)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(area, img)
        p.restore()
        if not steps:
            return

        # Which step is being drawn now. After the last one, keep cycling the highlight so it can be re-read.
        n, age = len(steps), self._t - born
        durs = [1.0 if s["shape"] == "text" else STEP_S for s in steps]  # writing a label is quick
        starts = [sum(durs[:i]) for i in range(n)]
        drawing = age < sum(durs)
        if drawing:
            cur = max(i for i in range(n) if starts[i] <= age)
        else:
            teach = [i for i in range(n) if steps[i]["shape"] != "text"] or list(range(n))
            cur = teach[int((age - sum(durs)) / STEP_S) % len(teach)]
        for i, s in enumerate(steps):
            t = age - starts[i]
            if drawing and t < 0:
                break
            prog = min(1.0, t / (0.6 if s["shape"] == "text" else 1.3)) if drawing else 1.0
            self._paint_stroke(p, s, i, area, prog, highlight=(i == cur), faded=(i != cur), clean=side < 0)

        # caption: what the current stroke means
        s = steps[cur]
        col = QColor(PENS[s["color"]])
        box = QRectF(area.left(), area.bottom() + 8, w, cap - 12)
        tint = QColor(col)
        tint.setAlpha(28)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tint)
        p.drawRoundedRect(box, 10, 10)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(box.left(), box.top(), 5, box.height()), 2.5, 2.5)
        doc = QTextDocument()
        doc.setDefaultFont(ui_font(9.5))
        doc.setDocumentMargin(0)
        doc.setHtml(f"<div style='color:#0F172A'><b style='color:{col.name()}'>{cur + 1}. "
                    f"{html.escape(s['label'])}</b> – {html.escape(s['detail'])}</div>")
        doc.setTextWidth(w - 28)
        p.save()
        p.translate(box.left() + 16, box.top() + max(4.0, (box.height() - doc.size().height()) / 2))
        doc.drawContents(p)
        p.restore()

    def _paint_stroke(self, p: QPainter, s: dict, i: int, area: QRectF, prog: float,
                      highlight: bool, faded: bool, clean: bool = False) -> None:
        """One teacher stroke: a circle that closes around a part, a path/arrow/line that grows, a polygon,
        or handwritten text. clean=True (whiteboard): no number badges, the drawing itself stays tidy."""
        col = QColor(PENS[s["color"]])
        if faded:
            col.setAlphaF(0.6)
        pts = [area.topLeft() + QPointF(fx * area.width(), fy * area.height()) for fx, fy in s["pts"]]
        under = QPen(QColor(255, 255, 255, 190 if not faded else 120), 8.5)
        ink = QPen(col, 4.5)
        for pen in (under, ink):
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setBrush(Qt.BrushStyle.NoBrush)

        if s["shape"] == "circle":
            c, r = pts[0], max(14.0, s.get("fr", 0.07) * area.width())
            rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
            span = int(-360 * 16 * prog)  # clockwise from the top, like a hand drawing a ring
            for pen in (under, ink):
                p.setPen(pen)
                p.drawArc(rect, 90 * 16, span)
            badge = c + QPointF(-r * 0.72, -r * 0.72)
        elif s["shape"] == "text":  # handwriting: the text appears letter by letter
            word = s.get("text", "")[: max(1, math.ceil(len(s.get("text", "")) * prog))]
            f = ui_font(17, bold=True)
            p.setFont(f)
            tw = p.fontMetrics().horizontalAdvance(s.get("text", "")) + 8
            box = QRectF(pts[0].x() - tw / 2, pts[0].y() - 15, tw, 30)
            p.setPen(QColor(255, 255, 255, 200))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):  # white halo keeps it readable on lines
                p.drawText(box.translated(dx, dy), Qt.AlignmentFlag.AlignCenter, word)
            p.setPen(col)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, word)
            return  # text needs no number badge
        else:
            path = QPainterPath(pts[0])
            if s["shape"] == "polygon":  # straight sides, closed, e.g. a triangle
                for q in pts[1:] + pts[:1]:
                    path.lineTo(q)
            elif len(pts) == 2:
                path.lineTo(pts[1])
            else:  # smooth curve through the points (midpoint quadratic)
                for a, b in zip(pts[1:-1], pts[2:]):
                    path.quadTo(a, (a + b) / 2)
                path.lineTo(pts[-1])
            steps_n = 48
            part = QPainterPath(path.pointAtPercent(0))
            for j in range(1, steps_n + 1):
                part.lineTo(path.pointAtPercent(prog * j / steps_n))
            for pen in (under, ink):
                p.setPen(pen)
                p.drawPath(part)
            if prog > 0.05 and s["shape"] in ("path", "arrow"):  # arrowhead at the pen tip: direction of flow
                tip = path.pointAtPercent(prog)
                ang = math.radians(-path.angleAtPercent(max(0.0, prog - 0.01)))
                head = QPainterPath(tip)
                for da in (2.6, -2.6):
                    head.lineTo(tip + QPointF(math.cos(ang + da) * 13, math.sin(ang + da) * 13))
                    head.moveTo(tip)
                for pen in (under, ink):
                    p.setPen(pen)
                    p.drawPath(head)
            badge = pts[0]

        if prog < 0.15 or clean:
            return
        if highlight:  # the step being explained pulses
            glow = QColor(PENS[s["color"]])
            glow.setAlphaF(max(0.0, 0.45 - 0.25 * math.sin(self._t * 5)))
            p.setPen(QPen(glow, 3))
            p.drawEllipse(badge, 17, 17)
        p.setPen(QPen(QColor("white"), 2))
        p.setBrush(QColor(PENS[s["color"]]))
        p.drawEllipse(badge, 11, 11)
        p.setPen(QColor("white"))
        p.setFont(ui_font(8.5, bold=True))
        p.drawText(QRectF(badge.x() - 11, badge.y() - 11, 22, 22), Qt.AlignmentFlag.AlignCenter, str(i + 1))
        if s.get("label") and (highlight or prog >= 1.0):  # label pill above the badge (below if no room)
            p.setFont(ui_font(8, bold=True))
            tw = p.fontMetrics().horizontalAdvance(s["label"]) + 14
            lx = min(max(badge.x() - tw / 2, area.left() + 2), area.right() - tw - 2)
            ly = badge.y() - 38 if badge.y() - 38 > area.top() else badge.y() + 16
            pill = QRectF(lx, ly, tw, 21)
            p.setPen(Qt.PenStyle.NoPen)
            bg = QColor(PENS[s["color"]]).darker(160) if highlight else QColor(17, 24, 39, 200)
            p.setBrush(bg)
            p.drawRoundedRect(pill, 10.5, 10.5)
            p.setPen(QColor("white"))
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, s["label"])

    def _bubble_rect(self, w: float, h: float) -> QRectF:
        """Place the bubble beside the avatar, on-screen, not covering the target."""
        a, gap = self._avatar, R + 14
        candidates = [
            QRectF(a.x() - gap - w, a.y() - h / 2, w, h),   # left
            QRectF(a.x() + gap, a.y() - h / 2, w, h),       # right
            QRectF(a.x() - w / 2, a.y() - gap - h, w, h),   # above
            QRectF(a.x() - w / 2, a.y() + gap, w, h),       # below
        ]
        screen = self._work_area()
        board = getattr(self, "_board_rect", None) if self._board else None
        if board is not None:  # a diagram panel is open: bubble below it, else beside it
            candidates[:0] = [QRectF(board.right() - w, board.bottom() + 12, w, h),
                              QRectF(board.left() - w - 12, board.top(), w, h),
                              QRectF(board.right() + 12, board.top(), w, h)]
        for r in candidates:
            if not screen.contains(r):
                continue
            if self._target is not None and r.adjusted(-30, -30, 30, 30).contains(self._target):
                continue
            if self._following and r.adjusted(-24, -24, 24, 24).contains(self._cursor):
                continue  # don't cover what the user is looking at
            if board is not None and r.intersects(board):
                continue
            return r
        r = candidates[0]
        r.moveLeft(min(max(r.left(), screen.left()), screen.right() - w))
        r.moveTop(min(max(r.top(), screen.top()), screen.bottom() - h))
        return r

    def _work_area(self) -> QRectF:
        """Where bubbles may go: the screen minus the taskbar, 12 px in from the edges."""
        g = self.geometry()
        return safe_area(QRectF(QApplication.primaryScreen().availableGeometry()), QPointF(g.x(), g.y()))


if __name__ == "__main__":
    # Preview: avatar flies to the screen centre and shows a Telugu bubble, then taps.
    app = QApplication(sys.argv)
    ov = Overlay()
    ov.show()
    cx, cy = int(ov.width() * ov._dpr / 2), int(ov.height() * ov._dpr / 2)
    ov.show_text.emit("నమస్తే! నేను **Zavero**. మీకు ఏ బటన్ నొక్కాలో చూపిస్తాను.", "info")
    QTimer.singleShot(1200, lambda: (ov.point_at.emit(cx, cy), ov.set_label.emit("Pay Bill")))
    QTimer.singleShot(1300, lambda: ov.show_text.emit("ఇక్కడ **Pay Bill** బటన్ మీద క్లిక్ చేయండి.", "info"))
    QTimer.singleShot(3500, lambda: ov.tap_at.emit(cx, cy))
    QTimer.singleShot(3600, lambda: ov.set_mode.emit("Doing"))
    QTimer.singleShot(3600, lambda: ov.show_text.emit("I'm clicking **Pay Bill** for you.", "info"))
    QTimer.singleShot(5500, lambda: ov.set_listening.emit(True))
    QTimer.singleShot(5500, lambda: ov.show_text.emit("Listening…", "listen"))
    QTimer.singleShot(7500, lambda: (ov.set_listening.emit(False), ov.go_home.emit(),
                                     ov.show_text.emit("అయిపోయింది! ✅", "done")))
    QTimer.singleShot(10000, app.quit)
    sys.exit(app.exec())
