import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from zavero.overlay import Overlay  # noqa: E402

app = QApplication.instance() or QApplication([])


def _overlay() -> Overlay:
    ov = Overlay()
    ov.resize(1536, 864)
    ov._home = ov._avatar = QPointF(1466, 734)
    ov._dt = 1 / 60
    return ov


def test_follows_the_mouse_while_helping():
    ov = _overlay()
    ov._cursor = QPointF(400, 300)
    assert not ov._should_follow()  # idle: stays in its corner
    ov._on_text("Click **Pay Bill**", "info")
    assert ov._should_follow()
    for _ in range(120):  # 2 s of frames
        ov._step_follow()
    goal = QPointF(448, 340)
    assert abs(ov._avatar.x() - goal.x()) < 3 and abs(ov._avatar.y() - goal.y()) < 3


def test_flips_near_edges_and_respects_settings():
    ov = _overlay()
    ov._cursor = QPointF(1530, 860)  # bottom-right corner: ride up-left instead
    g = ov._follow_goal()
    assert g.x() < 1530 and g.y() < 860
    ov._on_text("hi", "info")
    ov.follow_mode = "corner"
    assert not ov._should_follow()
    ov.follow_mode = "auto"
    ov._target = QPointF(10, 10)  # pointing at a button beats following
    assert not ov._should_follow()


def test_goes_home_when_done():
    ov = _overlay()
    ov._cursor = QPointF(400, 300)
    ov._on_text("hi", "info")
    ov._step_follow()
    ov._t += ov.ACTIVE_S + 1  # nothing new for a while
    ov._step_follow()
    assert ov._flight is not None and ov._flight[2] == ov._home
