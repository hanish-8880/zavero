"""The 3D board: a rotating teaching model (talk.clean_scene) on a white rounded card over the desktop.

A frameless, always-on-top web view (transparent window, white card inside) running three.js (bundled in
zavero/web, works offline). The camera fits the whole model inside the card.
Parts appear step by step; the bubble explains the current step. Next -> (bubble button, the page's own
button, or saying next / inka / aage) shows the next step; the model also moves on by itself every AUTO_S.
Drag = turn, scroll = zoom, Esc / ✕ = close. Create and use it only in the GUI thread (Overlay does).
"""
import json
from pathlib import Path

from PyQt6.QtCore import QRectF, Qt, QTimer, QUrl
from PyQt6.QtGui import QColor
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication

PAGE = Path(__file__).resolve().parent / "web" / "board3d.html"
SIZE = (580, 540)
AUTO_S = 7.0  # seconds per step while the user just watches


class Board3D(QWebEngineView):
    def __init__(self, ov) -> None:
        super().__init__()
        self.ov = ov
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet("background: transparent")
        self.page().setBackgroundColor(QColor(0, 0, 0, 0))
        self.titleChanged.connect(self._on_cmd)
        self.scene: dict | None = None
        self.step = 0
        self._ready = False
        self._auto = QTimer(self)
        self._auto.setInterval(int(AUTO_S * 1000))
        self._auto.timeout.connect(self._auto_next)
        self.setUrl(QUrl.fromLocalFile(str(PAGE)))

    @property
    def is_open(self) -> bool:
        return self.scene is not None and self.isVisible()

    def rect_in_overlay(self) -> QRectF:
        g, o = self.geometry(), self.ov.geometry()
        return QRectF(g.x() - o.x(), g.y() - o.y(), g.width(), g.height())

    def show_scene(self, scene: dict) -> None:
        self.scene, self.step = scene, 1
        area = QApplication.primaryScreen().availableGeometry()
        w, h = SIZE
        self.setGeometry(area.right() - w - 24, area.top() + 64, w, h)  # top right, below the browser bar; Chai and the bubble stay below
        self.show()
        if self._ready:
            self._load()

    def _load(self) -> None:
        self.page().runJavaScript(f"loadScene({json.dumps(self.scene, ensure_ascii=False)})")
        self.step = 1
        self._announce()
        self._auto.start()

    def _on_cmd(self, title: str) -> None:
        cmd = title.split(":", 1)[0]
        if cmd == "ready":
            self._ready = True
            if self.scene:
                self._load()
        elif cmd == "next":
            self.next()
        elif cmd == "close":
            self.close_board()

    def next(self) -> None:
        """Next step; after the last one, start again from the first (for a second look)."""
        if not self.scene:
            return
        n = len(self.scene["steps"])
        self.step = self.step + 1 if self.step < n else 1
        self.page().runJavaScript(f"setStep({self.step})")
        self._announce()
        self._auto.start()  # restart the clock: the user gets the full time on this step

    def _auto_next(self) -> None:
        if self.scene and self.step < len(self.scene["steps"]):
            self.next()
        else:
            self._auto.stop()  # all parts shown: stay on the last step

    def _announce(self) -> None:
        """The bubble explains the current step (stays until the board closes)."""
        steps = self.scene["steps"]
        s = steps[self.step - 1]
        head = f"{self.scene['answer']}\n\n" if self.step == 1 and self.scene.get("answer") else ""
        self.ov._on_text(f"{head}**{s['n']}/{len(steps)} · {s['label']}**\n{s['detail']}".strip(), "hold", ["step"])

    def close_board(self) -> None:
        if self.scene is None:
            return
        self.scene = None
        self._auto.stop()
        self.hide()
        self.ov._on_text("", "info")
