"""Transparent, click-through, always-on-top overlay: Zavero's avatar, speech bubble and target ring.

Other threads drive it only through the signals (thread-safe). Coordinates passed in are
real screen pixels (what driver.to_screen returns); the overlay converts them to Qt pixels.
The overlay blanks itself for a moment around each model screenshot, so the model never sees
the avatar, but screen recordings (demo video) still do.

Preview without the rest of the app:
    python -m zavero.overlay
"""
import ctypes
import html
import math
import re
import sys
import time

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient, QTextDocument
from PyQt6.QtWidgets import QApplication, QWidget

R = 26  # avatar radius
BUBBLE_W = 340
FONT = "Nirmala UI"  # ships with Windows; covers Telugu, Devanagari and Latin

ACCENT = QColor("#6D4AFF")
MOODS = {
    "info": QColor("#6D4AFF"),
    "listen": QColor("#00A3FF"),
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


class Overlay(QWidget):
    show_text = pyqtSignal(str, str)   # text, mood
    point_at = pyqtSignal(int, int)    # real screen px
    tap_at = pyqtSignal(int, int)      # real screen px
    go_home = pyqtSignal()             # avatar back to its corner, no target
    set_listening = pyqtSignal(bool)
    set_mode = pyqtSignal(str)         # "Guide" / "Doing" / ...
    hide_text = pyqtSignal()
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
        self._avatar = QPointF(self._home)
        self._target: QPointF | None = None
        self._text = ""
        self._mood = "info"
        self._mode = "Guide"
        self._listening = False
        self._taps: list[tuple[QPointF, float]] = []
        self._t = 0.0

        self._fly = QVariantAnimation(self)
        self._fly.setDuration(550)
        self._fly.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fly.valueChanged.connect(self._set_avatar)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

        self.show_text.connect(self._on_text)
        self.point_at.connect(self._on_point)
        self.tap_at.connect(self._on_tap)
        self.go_home.connect(self._on_home)
        self.set_listening.connect(self._on_listening)
        self.set_mode.connect(self._on_mode)
        self.hide_text.connect(lambda: self._on_text("", self._mood))
        self._invisible = False
        self._capture_sig.connect(self._set_invisible, Qt.ConnectionType.BlockingQueuedConnection)

    # --- window setup ---------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if sys.platform == "win32":
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            ex = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
            # WS_EX_TRANSPARENT | WS_EX_NOACTIVATE: clicks pass through, never steals focus
            user32.SetWindowLongW(hwnd, -20, ex | 0x20 | 0x08000000)

    def _set_invisible(self, on: bool) -> None:
        self._invisible = on
        self.repaint()

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

    # --- slots ----------------------------------------------------------
    def _on_text(self, text: str, mood: str) -> None:
        self._text, self._mood = text, mood
        self.update()

    def _on_point(self, x: int, y: int) -> None:
        self._target = self.local(x, y)
        self._fly_to(self._perch(self._target))

    def _on_tap(self, x: int, y: int) -> None:
        self._taps.append((self.local(x, y), self._t))

    def _on_home(self) -> None:
        self._target = None
        self._fly_to(self._home)

    def _on_listening(self, on: bool) -> None:
        self._listening = on
        self.update()

    def _on_mode(self, mode: str) -> None:
        self._mode = mode
        self.update()

    def _set_avatar(self, p) -> None:
        self._avatar = QPointF(p)
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
        x = min(max(t.x() + dx, R + 8), self.width() - R - 8)
        y = min(max(t.y() + dy, R + 8), self.height() - R - 8)
        return QPointF(x, y)

    def _tick(self) -> None:
        self._t += 0.04
        self._taps = [(p, b) for p, b in self._taps if self._t - b < 0.7]
        self.update()

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
            p.setPen(QPen(c, 4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            r = 8 + 40 * age
            p.drawEllipse(pos, r, r)
        self._paint_avatar(p)
        if self._text:
            self._paint_bubble(p)

    def _paint_target(self, p: QPainter) -> None:
        t = self._target
        pulse = 18 + 5 * math.sin(self._t * 5)
        glow = QColor(TARGET)
        glow.setAlpha(50)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(t, pulse + 6, pulse + 6)
        p.setPen(QPen(TARGET, 3))
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
            pen = QPen(TARGET, 2.5, Qt.PenStyle.DashLine)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawPath(path)

    def _paint_avatar(self, p: QPainter) -> None:
        a = self._avatar
        bob = math.sin(self._t * 2.2) * 2.5
        c = QPointF(a.x(), a.y() + bob)
        mood = MOODS["listen"] if self._listening else ACCENT
        if self._listening:
            for k in range(2):
                phase = (self._t * 1.2 + k * 0.5) % 1.0
                ring = QColor(mood)
                ring.setAlphaF(0.5 * (1 - phase))
                p.setPen(QPen(ring, 3))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, R + 4 + 22 * phase, R + 4 + 22 * phase)
        # soft shadow
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 45))
        p.drawEllipse(QPointF(a.x(), a.y() + R + 8), R * 0.75, 5)
        # body
        g = QRadialGradient(c + QPointF(-R * 0.35, -R * 0.45), R * 1.6)
        g.setColorAt(0, mood.lighter(160))
        g.setColorAt(0.55, mood)
        g.setColorAt(1, mood.darker(160))
        p.setBrush(QBrush(g))
        p.setPen(QPen(QColor(255, 255, 255, 220), 2))
        p.drawEllipse(c, R, R)
        # eyes look toward the target
        look = QPointF(0, 0)
        if self._target is not None:
            d = self._target - a
            n = math.hypot(d.x(), d.y()) or 1
            look = QPointF(d.x() / n * 3, d.y() / n * 3)
        blink = (self._t % 4.0) < 0.12
        for ex in (-9, 9):
            eye = c + QPointF(ex, -4)
            p.setBrush(QColor("white"))
            p.setPen(Qt.PenStyle.NoPen)
            if blink:
                p.drawRoundedRect(QRectF(eye.x() - 6, eye.y() - 1.2, 12, 2.4), 1.2, 1.2)
            else:
                p.drawEllipse(eye, 6, 7)
                p.setBrush(QColor("#1E1B4B"))
                p.drawEllipse(eye + look, 3, 3.5)
        # smile
        smile = QPen(QColor("white"), 2.2)
        smile.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(smile)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(c.x() - 7, c.y() + 1, 14, 10), 200 * 16, 140 * 16)

    def _paint_bubble(self, p: QPainter) -> None:
        doc = QTextDocument()
        doc.setDefaultFont(QFont(FONT, 12))
        doc.setDocumentMargin(0)
        doc.setHtml(f"<div style='color:#111827'>{to_html(self._text)}</div>")
        doc.setTextWidth(BUBBLE_W - 32)
        w = min(BUBBLE_W, doc.idealWidth() + 32)
        doc.setTextWidth(w - 32)
        h = doc.size().height() + 48  # text + header + padding
        rect = self._bubble_rect(w, h)

        mood = MOODS.get(self._mood, ACCENT)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawRoundedRect(rect.translated(0, 3), 14, 14)
        p.setBrush(QColor(255, 255, 255, 250))
        p.setPen(QPen(mood, 2))
        p.drawRoundedRect(rect, 14, 14)
        # header chip: "ZAVERO · GUIDE"
        p.setPen(mood)
        p.setFont(QFont(FONT, 8, QFont.Weight.Bold))
        p.drawText(QRectF(rect.x() + 16, rect.y() + 8, w - 32, 18), Qt.AlignmentFlag.AlignLeft,
                   f"ZAVERO · {self._mode.upper()}")
        p.save()
        p.translate(rect.x() + 16, rect.y() + 30)
        doc.drawContents(p)
        p.restore()

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
        for r in candidates:
            if not screen.contains(r):
                continue
            if self._target is not None and r.adjusted(-30, -30, 30, 30).contains(self._target):
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
