import math

from zavero.highlight import _length, centerline


def test_centerline_follows_a_bent_tube():
    # an L-shaped "tube": down 100 px, then right 100 px, 10 px thick
    pts = [(x, y) for x in range(0, 10) for y in range(0, 100)] + [(x, y) for x in range(0, 100) for y in range(90, 100)]
    line = centerline(pts, n=8)
    assert len(line) >= 6
    assert all(-1 <= x <= 100 and -1 <= y <= 100 for x, y in line)
    assert _length(line) > 80


def test_centerline_straight_tube_is_its_middle():
    pts = [(x, y) for x in range(0, 200) for y in range(48, 53)]  # horizontal tube around y=50
    line = centerline(pts, n=4)
    assert all(abs(y - 50) < 1.5 for _, y in line)
    assert math.isclose(_length(line), 150, rel_tol=0.1)  # spans most of the 200 px (slice centres)
