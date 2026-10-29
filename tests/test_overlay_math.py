from PyQt6.QtCore import QPointF

from zavero.overlay import bezier, bezier_flight, partial_markup, smoothstep
from zavero.phrases import POINT_LABELS, point_label


def test_flight_curve():
    p0, p2 = QPointF(0, 500), QPointF(800, 500)
    ctrl, dur = bezier_flight(p0, p2)
    assert ctrl == QPointF(400, 420)  # lifted by min(800 * 0.2, 80)
    assert dur == 1.0
    assert bezier_flight(p0, QPointF(10, 500))[1] == 0.6  # short hops still take 0.6 s
    assert bezier_flight(p0, QPointF(3000, 500))[1] == 1.4
    assert bezier(p0, ctrl, p2, 0)[0] == p0 and bezier(p0, ctrl, p2, 1)[0] == p2
    assert bezier(p0, ctrl, p2, 0.5)[0].y() < 500  # arcs upward
    assert smoothstep(0) == 0 and smoothstep(1) == 1 and smoothstep(0.5) == 0.5


def test_typewriter_keeps_bold():
    assert partial_markup("Click **Pay Bill** now", 9) == "Click **P**"
    assert partial_markup("Click **Pay Bill** now", 18) == "Click **Pay Bill**"
    assert partial_markup("hi", 1) == "h"


def test_point_label():
    assert point_label("Pay Bill") == "Pay Bill"
    assert point_label("", "ఇది ఏంటి?") in POINT_LABELS["te"]
    assert point_label("  ", "ye kya hai") in POINT_LABELS["en"]
