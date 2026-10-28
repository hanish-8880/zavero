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

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QCursor, QFont, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QRadialGradient, QTextDocument, QTransform,
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
}
TARGET = QColor("#FFB020")


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
    tap_at = pyqtSignal(int, int)      # real screen px
    go_home = pyqtSignal()             # avatar back to its corner, no target
    set_listening = pyqtSignal(bool)
    set_mode = pyqtSignal(str)         # "Guide" / "Doing" / ...
    set_thinking = pyqtSignal(bool)    # thinking dots while waiting for the model
    hide_text = pyqtSignal()
    attention = pyqtSignal()           # Chai twirls to catch the user's eye (reminders)
    show_board = pyqtSignal(bytes, list, float)  # PNG of a diagram, marks [{fx, fy, label}], its x on screen 0..1
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

        self._fly = QVariantAnimation(self)
        self._fly.setDuration(550)
        self._fly.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fly.valueChanged.connect(self._set_avatar)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

        self.show_text.connect(self._on_text)
        self.point_at.connect(self._on_point)
        self.tap_at.connect(self._on_tap)
        self.go_home.connect(self._on_home)
        self.set_listening.connect(self._on_listening)
        self.set_mode.connect(self._on_mode)
        self.set_thinking.connect(self._on_thinking)
        self.hide_text.connect(lambda: self._on_text("", self._mood))
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
        return not self._invisible and self._on_chai(self.local(x, y))

    # --- dragging Chai (events come from _ChaiWindow, in overlay coordinates) ----
    def _drag_start(self, pos: QPointF) -> None:
        if self._on_chai(pos):
            self._fly.stop()
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
        self._text, self._mood = text, mood
        self.update()
        if mood == "done" and text:  # finished messages fade away on their own
            QTimer.singleShot(10_000, lambda: self._text == text and self._on_text("", mood))

    def _on_board(self, png: bytes, marks: list, side: float) -> None:
        img = QImage.fromData(png)
        self._board = (img, marks, side, self._t) if not img.isNull() else None
        self._target = None
        self.update()

    def _on_point(self, x: int, y: int) -> None:
        self._target = self.local(x, y)
        if self._drag is None:
            self._fly_to(self._perch(self._target))

    def _on_tap(self, x: int, y: int) -> None:
        self._taps.append((self.local(x, y), self._t))

    def _on_home(self) -> None:
        self._target = None
        if self._drag is None:
            self._fly_to(self._home)

    def _on_listening(self, on: bool) -> None:
        self._listening = on
        self.update()

    def _on_thinking(self, on: bool) -> None:
        self._thinking = on
        self.update()

    def _on_mode(self, mode: str) -> None:
        self._mode = mode
        self.update()

    def _set_avatar(self, p) -> None:
        self._avatar = QPointF(p)
        self._sync_chai()
        self.update()

    def _fly_to(self, p: QPointF) -> None:
        self._fly.stop()
        self._fly.setStartValue(QPointF(self._avatar))
        self._fly.setEndValue(p)
        self._fly.start()

    def _perch(self, t: QPointF) -> QPointF:
        """Where the avatar sits next to a target: up-left of it, or flipped near edges."""
        dx = -62 if t.x() > 120 else 62
        dy = -62 if t.y() > 120 else 62
        return self._clamp(QPointF(t.x() + dx, t.y() + dy))

    def _tick(self) -> None:
        self._t += 0.033
        self._taps = [(p, b) for p, b in self._taps if self._t - b < 0.7]
        # follow the mouse; catch clicks only while it is over Chai
        cur = QPointF(self.mapFromGlobal(QCursor.pos()))
        d = cur - self._cursor
        speed = math.hypot(d.x(), d.y()) / 0.033
        self._cursor = cur
        hover = self._on_chai(cur) and not self._invisible
        if self._drag is None and hover != self._hover:
            self._chai.setCursor(Qt.CursorShape.OpenHandCursor if hover else Qt.CursorShape.ArrowCursor)
        self._hover = hover
        stroking = hover and speed > 40 and self._drag is None
        self._pet += ((1.0 if stroking else 0.0) - self._pet) * (0.18 if stroking else 0.06)
        self.update()
        self._chai.update()

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
        self._look += (look - self._look) * 0.22

        if self._t > self._next_blink:  # random blinks, sometimes a double blink
            self._blink_at = self._t
            self._double = random.random() < 0.25
            self._next_blink = self._t + 2 + random.random() * 3.5
        d0 = self._t - self._blink_at
        closed = math.sin(math.pi * d0 / 0.16) if d0 < 0.16 else 0.0
        if self._double and 0.26 < d0 < 0.42:
            closed = math.sin(math.pi * (d0 - 0.26) / 0.16)

        rot = self._look.x() * 5 + math.sin(self._t * 14) * 4 * self._pet  # lean toward the look + petting wiggle
        happy = (self._mood == "done" and bool(self._text)) or self._pet > 0.45 or spin < 0.95
        paint_chai(p, c, R, self._t, self._look, listening=self._listening, happy=happy,
                   eye_open=1 - closed, steam=not self._thinking, rot=rot, spin=spin)
        if self._thinking:  # three bouncing dots above the head
            for k in range(3):
                dy = -abs(math.sin(self._t * 6 + k * 0.7)) * 5
                pos = c + QPointF(-10 + k * 10, -R - 12 + dy)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 235))
                p.drawEllipse(pos, 4.5, 4.5)
                p.setBrush(mood)
                p.drawEllipse(pos, 2.6, 2.6)

    def _paint_bubble(self, p: QPainter) -> None:
        pad = 14
        doc = QTextDocument()
        doc.setDefaultFont(ui_font(10.5))
        doc.setDocumentMargin(0)
        doc.setHtml(f"<div style='color:#0F172A; line-height:125%'>{to_html(self._text)}</div>")
        doc.setTextWidth(BUBBLE_W - 2 * pad)
        w = max(160, min(BUBBLE_W, doc.idealWidth() + 2 * pad))
        doc.setTextWidth(w - 2 * pad)
        h = doc.size().height() + 44  # text + header + padding
        rect = self._bubble_rect(w, h)
        radius = 16
        mood = MOODS.get(self._mood, ACCENT)

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
        p.save()
        p.translate(rect.x() + pad, rect.y() + 28)
        doc.drawContents(p)
        p.restore()

    def _paint_board(self, p: QPainter) -> None:
        """Enlarged diagram in a glass panel, with numbered marks drawn on it one by one."""
        img, marks, side, born = self._board
        iw, ih = img.width() / self._dpr, img.height() / self._dpr  # logical size of the crop
        k = min(min(640, self.width() * 0.47) / iw, min(460, self.height() * 0.6) / ih, 3.0)  # enlarge, max 3x
        w, h, pad, head = iw * k, ih * k, 12, 26
        W, H = w + 2 * pad, h + 2 * pad + head
        x = self.width() - W - 28 if side < 0.5 else 28  # opposite side from the real diagram
        panel = QRectF(x, 48, W, H)
        self._board_rect = panel  # the bubble keeps out of it
        p.setPen(Qt.PenStyle.NoPen)
        for grow, alpha in ((14, 10), (8, 14), (3, 20)):
            p.setBrush(QColor(15, 23, 42, alpha))
            p.drawRoundedRect(panel.adjusted(-grow / 2, grow / 3, grow / 2, grow), 20, 20)
        p.setBrush(QColor(255, 255, 255, 238))
        p.setPen(QPen(QColor(255, 255, 255, 220), 1))
        p.drawRoundedRect(panel, 18, 18)
        p.setPen(QColor(71, 85, 105))
        head_font = ui_font(7.5, bold=True)
        head_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
        p.setFont(head_font)
        p.drawText(QRectF(x + pad + 4, 48 + 6, W - 2 * pad, 18), Qt.AlignmentFlag.AlignLeft, "ZAVERO · DIAGRAM")
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

        ink = QColor("#FF4D2E")
        age = self._t - born
        shown = min(len(marks), int(age / 0.8) + 1)  # a new mark every 0.8 s, like a teacher drawing
        pts = [area.topLeft() + QPointF(m["fx"] * w, m["fy"] * h) for m in marks]
        for i in range(1, shown):  # dashed path from one part to the next
            grow = min(1.0, (age - i * 0.8) / 0.45)
            a, b = pts[i - 1], pts[i - 1] + (pts[i] - pts[i - 1]) * grow
            pen = QPen(QColor(255, 77, 46, 120), 1.6, Qt.PenStyle.DashLine)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(a, b)
        for i in range(shown):
            m, c = marks[i], pts[i]
            t = age - i * 0.8
            r = 12 * min(1.0, t / 0.25)
            if i == shown - 1:  # newest mark pulses
                ring = QColor(ink)
                ring.setAlphaF(max(0.0, 0.5 - 0.25 * math.sin(self._t * 5)))
                p.setPen(QPen(ring, 3))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, r + 7, r + 7)
            p.setPen(QPen(QColor("white"), 2.5))
            p.setBrush(ink)
            p.drawEllipse(c, r, r)
            if t < 0.2:
                continue
            p.setPen(QColor("white"))
            p.setFont(ui_font(9, bold=True))
            p.drawText(QRectF(c.x() - 12, c.y() - 12, 24, 24), Qt.AlignmentFlag.AlignCenter, str(i + 1))
            if m.get("label"):  # label pill above the mark (below if no room), so the diagram text stays visible
                p.setFont(ui_font(8.5, bold=True))
                tw = p.fontMetrics().horizontalAdvance(m["label"]) + 16
                lx = min(max(c.x() - tw / 2, panel.left() + 6), panel.right() - tw - 6)
                ly = c.y() - r - 30 if c.y() - r - 30 > area.top() else c.y() + r + 8
                pill = QRectF(lx, ly, tw, 22)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(17, 24, 39, 215))
                p.drawRoundedRect(pill, 11, 11)
                p.setPen(QColor("white"))
                p.drawText(pill, Qt.AlignmentFlag.AlignCenter, m["label"])

    def _bubble_rect(self, w: float, h: float) -> QRectF:
        """Place the bubble beside the avatar, on-screen, not covering the target."""
        a, gap = self._avatar, R + 14
        candidates = [
            QRectF(a.x() - gap - w, a.y() - h / 2, w, h),   # left
            QRectF(a.x() + gap, a.y() - h / 2, w, h),       # right
            QRectF(a.x() - w / 2, a.y() - gap - h, w, h),   # above
            QRectF(a.x() - w / 2, a.y() + gap, w, h),       # below
        ]
        screen = QRectF(8, 8, self.width() - 16, self.height() - 16)
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
            if board is not None and r.intersects(board):
                continue
            return r
        r = candidates[0]
        r.moveLeft(min(max(r.left(), 8), self.width() - w - 8))
        r.moveTop(min(max(r.top(), 8), self.height() - h - 8))
        return r


if __name__ == "__main__":
    # Preview: avatar flies to the screen centre and shows a Telugu bubble, then taps.
    app = QApplication(sys.argv)
    ov = Overlay()
    ov.show()
    cx, cy = int(ov.width() * ov._dpr / 2), int(ov.height() * ov._dpr / 2)
    ov.show_text.emit("నమస్తే! నేను **Zavero**. మీకు ఏ బటన్ నొక్కాలో చూపిస్తాను.", "info")
    QTimer.singleShot(1200, lambda: ov.point_at.emit(cx, cy))
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
