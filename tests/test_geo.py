import math

from fuel_route.domain.geo import cumulative_miles, haversine_miles, in_usa, resample, simplify


def test_haversine_known_distance():
    # NYC -> LA great-circle distance is ~2,446 miles.
    assert math.isclose(haversine_miles((40.7128, -74.0060), (34.0522, -118.2437)), 2446, rel_tol=0.01)


def test_in_usa():
    assert in_usa((39.7, -104.9))  # Denver
    assert in_usa((61.2, -149.9))  # Anchorage
    assert not in_usa((48.85, 2.35))  # Paris
    assert not in_usa((19.4, -99.1))  # Mexico City


def test_resample_spacing_and_endpoints():
    line = [(40.0, -100.0), (40.0, -99.0), (40.0, -98.0)]
    total = cumulative_miles(line)[-1]
    pts = resample(line, 1.0)
    assert pts[0] == ((40.0, -100.0), 0.0)
    assert pts[-1][0] == (40.0, -98.0)
    assert math.isclose(pts[-1][1], total, rel_tol=1e-9)
    gaps = [b[1] - a[1] for a, b in zip(pts, pts[1:])]
    assert max(gaps) <= 1.0 + 1e-9
    assert len(pts) == math.floor(total) + 2


def test_simplify_drops_collinear_points_keeps_corners():
    line = [(0.0, x / 10) for x in range(11)] + [(y / 10, 1.0) for y in range(1, 11)]
    out = simplify(line, 1e-6)
    assert out == [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
