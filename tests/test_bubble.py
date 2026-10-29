import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF, QRectF  # noqa: E402

from zavero.overlay import HOVER_ALPHA, reading_time, safe_area  # noqa: E402

from test_follow import _overlay  # noqa: E402


def test_reading_time():
    # counted after typing (16 ms per character, up to 300 characters)
    assert reading_time("ok") == 2 * 0.016 + 10.0                          # short: at least 10 s
    assert abs(reading_time("x" * 100) - (1.6 + 4.0 + 9.0)) < 1e-9         # 4 s + 90 ms per character
    assert reading_time("x" * 2000) == 60.0                                # capped, no typing for long text


def test_safe_area_keeps_out_of_the_taskbar():
    # 1536x864 screen with a 48 px taskbar at the bottom; overlay starts at the screen's top-left.
    area = safe_area(QRectF(0, 0, 1536, 816), QPointF(0, 0))
    assert area == QRectF(12, 12, 1512, 792)
    assert area.bottom() == 804  # 12 px above the taskbar
    # Overlay on a second screen at x=1920: coordinates are relative to the overlay.
    assert safe_area(QRectF(1920, 0, 1280, 760), QPointF(1920, 0)).left() == 12


def test_bubble_fades_after_reading_time_but_hold_stays():
    ov = _overlay()
    ov._on_text("Done! ✅", "done")
    ov._t += reading_time("Done! ✅") + 0.1
    for _ in range(30):  # 0.5 s of frames
        ov._step_bubble()
    assert ov._text == ""
    ov._on_text("Click **Pay Bill**", "hold")
    ov._t += 60
    ov._step_bubble()
    assert ov._text == "Click **Pay Bill**"


def test_click_dismisses_after_5_s_only():
    ov = _overlay()
    ov._on_text("Here is your answer", "info")
    ov._t += 3
    ov._on_dismiss()  # too soon: the user is still reading, the click was for something else
    assert ov._t - ov._shown_at < 5
    ov._t += 3
    ov._on_dismiss()
    for _ in range(30):
        ov._step_bubble()
    assert ov._text == ""
    ov._on_text("Say yes or no", "hold")
    ov._t += 5
    ov._on_dismiss()
    ov._step_bubble()
    assert ov._text == "Say yes or no"


def test_see_through_on_hover():
    ov = _overlay()
    ov._on_text("Hello", "info")
    ov._bubble_last = QRectF(100, 100, 290, 80)
    ov._cursor = QPointF(150, 130)
    for _ in range(12):  # 200 ms
        ov._step_bubble()
    assert ov._hover_alpha == HOVER_ALPHA
    ov._cursor = QPointF(800, 600)
    for _ in range(12):
        ov._step_bubble()
    assert ov._hover_alpha == 1.0


def test_bubble_waits_while_a_diagram_is_explained():
    ov = _overlay()
    ov._board = (None, [{"shape": "circle"}], 0.3, ov._t)  # diagram board open
    ov._on_text("1. Left ventricle - pumps blood", "info")
    for _ in range(600):  # 10 s of frames: the reading clock is paused
        ov._t += ov._dt
        ov._step_bubble()
    assert ov._text


def test_marks_on_the_page_step_through_each_part():
    from zavero.overlay import MARK_S

    ov = _overlay()
    steps = [{"shape": "circle", "color": "red", "pts": [(0.2, 0.5)], "fr": 0.08, "label": "Battery", "detail": "Pushes current",
              "text": "", "look": "", "fill": False},
             {"shape": "circle", "color": "blue", "pts": [(0.7, 0.5)], "fr": 0.08, "label": "Resistor", "detail": "Slows it",
              "text": "", "look": "", "fill": False}]
    ov._on_show_marks(100, 100, 600, 400, steps, "A simple circuit.")
    assert ov.steps_open and "1/2 · Battery" in ov._text and "A simple circuit." in ov._text
    assert ov._buttons == ["close", "step"]                 # Next → button
    ov._t += MARK_S + 0.1
    ov._step_marks()
    assert "2/2 · Resistor" in ov._text                       # moved on by itself after reading time
    ov._t += MARK_S + 0.1
    ov._step_marks()
    assert ov._marks["all"] and "2/2" in ov._text             # stays on the last part
    ov._next_step()
    assert "1/2 · Battery" in ov._text                        # Next walks through again
    ov._on_hide_board()                                       # Esc / scroll / new question
    assert ov._marks is None and not ov.steps_open
