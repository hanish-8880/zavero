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


def test_only_while_i_talk_fades_out():
    ov = _overlay()
    ov.show_mode = "talk"
    ov._on_listening(True)
    ov._step_visibility()
    assert ov._opacity == 1.0
    ov._on_listening(False)
    ov._t += ov.ACTIVE_S + 1
    for _ in range(30):  # 0.5 s of frames
        ov._step_visibility()
    assert ov._opacity == 0.0
    ov.show_mode = "always"
    ov._step_visibility()
    assert ov._opacity == 1.0


def test_pen_trail_while_talking():
    ov = _overlay()
    ov._on_listening(True)
    for x, y in [(100, 100), (101, 100), (140, 120), (160, 160)]:  # tiny moves are skipped
        ov._cursor = QPointF(x, y)
        ov._step_ink()
    ov._on_listening(False)
    ink = ov.take_ink()
    assert len(ink) == 3 and ov._ink == []
    assert ink[0] == (round(100 * ov._dpr), round(100 * ov._dpr))  # real screen px
