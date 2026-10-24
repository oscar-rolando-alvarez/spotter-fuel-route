import math
from pathlib import Path

import pytest

from fuel_route.domain.geo import Region, cumulative_miles, haversine_miles, resample, simplify
from fuel_route.infrastructure.boundary import load_region

USA = load_region(Path(__file__).resolve().parents[1] / "data" / "us_border.json.gz")


def test_haversine_known_distance():
    # NYC -> LA great-circle distance is ~2,446 miles.
    assert math.isclose(haversine_miles((40.7128, -74.0060), (34.0522, -118.2437)), 2446, rel_tol=0.01)


def test_region_with_hole():
    square = [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0)]
    lake = [(4.0, 4.0), (4.0, 6.0), (6.0, 6.0), (6.0, 4.0)]
    region = Region([[square, lake]])
    assert region.contains((1.0, 1.0))
    assert not region.contains((5.0, 5.0))  # in the hole
    assert not region.contains((11.0, 5.0))


@pytest.mark.parametrize(
    ("place", "point", "inside"),
    [
        ("Detroit, MI", (42.3314, -83.0458), True),
        ("Windsor, ON", (42.3149, -83.0364), False),  # 2 km across the Detroit River
        ("Niagara Falls, NY", (43.0962, -79.0377), True),
        ("Niagara Falls, ON", (43.0896, -79.0849), False),
        ("San Diego, CA", (32.7157, -117.1611), True),
        ("Tijuana, MX", (32.5149, -117.0382), False),
        ("El Paso, TX", (31.7619, -106.4850), True),
        ("Ciudad Juarez, MX", (31.6904, -106.4245), False),
        ("Montreal, QC", (45.5019, -73.5674), False),  # passed the old bounding boxes
        ("Vancouver, BC", (49.2827, -123.1207), False),  # passed the old bounding boxes
        ("Point Roberts, WA", (48.9850, -123.0600), True),  # US exclave
        ("Key West, FL", (24.5551, -81.7800), True),
        ("Anchorage, AK", (61.2181, -149.9003), True),
        ("Honolulu, HI", (21.3069, -157.8583), True),
        ("Paris, FR", (48.85, 2.35), False),
    ],
)
def test_us_border(place, point, inside):
    assert USA.contains(point) is inside, place


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
